"""Connected V2 domain APIs, retaining V1 reconciliation and original IDs."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app import engine
from app.models import Asset, Claim, FollowUpAction, Inspection, Reason
from app.v2_models import (
    AssetBinding,
    BindAsset,
    CaseCreate,
    CaseRecord,
    ClosureCreate,
    ClosureEdit,
    ClosureTransition,
    EnrolInspection,
    FollowUpContext,
    InvestmentProject,
    InvestmentReview,
    InvestmentReviewCreate,
    InvestmentTarget,
    Membership,
    PhysicalAsset,
    PhysicalAssetCreate,
    ProjectCreate,
    ProjectUpdate,
    Revision,
    TargetCreate,
    TargetUpdate,
)
from app.v2_store import V2Store, check_version


def calculate_outcome(target, body):
    if body.status != "supported":
        return {"status": "insufficient_data", "reason": "measurement_not_supported"}
    if body.measured_value is None or body.baseline_value is None:
        return {"status": "insufficient_data", "reason": "missing_baseline_or_measurement"}
    if not body.comparable or body.baseline_period != body.measurement_period:
        return {"status": "insufficient_data", "reason": "incomparable_period_or_method"}
    if body.unit != target.unit or body.currency != target.currency:
        return {"status": "insufficient_data", "reason": "unit_or_currency_mismatch"}
    baseline, measured = Decimal(body.baseline_value), Decimal(body.measured_value)
    result = {"status": "calculated", "difference": str(baseline - measured), "unit": target.unit}
    if baseline <= 0:
        return {"status": "insufficient_data", "reason": "nonpositive_baseline"}
    reduction = (baseline - measured) / baseline * 100
    increase = (measured - baseline) / baseline * 100
    result["reduction_percent"] = str(reduction.quantize(Decimal("0.01")))
    result["increase_percent"] = str(increase.quantize(Decimal("0.01")))
    if target.target_type == "reduction_percent":
        result["target_met"] = reduction >= target.target_value
    elif target.target_type == "increase_percent":
        result["target_met"] = increase >= target.target_value
    else:
        result["target_met"] = (
            measured >= target.target_value
            if target.metric == "output_rate"
            else measured <= target.target_value
        )
    result["meaning"] = (
        "Arithmetic over reviewer-accepted comparable inputs, not an independent financial conclusion"
    )
    return result


def install_v2(app, store, authenticate, get_report):
    service = V2Store(store)
    service.analysts = set(app.state.analyst_actors)
    app.state.v2 = service
    Actor = Annotated[str, Depends(authenticate)]
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)], tags=["V2"])

    @router.get("/capabilities")
    def capabilities():
        import os
        import shutil

        return {
            "product_version": "2",
            "database": store.backend,
            "audio_decode_available": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
            "ai_provider": app.state.ai.name,
            "ai_configured": app.state.ai.configured(),
            "ai_model": os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
            "speech_mode": "short_audio_chunks_not_continuous_streaming",
            "max_audio_seconds": 120,
            "max_audio_bytes": 12 * 1024 * 1024,
            "hardware": "browser_phone_or_laptop; no smart-glasses SDK verified",
            "email_mode": "local_test_inbox",
            "automatic_underwriting": False,
            "analyst_actors": app.state.analyst_actors,
        }

    @router.post("/providers/reload")
    def reload_provider(body: Reason, actor: Actor):
        import os
        from pathlib import Path

        from dotenv import dotenv_values

        from app.v2_providers import GeminiProvider

        settings_file = Path(
            os.environ.get("CDI_ENV_FILE", str(Path(__file__).resolve().parents[1] / ".env"))
        )
        try:
            values = dotenv_values(settings_file)
        except OSError as exc:
            raise HTTPException(
                503, "Private configuration file is unavailable; restore local file access and retry"
            ) from exc
        for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL"):
            if key in values:
                os.environ[key] = values[key] or ""
        app.state.ai = GeminiProvider()
        return {
            "provider": "gemini",
            "configured": app.state.ai.configured(),
            "model": app.state.ai.model,
        }

    @router.post("/cases", response_model=CaseRecord, status_code=201)
    def create_case(body: CaseCreate, actor: Actor, idempotency_key: Annotated[str, Header()]):
        service.timezone(body.timezone)
        payload = body.model_dump(mode="json")
        with store.transaction() as db:
            previous = service.retry(db, actor, "case.create", idempotency_key, payload)
            if previous:
                return store.get(db, CaseRecord, previous)
            store.get(db, Inspection, body.inspection_id, body.inspection_id)
            if store.execute(
                db, f"SELECT case_id FROM {service.members} WHERE inspection_id=?", (body.inspection_id,)
            ).fetchone():
                raise HTTPException(409, "Inspection already belongs to a case")
            item = CaseRecord(**body.model_dump(exclude={"reason"}))
            service.save(db, item, actor, body.reason, "v2.case.created")
            service.enrol(db, item, body.inspection_id, actor, body.reason)
            service.receipt(db, actor, "case.create", idempotency_key, payload, item.id)
            return item

    @router.get("/cases", response_model=list[CaseRecord])
    def list_cases():
        with store.transaction(write=False) as db:
            return store.list(db, CaseRecord)

    @router.get("/cases/{case_id}", response_model=CaseRecord)
    def get_case(case_id: str):
        with store.transaction(write=False) as db:
            return service.get_case(db, case_id)

    @router.post("/cases/{case_id}/inspections", response_model=Membership, status_code=201)
    def enrol(case_id: str, body: EnrolInspection, actor: Actor):
        with store.transaction() as db:
            case = service.get_case(db, case_id)
            return service.enrol(db, case, body.inspection_id, actor, body.reason)

    @router.get("/cases/{case_id}/inspections", response_model=list[Inspection])
    def case_visits(case_id: str):
        with store.transaction(write=False) as db:
            return [store.get(db, Inspection, m.inspection_id) for m in service.list(db, Membership, case_id)]

    @router.post("/cases/{case_id}/physical-assets", status_code=201)
    def create_physical(case_id: str, body: PhysicalAssetCreate, actor: Actor):
        with store.transaction() as db:
            physical, binding = service.confirm_identity(db, case_id, body, actor)
            return {"physical_asset": physical, "binding": binding}

    @router.get("/cases/{case_id}/physical-assets", response_model=list[PhysicalAsset])
    def physical_list(case_id: str):
        with store.transaction(write=False) as db:
            return service.list(db, PhysicalAsset, case_id)

    @router.post("/cases/{case_id}/asset-bindings", response_model=AssetBinding, status_code=201)
    def bind(case_id: str, body: BindAsset, actor: Actor):
        with store.transaction() as db:
            physical = service.physical(db, case_id, body.physical_asset_id)
            _, binding = service.confirm_identity(db, case_id, body, actor, physical)
            return binding

    @router.post("/cases/{case_id}/asset-bindings/{binding_id}/retract", response_model=AssetBinding)
    def retract_binding(case_id: str, binding_id: str, body: Revision, actor: Actor):
        with store.transaction() as db:
            binding = service.get(db, AssetBinding, binding_id, case_id)
            check_version(binding, body.version)
            if not binding.active:
                raise HTTPException(409, "Association is already retracted")
            binding.active = False
            service.save(db, binding, actor, body.reason, "v2.asset_identity.retracted")
            store.execute(db, f"UPDATE {service.bindings} SET active=0 WHERE binding_id=?", (binding.id,))
            return binding

    @router.get("/cases/{case_id}/identity-suggestions")
    def suggestions(case_id: str, inspection_id: str, asset_id: str):
        with store.transaction(write=False) as db:
            service.require_visit(db, case_id, inspection_id)
            asset = store.get(db, Asset, asset_id, inspection_id)
            return {
                "requires_confirmation": True,
                "candidates": [
                    p
                    for p in service.list(db, PhysicalAsset, case_id)
                    if engine.norm(p.serial) == engine.norm(asset.serial)
                    or engine.norm(p.model) == engine.norm(asset.model)
                ],
            }

    @router.post("/cases/{case_id}/investments", response_model=InvestmentProject, status_code=201)
    def create_project(
        case_id: str, body: ProjectCreate, actor: Actor, idempotency_key: Annotated[str, Header()]
    ):
        payload = body.model_dump(mode="json")
        with store.transaction() as db:
            service.get_case(db, case_id)
            operation = "project.create:" + case_id
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, InvestmentProject, previous, case_id)
            service.project_refs(db, case_id, body)
            item = InvestmentProject(case_id=case_id, **body.model_dump(exclude={"reason"}))
            service.save(db, item, actor, body.reason, "v2.investment.created")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.get("/cases/{case_id}/investments", response_model=list[InvestmentProject])
    def project_list(case_id: str):
        with store.transaction(write=False) as db:
            return service.list(db, InvestmentProject, case_id)

    @router.get("/cases/{case_id}/investments/{project_id}")
    def project_detail(case_id: str, project_id: str):
        with store.transaction(write=False) as db:
            item = service.get(db, InvestmentProject, project_id, case_id)
            return {
                "project": item,
                "targets": [
                    t for t in service.list(db, InvestmentTarget, case_id) if t.project_id == item.id
                ],
                "reviews": [
                    r for r in service.list(db, InvestmentReview, case_id) if r.project_id == item.id
                ],
                "outcome_default": "not_yet_measurable",
            }

    @router.patch("/cases/{case_id}/investments/{project_id}", response_model=InvestmentProject)
    def project_edit(case_id: str, project_id: str, body: ProjectUpdate, actor: Actor):
        with store.transaction() as db:
            item = service.get(db, InvestmentProject, project_id, case_id)
            check_version(item, body.version)
            service.project_refs(db, case_id, body)
            for field, value in body.model_dump(exclude={"reason", "version", "inspection_id"}).items():
                setattr(item, field, value)
            return service.save(db, item, actor, body.reason, "v2.investment.edited")

    @router.post(
        "/cases/{case_id}/investments/{project_id}/targets", response_model=InvestmentTarget, status_code=201
    )
    def target_create(
        case_id: str,
        project_id: str,
        body: TargetCreate,
        actor: Actor,
        idempotency_key: Annotated[str, Header()],
    ):
        payload = body.model_dump(mode="json")
        with store.transaction() as db:
            service.get(db, InvestmentProject, project_id, case_id)
            operation = "target.create:" + project_id
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, InvestmentTarget, previous, case_id)
            service.require_visit(db, case_id, body.inspection_id)
            service.validate_source(db, body.source, case_id)
            item = InvestmentTarget(
                case_id=case_id, project_id=project_id, **body.model_dump(exclude={"reason"})
            )
            service.save(db, item, actor, body.reason, "v2.target.created")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.patch("/cases/{case_id}/targets/{target_id}", response_model=InvestmentTarget)
    def target_edit(case_id: str, target_id: str, body: TargetUpdate, actor: Actor):
        with store.transaction() as db:
            item = service.get(db, InvestmentTarget, target_id, case_id)
            check_version(item, body.version)
            service.require_visit(db, case_id, body.inspection_id)
            service.validate_source(db, body.source, case_id)
            for field, value in body.model_dump(exclude={"reason", "version", "inspection_id"}).items():
                setattr(item, field, value)
            return service.save(db, item, actor, body.reason, "v2.target.revised")

    @router.post(
        "/cases/{case_id}/investments/{project_id}/reviews", response_model=InvestmentReview, status_code=201
    )
    def append_review(case_id: str, project_id: str, body: InvestmentReviewCreate, actor: Actor):
        with store.transaction() as db:
            project = service.get(db, InvestmentProject, project_id, case_id)
            service.require_visit(db, case_id, body.inspection_id)
            target = None
            if body.target_id:
                target = service.get(db, InvestmentTarget, body.target_id, case_id)
                if target.project_id != project.id:
                    raise HTTPException(422, "Target belongs to another investment")
            for evidence_id in body.evidence_ids:
                service.evidence(db, evidence_id, case_id, accepted=body.status == "supported")
            if body.status == "supported" and not body.evidence_ids:
                raise HTTPException(422, "Supported reviews require accepted source evidence")
            if target and body.status == "supported":
                kinds = {
                    "downtime_hours": {"operating_log", "maintenance_record"},
                    "repair_cost": {"maintenance_record", "invoice", "payment_extract"},
                    "output_rate": {"production_record"},
                    "defect_rate": {"production_record"},
                    "energy_consumption": {"utility_record", "operating_log"},
                }[target.metric]
                if (
                    body.measured_value is None
                    or body.baseline_value is None
                    or not body.baseline_source
                    or not body.measurement_source
                ):
                    raise HTTPException(
                        422,
                        "Supported outcome requires baseline/measurement values and exact source citations",
                    )
                for citation, value in (
                    (body.baseline_source, body.baseline_value),
                    (body.measurement_source, body.measured_value),
                ):
                    if citation.evidence_id not in body.evidence_ids:
                        raise HTTPException(422, "Measurement citations must refer to this review's evidence")
                    evidence = service.evidence(db, citation.evidence_id, case_id, accepted=True)
                    if evidence.kind not in kinds or citation.quote not in evidence.text:
                        raise HTTPException(
                            422, "Measurement needs a relevant accepted record and a resolvable quoted source"
                        )
                    import re

                    values = [
                        Decimal(match.replace(",", ""))
                        for match in re.findall(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?", citation.quote)
                    ]
                    if Decimal(value) not in values:
                        raise HTTPException(
                            422,
                            "Measurement value must be present in its quoted record; clarify ambiguous numbers",
                        )
            if body.physical_asset_id:
                binding = service.binding(db, case_id, body.physical_asset_id, body.inspection_id)
                if body.physical_asset_id not in [link.physical_asset_id for link in project.asset_links]:
                    raise HTTPException(422, "Machine is not linked to this investment")
            if body.status == "supported" and body.kind != "outcome":
                if not body.physical_asset_id:
                    raise HTTPException(422, "Deployment verification requires a linked physical asset")
                claim_kind = "presence" if body.kind == "delivery" else body.kind
                claim_ids = {
                    c.id
                    for c in store.list(db, Claim, body.inspection_id)
                    if c.asset_id == binding.local_asset_id and c.kind == claim_kind
                }
                if not any(
                    f.claim_id in claim_ids
                    and f.computed_status == "supported"
                    and f.reviewed_status == "supported"
                    and set(f.evidence_ids).intersection(body.evidence_ids)
                    for f in engine.current_findings(store, db, body.inspection_id)
                ):
                    raise HTTPException(
                        409, "Deployment milestone requires a currently supported, reviewed V1 finding"
                    )
            calculation = calculate_outcome(target, body) if target else {}
            item = InvestmentReview(
                case_id=case_id,
                project_id=project_id,
                target_version=target.version if target else None,
                reviewed_by=actor,
                calculation=calculation,
                **body.model_dump(exclude={"reason"}),
            )
            return service.save(db, item, actor, body.reason, "v2.investment.review_appended")

    @router.post("/cases/{case_id}/follow-ups", status_code=201)
    def closure_create(
        case_id: str, body: ClosureCreate, actor: Actor, idempotency_key: Annotated[str, Header()]
    ):
        payload = body.model_dump(mode="json")
        with store.transaction() as db:
            service.get_case(db, case_id)
            operation = "closure.create:" + case_id
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return {
                    "task": store.get(db, FollowUpAction, previous),
                    "details": service.follow_context(db, case_id, previous),
                }
            task, context = service.create_follow_up(db, case_id, body, actor)
            service.receipt(db, actor, operation, idempotency_key, payload, task.id)
            return {"task": task, "details": context}

    @router.get("/cases/{case_id}/follow-ups")
    def closure_list(case_id: str):
        with store.transaction(write=False) as db:
            return service.due(db, case_id) + [
                {
                    "task": store.get(db, FollowUpAction, c.follow_up_id),
                    "details": c,
                    "overdue": False,
                    "due_today": False,
                }
                for c in service.list(db, FollowUpContext, case_id)
                if c.workflow_status == "closed"
            ]

    @router.post("/cases/{case_id}/follow-ups/{follow_up_id}/transition")
    def closure_transition(case_id: str, follow_up_id: str, body: ClosureTransition, actor: Actor):
        with store.transaction() as db:
            task, context = service.transition(db, case_id, follow_up_id, body, actor)
            return {"task": task, "details": context}

    @router.patch("/cases/{case_id}/follow-ups/{follow_up_id}")
    def closure_edit(case_id: str, follow_up_id: str, body: ClosureEdit, actor: Actor):
        with store.transaction() as db:
            context = service.follow_context(db, case_id, follow_up_id)
            if context is None:
                raise HTTPException(404, "Enhanced follow-up not found")
            check_version(context, body.version)
            if context.workflow_status == "closed":
                raise HTTPException(409, "Reopen the follow-up before changing its requirements")
            if body.inspection_id != context.inspection_id:
                raise HTTPException(
                    422, "Keep the original finding's inspection; use review_inspection_id for a later visit"
                )
            binding = service.binding(db, case_id, body.physical_asset_id, body.inspection_id)
            service.validate_source(db, body.source, case_id)
            if body.reviewer not in service.analysts:
                raise HTTPException(422, "Choose a configured analyst reviewer")
            if body.project_id:
                service.get(db, InvestmentProject, body.project_id, case_id)
            if (
                body.claim_id
                and store.get(db, Claim, body.claim_id, body.inspection_id).asset_id != binding.local_asset_id
            ):
                raise HTTPException(422, "Claim belongs to another physical machine")
            task = store.get(db, FollowUpAction, follow_up_id, context.inspection_id)
            task.claim_id, task.request, task.state = body.claim_id, body.request, "open"
            for key, value in body.model_dump(
                exclude={"reason", "version", "claim_id", "request", "inspection_id"}
            ).items():
                setattr(context, key, value)
            context.workflow_status = "open"
            context.submitted_evidence_ids, context.verified_evidence_ids = [], []
            context.verified_by = context.verification_reason = context.review_inspection_id = None
            store.save(db, task, actor, body.reason, "follow_up.updated")
            service.save(db, context, actor, body.reason, "v2.follow_up.requirements_edited")
            return {"task": task, "details": context}

    @router.get("/cases/{case_id}/activity")
    def case_activity(case_id: str, request: Request, entity_id: str | None = None):
        if request.state.principal["role"] != "analyst":
            raise HTTPException(403, "Detailed V2 audit history is restricted to analysts")
        with store.transaction(write=False) as db:
            events = [
                event
                for m in service.list(db, Membership, case_id)
                for event in store.events(db, m.inspection_id, include_v2=True)
                if event.action.startswith("v2.") or (entity_id and event.entity_id == entity_id)
            ]
            if entity_id:
                events = [event for event in events if event.entity_id == entity_id]
            return sorted(events, key=lambda event: event.time)

    from app.v2_capture import install_capture
    from app.v2_copilot import install_copilot
    from app.v2_reminders import install_reminders
    from app.v2_reporting import install_reporting

    install_capture(router, app, service, authenticate)
    install_copilot(router, app, service, authenticate)
    install_reporting(router, app, service, authenticate, get_report)
    install_reminders(router, app, service, authenticate)
    app.include_router(router)
    return service
