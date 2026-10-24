"""Stored-source consulting and human confirmation; never adjudicates V1 claims."""

from decimal import Decimal
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from pydantic import ValidationError

from app import engine
from app.models import Claim
from app.v2_capture import check_segment_access
from app.v2_models import (
    AnalysisRequest,
    CandidateConfirmation,
    CandidateEdit,
    CopilotAnalysis,
    ExtractedCandidate,
    FollowUpContext,
    InterviewSession,
    InvestmentProject,
    InvestmentTarget,
    QuestionUpdate,
    Source,
    StatementRecord,
    TargetCreate,
    TranscriptSegment,
)
from app.v2_providers import rule_questions
from app.v2_store import check_version, fingerprint


def get_context(service, db, segment):
    store = service.store
    interview = service.get(db, InterviewSession, segment.interview_id, segment.case_id)
    binding = service.binding(db, segment.case_id, interview.physical_asset_id, segment.inspection_id)
    claims = {
        c.id: c for c in store.list(db, Claim, segment.inspection_id) if c.asset_id == binding.local_asset_id
    }
    findings = engine.current_findings(store, db, segment.inspection_id)
    projects = [
        p
        for p in service.list(db, InvestmentProject, segment.case_id)
        if any(a.physical_asset_id == interview.physical_asset_id for a in p.asset_links)
    ]
    project_ids = {p.id for p in projects}
    targets = [t for t in service.list(db, InvestmentTarget, segment.case_id) if t.project_id in project_ids]
    tasks = [
        t
        for t in service.list(db, FollowUpContext, segment.case_id)
        if t.physical_asset_id == interview.physical_asset_id and t.workflow_status != "closed"
    ]
    context = {
        "asset": {
            "physical_asset_id": interview.physical_asset_id,
            "local_asset_id": binding.local_asset_id,
            "binding_id": binding.id,
            "binding_version": binding.version,
        },
        "unresolved_claims": [
            {
                "claim_id": f.claim_id,
                "kind": claims[f.claim_id].kind,
                "status": f.computed_status,
                "next_action": f.next_best_action,
                "basis_hash": f.basis_hash,
            }
            for f in findings
            if f.claim_id in claims and f.computed_status != "supported"
        ],
        "projects": [
            {
                "id": p.id,
                "version": p.version,
                "title": p.title,
                "rationale": p.rationale,
                "proposed_amount": str(p.proposed_amount) if p.proposed_amount is not None else None,
                "currency": p.currency,
                "stage": p.stage,
            }
            for p in projects
        ][-10:],
        "targets": [
            {
                "id": t.id,
                "version": t.version,
                "metric": t.metric,
                "target_value": str(t.target_value),
                "baseline_value": str(t.baseline_value) if t.baseline_value is not None else None,
                "unit": t.unit,
            }
            for t in targets
        ][-20:],
        "open_follow_ups": [
            {
                "id": t.follow_up_id,
                "version": t.version,
                "required_evidence": t.required_evidence,
                "due_date": t.due_date,
                "status": t.workflow_status,
            }
            for t in tasks
        ][-20:],
        "authority": "Management statements and forecasts are context only. V1 rules control core support.",
    }
    if not findings:
        context["finding_notice"] = "Reconciliation is missing or stale; do not assume prior support"
    return interview, context


def source_for(interview, segment, quote):
    return Source(
        kind="interview",
        attribution=interview.speaker_label
        + (" (analyst-confirmed)" if interview.speaker_confirmed else " (unconfirmed speaker)"),
        quote=quote,
        segment_id=segment.id,
        segment_version=segment.version,
        origin_group=segment.case_id + ":management_interview",
    )


