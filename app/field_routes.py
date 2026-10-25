"""Bounded live preview is ephemeral; deliberate captures are persisted and reviewed."""

import hashlib
import io
import time
from threading import Lock
from typing import Annotated

from fastapi import Depends, File, Form, Header, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from app.field_models import (
    CaptureInput,
    CaptureReview,
    DocumentaryInput,
    DocumentaryReview,
    FieldSession,
    FieldSessionCreate,
    SessionTransition,
    VisualCapture,
)
from app.identifiers import compare_scan, normalized
from app.label_scan import scan_file
from app.models import Asset, Evidence, FollowUpAction, now
from app.nameplates import associate_nameplate
from app.v2_media import persist_original
from app.v2_models import (
    AssetBinding,
    BindAsset,
    InvestmentProject,
    PhysicalAsset,
    PhysicalAssetCreate,
    Revision,
)
from app.v2_store import check_version


def require_session(service, db, case_id, sid, actor=None):
    item = service.get(db, FieldSession, sid, case_id)
    service.require_visit(db, case_id, item.inspection_id)
    if actor and item.owner != actor:
        raise HTTPException(403, "This device session belongs to another analyst")
    if actor and item.state == "CLOSED":
        raise HTTPException(409, "SESSION_CLOSED: start a new field session")
    return item


def process_capture(service, case_id, capture_id, actor, reason):
    store = service.store
    with store.transaction(write=False) as db:
        item = service.get(db, VisualCapture, capture_id, case_id)
        session = service.get(db, FieldSession, item.session_id, case_id)
        ev = service.evidence(db, item.evidence_id, case_id)
        asset = (
            store.get(db, Asset, item.intended_asset_id, item.inspection_id)
            if item.intended_asset_id
            else None
        )
    try:
        raw = scan_file(store.files / ev.sha256)
        expected = {k: getattr(asset, k, None) for k in ("serial", "model", "site")}
        expected["manufacturer"] = session.expected_manufacturer
        result = compare_scan(raw, expected)
        with store.transaction() as db:
            current = service.get(db, VisualCapture, capture_id, case_id)
            check_version(current, item.version)
            raw["registry_association"] = associate_nameplate(
                store,
                db,
                item.inspection_id,
                item.evidence_id,
                raw,
                item.intended_asset_id,
                actor,
                reason,
            )
            current.raw_result, current.comparison = raw, result
            current.working_fields = current.working_fields.model_validate(result["observed_fields"])
            current.state = (
                "NEEDS_REVIEW"
                if result["decision"] in {"MATCH_CANDIDATE", "NEEDS_REVIEW"}
                or raw["registry_association"]["state"] == "CONTEXT_LINKED"
                else "NEEDS_RESCAN"
            )
            current.error = None
            return service.save(db, current, actor, reason, "v2.field.capture_processed")
    except HTTPException as exc:
        if exc.status_code == 409:
            raise
        with store.transaction() as db:
            current = service.get(db, VisualCapture, capture_id, case_id)
            if current.state in {"ACCEPTED", "REJECTED"}:
                return current
            current.state, current.error = "PROCESSING_FAILED", str(exc.detail)[:4000]
            return service.save(db, current, actor, reason, "v2.field.processing_failed")


