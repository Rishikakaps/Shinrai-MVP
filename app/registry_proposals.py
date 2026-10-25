"""Registry changes and adjusted images reviewed against the shared intake pipeline."""

import hashlib
import io
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from PIL import Image, ImageOps
from pydantic import Field

from app import engine
from app.intake_models import IntakeUpload
from app.intake_understanding import resolve
from app.models import Asset, AssetCreate, AssetUpdate, Evidence, Model, Text, now
from app.registry import save_asset
from app.v2_store import check_version


class RegistryProposal(Model):
    version: int = Field(ge=1)
    action: Literal["create", "update"]
    target_id: str | None = None
    target_version: int | None = Field(default=None, ge=1)
    fields: AssetCreate
    checked_original: bool
    acknowledge_conflicts: bool = False
    reason: Text


class ImageAdjustment(Model):
    version: int = Field(ge=1)
    frame_number: int | None = Field(default=None, ge=1, le=6)
    crop: tuple[int, int, int, int] | None = None
    rotate: Literal[0, 90, 180, 270] = 0
    autocontrast: bool = False
    reason: Text


def install_registry_proposals(app, store, authenticate):
    router = APIRouter(
        prefix="/api/evidence", dependencies=[Depends(authenticate)], tags=["Reviewed registry proposals"]
    )
    Actor = Annotated[str, Depends(authenticate)]
    intake = app.state.intake

    @router.post("/{identifier}/registry-proposal")
    def apply(identifier: str, body: RegistryProposal, actor: Actor):
        with store.transaction() as db:
            item = intake.get(db, identifier)
            check_version(item, body.version)
            if item.processing_status in {"queued", "processing"} or not body.checked_original:
                raise HTTPException(
                    422, "Wait for extraction and review the original before saving registry fields"
                )
            if not item.evidence_id or item.media_type.startswith(("audio/", "video/")):
                raise HTTPException(422, "Choose a document, photograph or adjusted timestamped frame")
            evidence = store.get(db, Evidence, item.evidence_id, item.inspection_id)
            if not engine.intact(store, evidence):
                raise HTTPException(409, "Original integrity check failed")
            resolution = resolve(
                item.raw_result.get("fields", []), store.list(db, Asset, item.inspection_id), item.asset_hint
            )
            exact = [
                c
                for c in resolution["candidates"]
                if c["asset_id"] == body.target_id and not c["conflicting_identifiers"]
            ]
            if (
                resolution.get("decision") != "EXACT_SERIAL_CANDIDATE" or not exact or body.action == "create"
            ) and not body.acknowledge_conflicts:
                raise HTTPException(
                    422, "Acknowledge unresolved/new/conflicting identity and explain the registry decision"
                )
            previous = item.metadata.get("registry_proposal")
            if previous:
                raise HTTPException(
                    409,
                    "This source proposal was already applied; edit the current registry record for later corrections",
                )
            body.fields.provenance["last_review_source"] = {
                "intake_id": item.id,
                "sha256": item.content_sha256,
                "synthetic_demo": item.synthetic_demo,
            }
            if body.action == "create":
                body.fields.provenance["synthetic_demo"] = item.synthetic_demo
            if body.action == "update":
                if not body.target_id or body.target_version is None:
                    raise HTTPException(422, "Select a current target record/version")
                asset = save_asset(
                    store,
                    db,
                    item.inspection_id,
                    AssetUpdate(**body.fields.model_dump(), version=body.target_version),
                    actor,
                    body.target_id,
                )
            else:
                asset = save_asset(store, db, item.inspection_id, body.fields, actor)
            item.metadata["registry_proposal"] = {
                "action": body.action,
                "asset_id": asset.id,
                "asset_version": asset.version,
                "reviewed_by": actor,
                "reviewed_at": now(),
                "reason": body.reason,
            }
            item.assigned_asset_id = asset.id
            item.processing_status = "linked"
            item.reviewed_by, item.reviewed_at, item.review_reason = actor, now(), body.reason
            intake.save(db, item, actor, body.reason, "registry_proposal_applied")
            return {"asset": asset, "intake": item, "evidence_accepted": False, "claims_supported": False}

    @router.post("/{identifier}/adjust-image", status_code=201)
    def adjust(identifier: str, body: ImageAdjustment, actor: Actor, request: Request):
        with store.transaction(write=False) as db:
            item = intake.get(db, identifier)
            check_version(item, body.version)
            if item.processing_status in {"queued", "processing"}:
                raise HTTPException(409, "Wait for processing before deriving a source image")
            original_path = store.files / item.content_sha256
            if (
                not original_path.is_file()
                or hashlib.sha256(original_path.read_bytes()).hexdigest() != item.content_sha256
            ):
                raise HTTPException(409, "Original integrity check failed")
            if body.frame_number:
                pages = item.raw_result.get("pages", [])
                if not 1 <= body.frame_number <= len(pages) or not pages[body.frame_number - 1].get("frame"):
                    raise HTTPException(404, "Source frame not found")
                page = pages[body.frame_number - 1]
                artifact = item.raw_result.get("artifact", {"record_id": item.id, "attempt": item.attempts})
                path = (
                    intake.derived / artifact["record_id"] / str(artifact["attempt"]) / page["frame"]["file"]
                )
                if not path.resolve().is_relative_to(intake.derived.resolve()):
                    raise HTTPException(409, "Invalid derived source")
                expected = page["frame"]["sha256"]
                timestamp = page["timestamp"]
            else:
                if not item.media_type.startswith("image/"):
                    raise HTTPException(422, "Choose a photo or a decoded video frame")
                path = store.files / item.content_sha256
                expected = item.content_sha256
                timestamp = item.metadata.get("source_timestamp_seconds")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise HTTPException(409, "Source integrity check failed")
            source = path.read_bytes()
        with Image.open(io.BytesIO(source)) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            if body.crop:
                left, top, right, bottom = body.crop
                if not 0 <= left < right <= image.width or not 0 <= top < bottom <= image.height:
                    raise HTTPException(422, "Crop lies outside source pixels")
                image = image.crop(body.crop)
            image = image.rotate(-body.rotate, expand=True)
            if body.autocontrast:
                image = ImageOps.autocontrast(image)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=95)
        upload = UploadFile(
            io.BytesIO(output.getvalue()),
            filename="adjusted-" + item.original_filename.rsplit(".", 1)[0] + ".jpg",
            headers={"content-type": "image/jpeg"},
        )
        # The same durable ingestion, validation and OCR queue handles every adjusted frame.
        from starlette.datastructures import Headers

        upload.headers = Headers({"content-type": "image/jpeg"})
        metadata = IntakeUpload(
            case_id=item.case_id,
            inspection_id=item.inspection_id,
            asset_hint=item.asset_hint,
            source_type="browser",
            captured_at=item.captured_at,
            synthetic_demo=item.synthetic_demo,
            reason=body.reason,
        )
        child = intake.upload(metadata, upload, actor, request.headers.get("Idempotency-Key") or now())
        with store.transaction() as db:
            current = intake.get(db, child.id)
            current.metadata.update(
                {
                    "parent_intake_id": item.id,
                    "parent_sha256": item.content_sha256,
                    "source_frame_sha256": expected,
                    "source_timestamp_seconds": timestamp,
                    "adjustment": body.model_dump(exclude={"version", "reason"}),
                }
            )
            intake.save(db, current, actor, body.reason, "derived_source_recorded")
        return current

    app.include_router(router)
