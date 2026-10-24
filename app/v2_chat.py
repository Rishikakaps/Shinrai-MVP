"""Read-only, persisted case consultation. A reply never changes evidence or findings."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app import engine
from app.models import Claim, Text
from app.v2_models import (
    Change,
    FollowUpContext,
    InterviewSession,
    InvestmentProject,
    InvestmentTarget,
    Scoped,
    TranscriptSegment,
)


class ChatRequest(Change):
    inspection_id: str
    physical_asset_id: str | None = None
    question: Text


class Consultation(Scoped):
    physical_asset_id: str | None = None
    question: str
    answer: str
    sources: list[dict]
    provider: str
    model: str


def context_for(service, db, case_id, body):
    service.require_visit(db, case_id, body.inspection_id)
    case = service.get_case(db, case_id)
    local = None
    if body.physical_asset_id:
        service.physical(db, case_id, body.physical_asset_id)
        local = service.binding(db, case_id, body.physical_asset_id, body.inspection_id).local_asset_id
    sources = []

    def add(obj, kind, text):
        sources.append({"id": obj.id, "kind": kind, "version": obj.version, "text": text})

    claims = {
        c.id: c for c in service.store.list(db, Claim, body.inspection_id) if not local or c.asset_id == local
    }
    for f in engine.current_findings(service.store, db, body.inspection_id):
        if f.claim_id in claims:
            add(
                f,
                "finding",
                {
                    "claim": claims[f.claim_id].kind,
                    "computed": f.computed_status,
                    "reviewed": f.reviewed_status,
                    "explanation": f.explanation,
                    "next_action": f.next_best_action,
                },
            )
    projects = [
        p
        for p in service.list(db, InvestmentProject, case_id)
        if not body.physical_asset_id
        or any(l.physical_asset_id == body.physical_asset_id for l in p.asset_links)
    ][-5:]
    for p in projects:
        add(
            p,
            "reported_investment",
            {
                "title": p.title,
                "rationale": p.rationale,
                "proposed_amount": str(p.proposed_amount) if p.proposed_amount is not None else None,
                "currency": p.currency,
                "stage": p.stage,
                "source": p.source.model_dump(mode="json"),
            },
        )
    for t in service.list(db, InvestmentTarget, case_id):
        if t.project_id in {p.id for p in projects}:
            add(
                t,
                "management_forecast",
                {
                    "metric": t.metric,
                    "value": str(t.target_value),
                    "unit": t.unit,
                    "baseline": str(t.baseline_value) if t.baseline_value is not None else None,
                },
            )
    for f in service.list(db, FollowUpContext, case_id)[-12:]:
        if not body.physical_asset_id or f.physical_asset_id == body.physical_asset_id:
            add(
                f,
                "follow_up",
                {
                    "required_evidence": f.required_evidence,
                    "status": f.workflow_status,
                    "due_date": f.due_date,
                },
            )
    sessions = {
        i.id
        for i in service.list(db, InterviewSession, case_id)
        if not body.physical_asset_id or i.physical_asset_id == body.physical_asset_id
    }
    for s in [s for s in service.list(db, TranscriptSegment, case_id) if s.interview_id in sessions][-6:]:
        add(s, "reported_transcript", {"original": s.text, "translation": s.english_translation})
    return {
        "company": case.company,
        "site": case.site,
        "sources": sources[:45],
        "notice": "These records are attributed reports and reviews, not independently authenticated facts.",
    }


def install_chat(router, app, service, authenticate):
    Actor = Annotated[str, Depends(authenticate)]

    @router.post("/cases/{case_id}/chat", response_model=Consultation, status_code=201)
    def consult(case_id: str, body: ChatRequest, actor: Actor, idempotency_key: Annotated[str, Header()]):
        payload = body.model_dump(mode="json")
        operation = "chat:" + case_id
        with service.store.transaction(write=False) as db:
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, Consultation, previous, case_id)
            context = context_for(service, db, case_id, body)
        result = app.state.ai.consult(body.question, context)
        by_id = {s["id"]: s for s in context["sources"]}
        if not set(result["source_ids"]).issubset(by_id):
            raise HTTPException(502, "Chat citations did not resolve to stored records; no reply was saved")
        with service.store.transaction() as db:
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, Consultation, previous, case_id)
            item = Consultation(
                case_id=case_id,
                inspection_id=body.inspection_id,
                physical_asset_id=body.physical_asset_id,
                question=body.question,
                answer=result["answer"],
                sources=[by_id[x] for x in dict.fromkeys(result["source_ids"])],
                provider=app.state.ai.name,
                model=app.state.ai.model,
            )
            service.save(db, item, actor, body.reason, "v2.consultation.saved")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.get("/cases/{case_id}/chat", response_model=list[Consultation])
    def history(case_id: str, request: Request):
        if request.state.principal["role"] != "analyst":
            raise HTTPException(403, "Case consultation is restricted to analysts")
        with service.store.transaction(write=False) as db:
            return service.list(db, Consultation, case_id)