def install_field(router, app, service, authenticate):
    store = service.store
    Actor = Annotated[str, Depends(authenticate)]
    # Preview bytes never enter storage, audit or the V1 reconciliation basis.
    live, live_lock = {}, Lock()
    app.state.field_live = live

    @router.post("/cases/{case_id}/field-sessions", response_model=FieldSession, status_code=201)
    def start(
        case_id: str, body: FieldSessionCreate, actor: Actor, idempotency_key: Annotated[str, Header()]
    ):
        payload, operation = body.model_dump(mode="json"), "field.start:" + case_id
        with store.transaction() as db:
            service.require_visit(db, case_id, body.inspection_id)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, FieldSession, previous, case_id)
            if body.intended_asset_id:
                store.get(db, Asset, body.intended_asset_id, body.inspection_id)
            if body.physical_asset_id:
                binding = service.binding(db, case_id, body.physical_asset_id, body.inspection_id)
                if body.intended_asset_id and binding.local_asset_id != body.intended_asset_id:
                    raise HTTPException(422, "Intended and confirmed machines differ")
            if body.purpose == "machine_acoustic" and not body.physical_asset_id:
                raise HTTPException(422, "Confirm physical identity before machine acoustic recording")
            if body.project_id:
                service.get(db, InvestmentProject, body.project_id, case_id)
            if body.task_id:
                store.get(db, FollowUpAction, body.task_id, body.inspection_id)
            item = FieldSession(case_id=case_id, owner=actor, **body.model_dump(exclude={"reason"}))
            service.save(db, item, actor, body.reason, "v2.field.session_created")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.get("/cases/{case_id}/field-sessions")
    def sessions(case_id: str):
        with store.transaction(write=False) as db:
            return service.list(db, FieldSession, case_id)

    @router.get("/cases/{case_id}/field-sessions/{sid}")
    def status(case_id: str, sid: str):
        with store.transaction(write=False) as db:
            item = require_session(service, db, case_id, sid)
        with live_lock:
            receipt = live.get(sid, {}).copy()
        age = time.monotonic() - receipt.get("clock", 0)
        return {
            "session": item,
            "transport": {
                "state": "CLOSED" if item.state == "CLOSED" else "CONNECTED" if age < 8 else "INTERRUPTED",
                "received_samples": receipt.get("count", 0),
                "last_sequence": receipt.get("sequence", -1),
                "last_received_at": receipt.get("received_at"),
                "preview_persisted": False,
            },
            "captures": [c for c in captures(case_id) if c.session_id == sid],
        }

    @router.patch("/cases/{case_id}/field-sessions/{sid}", response_model=FieldSession)
    def transition(case_id: str, sid: str, body: SessionTransition, actor: Actor):
        with store.transaction() as db:
            item = require_session(service, db, case_id, sid, actor)
            check_version(item, body.version)
            item.state = body.state
            service.save(db, item, actor, body.reason, "v2.field.connection_transition")
        if body.state != "CONNECTED":
            with live_lock:
                live.pop(sid, None)
        return item

    @router.post("/cases/{case_id}/field-sessions/{sid}/preview")
    async def preview(case_id: str, sid: str, request: Request, actor: Actor, sequence: int):
        if not 0 <= sequence <= 2147483647:
            raise HTTPException(422, "Invalid preview sequence")
        with store.transaction(write=False) as db:
            item = require_session(service, db, case_id, sid, actor)
            if item.purpose != "identifier":
                raise HTTPException(422, "This session is not a visual capture session")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 256 * 1024:
                raise HTTPException(413, "Preview limit is 256 KiB; evidence capture uses a separate route")
        digest = hashlib.sha256(data).hexdigest()
        try:
            with Image.open(io.BytesIO(data)) as image:
                if (
                    image.format not in {"JPEG", "PNG"}
                    or max(image.size) > 640
                    or image.width * image.height > 307200
                ):
                    raise ValueError()
                image.verify()
        except (ValueError, OSError, UnidentifiedImageError) as exc:
            raise HTTPException(
                422, "Use a valid bounded JPEG/PNG preview, at most 640 pixels on its long edge"
            ) from exc
        with live_lock:
            previous = live.get(sid)
            if previous and sequence <= previous["sequence"]:
                if sequence == previous["sequence"] and digest == previous["digest"]:
                    return {"sequence": sequence, "received_at": previous["received_at"], "duplicate": True}
                raise HTTPException(409, "PREVIEW_SEQUENCE_CONFLICT: reconnect using the latest sequence")
            if previous and time.monotonic() - previous["clock"] < 0.25:
                raise HTTPException(
                    429, "Preview backpressure; retry after one second", headers={"Retry-After": "1"}
                )
            if len(live) >= 1024:
                expired = [key for key, value in live.items() if time.monotonic() - value["clock"] > 60]
                for key in expired:
                    live.pop(key, None)
                if len(live) >= 1024:
                    raise HTTPException(429, "Too many active field sessions")
            receipt = {
                "sequence": sequence,
                "digest": digest,
                "count": (previous or {}).get("count", 0) + 1,
                "received_at": now(),
                "clock": time.monotonic(),
            }
            live[sid] = receipt
        return {
            "sequence": sequence,
            "received_at": receipt["received_at"],
            "received_samples": receipt["count"],
            "preview_persisted": False,
        }

    @router.post(
        "/cases/{case_id}/field-sessions/{sid}/captures", response_model=VisualCapture, status_code=201
    )
    def capture(
        case_id: str,
        sid: str,
        actor: Actor,
        file: Annotated[UploadFile, File()],
        metadata: Annotated[str, Form(max_length=8000)],
        idempotency_key: Annotated[str, Header()],
    ):
        from app.main import validate_file

        try:
            body = CaptureInput.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid capture metadata") from exc
        content = file.file.read(12 * 1024 * 1024 + 1)
        filename = (file.filename or "capture.jpg").replace("\\", "/").rsplit("/", 1)[-1][:200]
        media_type = file.content_type or ""
        payload = {
            "metadata": body.model_dump(mode="json"),
            "digest": hashlib.sha256(content).hexdigest(),
            "filename": filename,
            "media_type": media_type,
        }
        operation = "field.capture:" + sid
        with store.transaction(write=False) as db:
            session = require_session(service, db, case_id, sid, actor)
            if session.purpose != "identifier":
                raise HTTPException(422, "Use the appropriate audio/documentary pipeline")
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, VisualCapture, previous, case_id)
        if media_type not in {"image/jpeg", "image/png"}:
            raise HTTPException(415, "Capture a JPEG or PNG image")
        validate_file(content, filename, media_type)
        digest = persist_original(store.files, content)
        with store.transaction() as db:
            session = require_session(service, db, case_id, sid, actor)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, VisualCapture, previous, case_id)
            ev = Evidence(
                inspection_id=session.inspection_id,
                kind="site_image",
                filename=filename,
                media_type=media_type,
                sha256=digest,
                byte_size=len(content),
                source="Field session " + sid,
                captured_at=body.captured_at,
            )
            store.save(db, ev, actor, body.reason, "evidence.uploaded")
            asset = (
                store.get(db, Asset, session.intended_asset_id, session.inspection_id)
                if session.intended_asset_id
                else None
            )
            item = VisualCapture(
                inspection_id=session.inspection_id,
                case_id=case_id,
                session_id=sid,
                evidence_id=ev.id,
                evidence_version=ev.version,
                intended_asset_id=session.intended_asset_id,
                asset_version=asset.version if asset else None,
                captured_at=body.captured_at,
                received_at=now(),
            )
            service.save(db, item, actor, body.reason, "v2.field.original_persisted")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
        return process_capture(service, case_id, item.id, actor, body.reason)

    @router.get("/cases/{case_id}/visual-captures", response_model=list[VisualCapture])
    def captures(case_id: str):
        with store.transaction(write=False) as db:
            return service.list(db, VisualCapture, case_id)

    @router.post("/cases/{case_id}/visual-captures/{cid}/process", response_model=VisualCapture)
    def reprocess(case_id: str, cid: str, body: Revision, actor: Actor):
        with store.transaction(write=False) as db:
            item = service.get(db, VisualCapture, cid, case_id)
            check_version(item, body.version)
            if item.state in {"ACCEPTED", "REJECTED"}:
                raise HTTPException(409, "Capture was reviewed; record a new capture instead")
        return process_capture(service, case_id, cid, actor, body.reason)

    @router.patch("/cases/{case_id}/visual-captures/{cid}/review", response_model=VisualCapture)
    def review(
        case_id: str, cid: str, body: CaptureReview, actor: Actor, idempotency_key: Annotated[str, Header()]
    ):
        operation, payload = "field.review:" + cid, body.model_dump(mode="json")
        with store.transaction() as db:
            item = service.get(db, VisualCapture, cid, case_id)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return item
            check_version(item, body.version)
            if item.state in {"ACCEPTED", "REJECTED"}:
                raise HTTPException(409, "Capture already reviewed; use a new capture or retract its binding")
            ev = service.evidence(db, item.evidence_id, case_id)
            check_version(ev, item.evidence_version)
            if body.intended_asset_id and body.intended_asset_id != item.intended_asset_id:
                target = store.get(db, Asset, body.intended_asset_id, item.inspection_id)
                item.intended_asset_id, item.asset_version = target.id, target.version
            if body.action in {"correct", "accept"}:
                item.working_fields = body.fields
            if body.action == "accept":
                if not body.checked_original or not item.intended_asset_id:
                    raise HTTPException(
                        422, "Review the original and select an intended asset before identity acceptance"
                    )
                if (
                    item.comparison.get("decision") == "CONFLICTING_SOURCES"
                    and not body.acknowledge_conflicts
                ):
                    raise HTTPException(
                        422, "Explicitly acknowledge and explain conflicting source identifiers"
                    )
                asset = store.get(db, Asset, item.intended_asset_id, item.inspection_id)
                check_version(asset, item.asset_version)
                if not all(
                    normalized(getattr(body.fields, k))
                    and normalized(getattr(body.fields, k)) == normalized(getattr(asset, k))
                    for k in ("serial", "model", "site")
                ):
                    raise HTTPException(
                        422,
                        "Reviewed serial, model and site must match the declared machine; never fill unknowns from expectation",
                    )
                for key in ("serial", "model", "site"):
                    setattr(ev.facts, key, getattr(body.fields, key))
                ev.confirmed, ev.quality_flags = True, ["manual_correction"]
                store.save(db, ev, actor, body.reason, "evidence.analyst_correction")
                item.evidence_version = ev.version
                bindings = [
                    b
                    for b in service.list(db, AssetBinding, case_id)
                    if b.active and b.local_asset_id == asset.id
                ]
                if bindings:
                    physical_id = bindings[0].physical_asset_id
                    service.binding(db, case_id, physical_id, item.inspection_id)
                else:
                    existing = [
                        p
                        for p in service.list(db, PhysicalAsset, case_id)
                        if normalized(p.serial) == normalized(asset.serial)
                    ]
                    args = {
                        "inspection_id": item.inspection_id,
                        "local_asset_id": asset.id,
                        "identity_evidence_id": ev.id,
                        "identity_locator": "Field capture " + item.id,
                        "manufacturer": body.fields.manufacturer,
                        "reason": body.reason,
                    }
                    request_body = (
                        BindAsset(physical_asset_id=existing[0].id, **args)
                        if existing
                        else PhysicalAssetCreate(**args)
                    )
                    physical, _ = service.confirm_identity(
                        db, case_id, request_body, actor, existing[0] if existing else None
                    )
                    physical_id = physical.id
                item.physical_asset_id, item.state = physical_id, "ACCEPTED"
                session = service.get(db, FieldSession, item.session_id, case_id)
                session.physical_asset_id = physical_id
                service.save(db, session, actor, body.reason, "v2.field.identity_confirmed")
            elif body.action == "reject":
                item.state = "REJECTED"
            elif body.action == "rescan":
                item.state = "NEEDS_RESCAN"
            else:
                item.state = "NEEDS_REVIEW"
            item.reviewed_by, item.review_reason = actor, body.reason
            service.save(db, item, actor, body.reason, "v2.field.capture_" + body.action)
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.post("/cases/{case_id}/documentary-reviews", response_model=DocumentaryReview, status_code=201)
    def documentary(
        case_id: str, body: DocumentaryInput, actor: Actor, idempotency_key: Annotated[str, Header()]
    ):
        payload, operation = body.model_dump(mode="json"), "documentary.review:" + case_id
        with store.transaction() as db:
            service.require_visit(db, case_id, body.inspection_id)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, DocumentaryReview, previous, case_id)
            if not body.checked_originals:
                raise HTTPException(422, "Review the documentary sources explicitly")
            if body.project_id:
                service.get(db, InvestmentProject, body.project_id, case_id)
            versions = {}
            for eid in body.evidence_ids:
                ev = service.evidence(db, eid, case_id, accepted=True)
                if ev.kind in {"site_image", "site_observation", "management_statement"}:
                    raise HTTPException(422, "Documentary support requires documentary source records")
                versions[eid] = ev.version
            if body.status != "INCONCLUSIVE" and not versions:
                raise HTTPException(422, "Accepted documentary evidence is required")
            if body.status == "DOCUMENTARILY_SUPPORTED" and body.supported_quantity != body.declared_quantity:
                raise HTTPException(422, "Full documentary support requires matching reviewed quantities")
            if body.status == "PARTIALLY_SUPPORTED" and (
                body.supported_quantity is None or not 0 < body.supported_quantity < body.declared_quantity
            ):
                raise HTTPException(
                    422, "Partial support requires a positive reviewed quantity below the declared quantity"
                )
            item = DocumentaryReview(
                case_id=case_id,
                evidence_versions=versions,
                reviewed_by=actor,
                review_reason=body.reason,
                **body.model_dump(exclude={"evidence_ids", "reason", "checked_originals"}),
            )
            service.save(db, item, actor, body.reason, "v2.documentary.reviewed")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.get("/cases/{case_id}/documentary-reviews")
    def documentary_list(case_id: str):
        with store.transaction(write=False) as db:
            results = []
            for item in service.list(db, DocumentaryReview, case_id):
                current = True
                for eid, version in item.evidence_versions.items():
                    try:
                        ev = service.evidence(db, eid, case_id, accepted=True)
                        current = current and ev.version == version
                    except HTTPException:
                        current = False
                results.append({"review": item, "source_current": current, "physically_verified": False})
            return results
