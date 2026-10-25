"""Authenticated inbox APIs; association, evidence acceptance and claim support are separate."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app import engine
from app.intake_models import IntakeDocumentReview, IntakeRecord, IntakeReview, IntakeUpload
from app.intake_service import KINDS, IntakeService
from app.intake_understanding import proposed_facts
from app.models import Asset, Claim, Evidence, EvidenceLink, now
from app.v2_models import Revision
from app.v2_store import check_version


def install_intake(app, store, service, authenticate, activate):
    intake = IntakeService(store, service, activate)
    app.state.intake = intake
    router = APIRouter(prefix="/api", dependencies=[Depends(authenticate)], tags=["Evidence intake"])
    Actor = Annotated[str, Depends(authenticate)]

    def visible(item, request):
        if item.media_type.startswith("video/") and not item.raw_result.get("duration_seconds"):
            return request.state.principal["role"] == "analyst"
        return not item.media_type.startswith("audio/") or request.state.principal["role"] == "analyst"

    def get(db, identifier, request):
        item = intake.get(db, identifier)
        if not visible(item, request):
            raise HTTPException(403, "Recording intake is restricted to analysts")
        if item.processing_status not in {"queued", "processing"}:
            from app.intake_understanding import resolve

            item.resolution = resolve(
                item.raw_result.get("fields", []), store.list(db, Asset, item.inspection_id), item.asset_hint
            )
        return item

    @router.post("/evidence/intake", response_model=IntakeRecord, status_code=201)
    def upload(
        actor: Actor,
        file: Annotated[UploadFile, File()],
        metadata: Annotated[str, Form(max_length=12000)],
        idempotency_key: Annotated[str, Header()],
    ):
        try:
            body = IntakeUpload.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid intake metadata") from exc
        return intake.upload(body, file, actor, idempotency_key)

    @router.get("/evidence/inbox")
    def inbox(
        request: Request,
        inspection_id: str,
        q: str = "",
        state: str | None = None,
        asset_id: str | None = None,
    ):
        from app.models import Inspection

        with store.transaction(write=False) as db:
            store.get(db, Inspection, inspection_id, inspection_id)
            rows = intake.records(db, iid=inspection_id)
            rows = [
                r
                for r in rows
                if visible(r, request)
                and (not state or r.processing_status == state)
                and (not asset_id or r.assigned_asset_id == asset_id)
                and q.casefold()
                in (
                    r.original_filename + " " + r.display_filename + " " + r.raw_result.get("text", "")
                ).casefold()
            ]
            return [
                r.model_dump(mode="json", exclude={"raw_result"})
                for r in sorted(rows, key=lambda r: r.created_at, reverse=True)[:100]
            ]

    @router.get("/evidence/{identifier}/processing-status")
    def status(identifier: str, request: Request):
        with store.transaction(write=False) as db:
            item = get(db, identifier, request)
            ev = store.get(db, Evidence, item.evidence_id, item.inspection_id) if item.evidence_id else None
            return {
                "intake": item,
                "evidence": ev,
                "proposed_facts": proposed_facts(item.raw_result.get("fields", [])),
                "acceptance_is_separate": True,
            }

    @router.get("/evidence/{identifier}/extraction")
    def extraction(identifier: str, request: Request):
        with store.transaction(write=False) as db:
            item = get(db, identifier, request)
            return {
                "evidence_id": item.evidence_id,
                "original_sha256": item.content_sha256,
                "pipeline_version": item.pipeline_version,
                "processing_status": item.processing_status,
                "result": item.raw_result,
            }

    @router.get("/evidence/{identifier}/asset-candidates")
    def candidates(identifier: str, request: Request):
        with store.transaction(write=False) as db:
            return get(db, identifier, request).resolution

    @router.get("/evidence/{identifier}/original")
    def original(identifier: str, request: Request):
        with store.transaction(write=False) as db:
            item = get(db, identifier, request)
            path = store.files / item.content_sha256
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item.content_sha256:
                raise HTTPException(409, "Original integrity check failed")
        return FileResponse(
            path,
            media_type=item.media_type,
            filename=item.original_filename,
            content_disposition_type="inline",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/evidence/{identifier}/frames/{number}")
    def frame(identifier: str, number: int, request: Request):
        with store.transaction(write=False) as db:
            item = get(db, identifier, request)
            pages = item.raw_result.get("pages", [])
            if not 1 <= number <= len(pages) or not pages[number - 1].get("frame"):
                raise HTTPException(404, "Frame not found")
            artifact = item.raw_result.get("artifact", {"record_id": item.id, "attempt": item.attempts})
            metadata = pages[number - 1]["frame"]
            path = intake.derived / artifact["record_id"] / str(artifact["attempt"]) / metadata["file"]
            if (
                not path.resolve().is_relative_to(intake.derived.resolve())
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]
            ):
                raise HTTPException(
                    409, "Derived frame unavailable or integrity changed; reprocess the original"
                )
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @router.post("/evidence/{identifier}/retry", response_model=IntakeRecord)
    def retry(identifier: str, body: Revision, actor: Actor, request: Request):
        with store.transaction() as db:
            item = get(db, identifier, request)
            check_version(item, body.version)
            if item.processing_status in {"queued", "processing"}:
                raise HTTPException(409, "Processing is already queued or running")
            item.processing_status, item.last_error = "queued", None
            return intake.save(db, item, actor, body.reason, "retry_queued")

    @router.post("/evidence/{identifier}/confirm-asset", response_model=IntakeRecord)
    def confirm(identifier: str, body: IntakeReview, actor: Actor, request: Request):
        with store.transaction() as db:
            item = get(db, identifier, request)
            check_version(item, body.version)
            if item.processing_status in {"queued", "processing"}:
                raise HTTPException(409, "Wait for processing before review")
            if body.action == "confirm":
                if not body.checked_original or not body.asset_id:
                    raise HTTPException(422, "Select a machine and explicitly review the original")
                store.get(db, Asset, body.asset_id, item.inspection_id)
                decision = item.resolution.get("decision")
                candidate = next(
                    (c for c in item.resolution.get("candidates", []) if c["asset_id"] == body.asset_id), None
                )
                if (
                    decision != "EXACT_SERIAL_CANDIDATE"
                    or not candidate
                    or candidate["conflicting_identifiers"]
                ) and not body.acknowledge_conflicts:
                    raise HTTPException(
                        422,
                        "Acknowledge and explain ambiguous/conflicting identifiers before overriding the association",
                    )
                item.assigned_asset_id, item.processing_status = body.asset_id, "linked"
            else:
                item.assigned_asset_id = None
                item.processing_status = "rejected" if body.action == "reject" else "needs_review"
            item.reviewed_by, item.reviewed_at, item.review_reason = actor, now(), body.reason
            return intake.save(db, item, actor, body.reason, "association_" + body.action)

    @router.post("/evidence/{identifier}/review-document")
    def review_document(identifier: str, body: IntakeDocumentReview, actor: Actor, request: Request):
        with store.transaction() as db:
            item = get(db, identifier, request)
            check_version(item, body.version)
            if not item.evidence_id or not body.checked_original or item.processing_status != "linked":
                raise HTTPException(422, "Review the original and confirm the asset association first")
            evidence = store.get(db, Evidence, item.evidence_id, item.inspection_id)
            check_version(evidence, body.evidence_version)
            if not engine.intact(store, evidence):
                raise HTTPException(409, "Original integrity check failed")
            evidence.kind = KINDS.get(body.category, "other")
            evidence.facts, evidence.confirmed = body.facts, True
            evidence.quality_flags = sorted(set(body.quality_flags + ["manual_correction"]))
            store.save(db, evidence, actor, body.reason, "evidence.analyst_correction")
            item.category = body.category
            intake.save(db, item, actor, body.reason, "document_reviewed")
            activate(db, item.inspection_id, actor, body.reason)
            return {"intake": item, "evidence": evidence, "claim_support_computed": False}

    @router.post("/evidence/{identifier}/attach-acoustic")
    def acoustic(identifier: str, body: Revision, actor: Actor, request: Request, physical_asset_id: str):
        with store.transaction() as db:
            item = get(db, identifier, request)
            check_version(item, body.version)
            if not item.media_type.startswith("audio/") or not item.case_id:
                raise HTTPException(422, "Select processed acoustic audio in a case")
            if item.audio_recording_id:
                raise HTTPException(409, "Audio already handed to the existing recording pipeline")
            audio = intake.acoustic_handoff(db, item, physical_asset_id, actor, body.reason)
            intake.save(db, item, actor, body.reason, "acoustic_handoff")
            return audio

    @router.get("/assets/{asset_id}/evidence")
    def asset_evidence(asset_id: str, request: Request):
        with store.transaction(write=False) as db:
            asset = store.get(db, Asset, asset_id)
            claim_ids = {c.id for c in store.list(db, Claim, asset.inspection_id) if c.asset_id == asset_id}
            evidence_ids = {
                l.evidence_id
                for l in store.list(db, EvidenceLink, asset.inspection_id)
                if l.active and l.claim_id in claim_ids
            }
            return {
                "asset": asset,
                "intake": [
                    r
                    for r in intake.records(db, iid=asset.inspection_id)
                    if visible(r, request) and r.assigned_asset_id == asset_id
                ],
                "claim_linked_evidence": [
                    e for e in store.list(db, Evidence, asset.inspection_id) if e.id in evidence_ids
                ],
            }

    app.include_router(router)
    return intake