def install_copilot(router, app, service, authenticate):
    store = service.store
    Actor = Annotated[str, Depends(authenticate)]

    @router.post(
        "/cases/{case_id}/segments/{segment_id}/analyse", response_model=CopilotAnalysis, status_code=201
    )
    def analyse(
        case_id: str,
        segment_id: str,
        body: AnalysisRequest,
        actor: Actor,
        idempotency_key: Annotated[str, Header()],
    ):
        operation = "copilot.analyse:" + segment_id
        with store.transaction(write=False) as db:
            segment = service.get(db, TranscriptSegment, segment_id, case_id)
            interview, context = get_context(service, db, segment)
            context_hash = fingerprint(context)
            payload = {
                "request": body.model_dump(mode="json"),
                "segment_version": segment.version,
                "context_hash": context_hash,
            }
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, CopilotAnalysis, previous, case_id)
            prior = service.list(db, CopilotAnalysis, case_id)
            asked = {
                q.topic
                for a in prior
                if a.context_hash == context_hash
                for q in a.questions
                if q.status in {"asked", "dismissed"}
            }
        text = segment.text + (
            "\nEnglish translation: " + segment.english_translation if segment.english_translation else ""
        )
        notices = []
        provider, model = app.state.ai.name, app.state.ai.model
        try:
            output = app.state.ai.analyse(
                text, {**context, "already_asked_or_dismissed_topics": sorted(asked)}
            )
        except HTTPException:
            if not body.allow_rule_fallback:
                raise
            output = rule_questions(text, context)
            provider, model = "context_rules", "rules-v2.1"
            notices.append(
                "AI unavailable: explicit rules-only fallback; no AI candidate extraction was performed"
            )
        questions = []
        topics = set(asked)
        for question in output.questions:
            if question.topic not in topics:
                topics.add(question.topic)
                questions.append(question)
        with store.transaction() as db:
            fresh = service.get(db, TranscriptSegment, segment_id, case_id)
            check_version(fresh, segment.version)
            current_interview, current_context = get_context(service, db, fresh)
            if current_interview.version != interview.version or fingerprint(current_context) != context_hash:
                raise HTTPException(409, "Inspection context changed during analysis; refresh and retry")
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, CopilotAnalysis, previous, case_id)
            existing = service.list(db, ExtractedCandidate, case_id)
            candidate_ids = []
            for proposed in output.candidates:
                matching = next(
                    (
                        c
                        for c in existing
                        if c.segment_id == segment.id
                        and c.segment_version == segment.version
                        and c.payload.model_dump() == proposed.model_dump()
                        and c.review_status != "stale"
                    ),
                    None,
                )
                if matching:
                    candidate_ids.append(matching.id)
                    continue
                candidate = ExtractedCandidate(
                    case_id=case_id,
                    inspection_id=segment.inspection_id,
                    segment_id=segment.id,
                    segment_version=segment.version,
                    physical_asset_id=interview.physical_asset_id,
                    project_id=interview.project_id,
                    payload=proposed,
                )
                service.save(db, candidate, actor, body.reason, "v2.candidate.proposed")
                candidate_ids.append(candidate.id)
            item = CopilotAnalysis(
                case_id=case_id,
                inspection_id=segment.inspection_id,
                segment_id=segment.id,
                segment_version=segment.version,
                context_hash=context_hash,
                provider=provider,
                model=model,
                questions=questions[:3],
                candidate_ids=candidate_ids,
                notices=notices,
            )
            service.save(db, item, actor, body.reason, "v2.copilot.analysis_saved")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.get("/cases/{case_id}/candidates", response_model=list[ExtractedCandidate])
    def candidates(case_id: str, request: Request):
        if request.state.principal["role"] != "analyst":
            raise HTTPException(403, "Draft extraction review is restricted to analysts")
        with store.transaction(write=False) as db:
            return service.list(db, ExtractedCandidate, case_id)

    @router.patch("/cases/{case_id}/candidates/{candidate_id}", response_model=ExtractedCandidate)
    def edit_candidate(case_id: str, candidate_id: str, body: CandidateEdit, actor: Actor):
        with store.transaction() as db:
            item = service.get(db, ExtractedCandidate, candidate_id, case_id)
            check_version(item, body.version)
            if item.review_status != "pending":
                raise HTTPException(409, "Only pending candidates can be edited")
            segment = service.get(db, TranscriptSegment, item.segment_id, case_id)
            check_version(segment, item.segment_version)
            if body.payload.quote not in segment.text + "\n" + (segment.english_translation or ""):
                raise HTTPException(422, "Candidate quote must resolve to its stored source")
            item.payload = body.payload
            return service.save(db, item, actor, body.reason, "v2.candidate.analyst_edited")

    @router.post("/cases/{case_id}/candidates/{candidate_id}/confirm", response_model=ExtractedCandidate)
    def confirm(case_id: str, candidate_id: str, body: CandidateConfirmation, actor: Actor):
        with store.transaction() as db:
            item = service.get(db, ExtractedCandidate, candidate_id, case_id)
            proposed = body.edited or item.payload
            if item.review_status == "accepted":
                if (
                    body.action == "accept"
                    and item.accepted_payload == proposed
                    and (not body.project_id or body.project_id == item.project_id)
                ):
                    return item
                raise HTTPException(409, "Candidate was already accepted with a different decision")
            check_version(item, body.version)
            if item.review_status != "pending":
                raise HTTPException(409, "Candidate is no longer pending; review the current source")
            segment = service.get(db, TranscriptSegment, item.segment_id, case_id)
            check_version(segment, item.segment_version)
            interview = service.get(db, InterviewSession, segment.interview_id, case_id)
            service.binding(db, case_id, item.physical_asset_id, item.inspection_id)
            if proposed.quote not in segment.text + "\n" + (segment.english_translation or ""):
                raise HTTPException(422, "Candidate quote is not present in the current source")
            if body.action == "reject":
                item.review_status = "rejected"
                return service.save(db, item, actor, body.reason, "v2.candidate.rejected")
            if not body.confirmed_source:
                raise HTTPException(
                    422, "Review the original/translation and explicitly confirm the source interpretation"
                )
            project_id = body.project_id or item.project_id
            project = service.get(db, InvestmentProject, project_id, case_id) if project_id else None
            if project and item.physical_asset_id not in [a.physical_asset_id for a in project.asset_links]:
                raise HTTPException(422, "Investment is not linked to this physical machine")
            source = source_for(interview, segment, proposed.quote)
            if proposed.kind == "investment_target":
                if (
                    project is None
                    or proposed.metric is None
                    or proposed.value is None
                    or not proposed.unit
                    or not proposed.target_type
                ):
                    raise HTTPException(
                        422, "Choose a linked investment and complete the metric, value, unit and target type"
                    )
                try:
                    target_input = TargetCreate(
                        inspection_id=item.inspection_id,
                        metric=proposed.metric,
                        unit=proposed.unit,
                        target_type=proposed.target_type,
                        target_value=proposed.value,
                        currency=proposed.currency,
                        due_date=proposed.due_date,
                        source=source,
                        reason=body.reason,
                    )
                except ValidationError as exc:
                    raise HTTPException(
                        422, "Edited target has invalid units, percentage, date or currency"
                    ) from exc
                existing_targets = [
                    t
                    for t in service.list(db, InvestmentTarget, case_id)
                    if t.project_id == project_id
                    and t.metric == proposed.metric
                    and t.source.segment_id == segment.id
                    and t.target_value == proposed.value
                    and t.target_type == proposed.target_type
                ]
                if existing_targets:
                    raise HTTPException(
                        409, "This source already produced the same target; review the existing record"
                    )
                destination = InvestmentTarget(
                    case_id=case_id, project_id=project_id, **target_input.model_dump(exclude={"reason"})
                )
                service.save(db, destination, actor, body.reason, "v2.target.confirmed_from_interview")
            elif proposed.kind == "follow_up":
                if body.follow_up is None:
                    raise HTTPException(
                        422, "Complete the follow-up owner, reviewer, due date and evidence requirement"
                    )
                task_input = body.follow_up
                if (
                    task_input.physical_asset_id != item.physical_asset_id
                    or task_input.inspection_id != item.inspection_id
                ):
                    raise HTTPException(422, "Follow-up must retain its source machine and visit")
                task_input.source = source
                destination, _ = service.create_follow_up(db, case_id, task_input, actor)
            else:
                if proposed.kind == "proposed_amount":
                    if project is None or proposed.value is None or not proposed.currency:
                        raise HTTPException(
                            422, "A proposed amount requires a linked project, amount and currency"
                        )
                    if body.project_version is None:
                        raise HTTPException(
                            422,
                            "Review and submit the current project version before changing its proposed amount",
                        )
                    check_version(project, body.project_version)
                    if (
                        proposed.value > Decimal("9999999999999999.99")
                        or proposed.value.as_tuple().exponent < -2
                    ):
                        raise HTTPException(422, "Amount exceeds supported precision")
                    project.proposed_amount, project.currency, project.amount_source = (
                        proposed.value,
                        proposed.currency,
                        source,
                    )
                    service.save(db, project, actor, body.reason, "v2.investment.proposed_amount_confirmed")
                destination = StatementRecord(
                    case_id=case_id,
                    inspection_id=item.inspection_id,
                    physical_asset_id=item.physical_asset_id,
                    project_id=project_id,
                    text=proposed.text,
                    source=source,
                    kind=proposed.kind,
                    value=proposed.value,
                    currency=proposed.currency,
                )
                service.save(db, destination, actor, body.reason, "v2.statement.confirmed_as_reported")
            item.review_status, item.destination_id, item.project_id = "accepted", destination.id, project_id
            item.accepted_payload = proposed
            return service.save(db, item, actor, body.reason, "v2.candidate.accepted")

    @router.patch("/cases/{case_id}/analyses/{analysis_id}/question", response_model=CopilotAnalysis)
    def mark_question(case_id: str, analysis_id: str, body: QuestionUpdate, actor: Actor):
        with store.transaction() as db:
            item = service.get(db, CopilotAnalysis, analysis_id, case_id)
            check_version(item, body.version)
            if body.index >= len(item.questions):
                raise HTTPException(422, "Question index is outside this analysis")
            item.questions[body.index].status = body.status
            return service.save(db, item, actor, body.reason, "v2.question.marked")

    @router.get("/cases/{case_id}/analyses")
    def analyses(case_id: str, request: Request, segment_id: str | None = None):
        with store.transaction(write=False) as db:
            items = service.list(db, CopilotAnalysis, case_id)
            results = []
            for item in items:
                if segment_id and item.segment_id != segment_id:
                    continue
                segment = service.get(db, TranscriptSegment, item.segment_id, case_id)
                try:
                    check_segment_access(service, db, request, segment)
                except HTTPException as exc:
                    if exc.status_code == 403:
                        continue
                    raise
                results.append({"analysis": item, "source_current": segment.version == item.segment_version})
            return results
