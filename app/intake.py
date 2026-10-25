"""Reviewed evidence intake, source-preserving transforms and registry proposals."""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import Field

from app import engine
from app.extraction import MAX_BYTES, extract, parse_facts
from app.identifiers import UNCERTAIN, code_fields, normalized, parse_fields
from app.models import (
    Asset,
    AssetCreate,
    AssetUpdate,
    Claim,
    Entity,
    Evidence,
    EvidenceLink,
    Inspection,
    Model,
    Reason,
    Text,
)
from app.registry import save_asset
from app.v2_media import persist_original
from app.v2_store import check_version


class Intake(Entity):
    evidence_id: str
    state: Literal["uploaded", "needs_review", "failed", "assigned", "rejected"] = "uploaded"
    category: str = "unknown"
    suggested_title: str = ""
    raw_extraction: dict = Field(default_factory=dict)
    candidates: list[dict] = Field(default_factory=list)
    decision: str = "UNASSIGNED"
    selected_asset_id: str | None = None
    parent_id: str | None = None
    timestamp_seconds: float | None = None
    transform: dict = Field(default_factory=dict)
    error: str | None = None
    reviewed_by: str | None = None


class IntakeReview(Model):
    version: int = Field(ge=1)
    action: Literal["assign", "create", "update", "reject"]
    target_id: str | None = None
    target_version: int | None = Field(default=None, ge=1)
    fields: AssetCreate | None = None
    checked_original: bool = False
    acknowledge_conflicts: bool = False
    reason: Text


class Transform(Reason):
    version: int = Field(ge=1)
    crop: tuple[int, int, int, int] | None = None
    rotate: Literal[0, 90, 180, 270] = 0
    autocontrast: bool = False


def resolve(assets, fields):
    """Candidates only. Unknown/partial/conflicting identifiers never cause a link."""
    serials = fields.get("serial", [])
    tags = fields.get("asset_id", [])
    strong = []
    for a in assets:
        matches, conflicts = [], []
        for key, values in [
            ("serial", serials),
            ("tag", tags),
            ("model", fields.get("model", [])),
            ("manufacturer", fields.get("manufacturer", [])),
        ]:
            expected = getattr(a, key)
            if not values or not expected:
                continue
            if normalized(expected) in {normalized(v) for v in values}:
                matches.append(key)
            else:
                conflicts.append(key)
        if matches:
            strong.append(
                {
                    "asset_id": a.id,
                    "tag": a.tag,
                    "matches": matches,
                    "conflicts": conflicts,
                    "method": "serial"
                    if "serial" in matches
                    else "asset_id"
                    if "tag" in matches
                    else "model_only",
                }
            )
    if any(len({normalized(v) for v in values}) > 1 for values in fields.values()) or any(
        UNCERTAIN.search(v) for values in fields.values() for v in values
    ):
        return "CONFLICTING_OR_PARTIAL", strong
    exact = [c for c in strong if c["method"] in {"serial", "asset_id"}]
    if len(exact) == 1 and not exact[0]["conflicts"]:
        # An explicit unknown serial must not be ignored just because a tag matches.
        if serials and "serial" not in exact[0]["matches"]:
            return "CONFLICT", strong
        return "CANDIDATE_NEEDS_REVIEW", strong
    if exact:
        return "CONFLICT", strong
    if serials or tags:
        return "UNKNOWN_IDENTIFIER", strong
    return ("MODEL_ONLY_REVIEW" if strong else "UNASSIGNED"), strong


def structured(result, codes=None):
    text = result["text"]
    fields = parse_fields(text)
    patterns = {
        "asset_id": r"(?:asset(?:\s*id)?|tag)",
        "rated_power_kw": r"(?:rated_power_kw|power\s*(?:\(kw\)|kw)|kilowatts)",
        "horse_power": r"(?:horse_power|hp)",
        "rated_voltage_v": r"(?:rated_voltage_v|voltage)",
        "rated_speed_rpm": r"(?:rated_speed_rpm|rpm|speed)",
    }
    for key, pattern in patterns.items():
        fields[key] = list(
            dict.fromkeys(
                m.group(1).strip()
                for m in re.finditer(
                    rf"^\s*{pattern}\s*[:#=]\s*([^\r\n]{{1,200}})", text, re.IGNORECASE | re.MULTILINE
                )
            )
        )[:20]
    for code in codes or []:
        values = code_fields(code["text"])
        # Structured tags are kept separate from serial identifiers.
        import json

        try:
            obj = json.loads(code["text"])
            if (
                isinstance(obj, dict)
                and isinstance(obj.get("asset_id"), str)
                and 0 < len(obj["asset_id"]) <= 200
            ):
                values["asset_id"] = [obj["asset_id"]]
        except (ValueError, TypeError):
            pass
        for key, vals in values.items():
            fields[key] = list(dict.fromkeys(fields.get(key, []) + vals))
    category = "unknown"
    lower = text.casefold()
    for name, marker in [
        ("commissioning_certificate", "commissioning"),
        ("invoice", "invoice"),
        ("payment_extract", "payment"),
        ("motor_nameplate", "rpm"),
        ("motor_nameplate", "serial"),
    ]:
        if marker in lower:
            category = name
            break
    return {
        "text": text,
        "pages": result.get("pages", []),
        "method": result["method"],
        "flags": result.get("flags", []),
        "fields": fields,
        "codes": codes or [],
        "category": category,
    }


def process_item(store, iid, item_id, actor, reason):
    with store.transaction(write=False) as db:
        item = store.get(db, Intake, item_id, iid)
        ev = store.get(db, Evidence, item.evidence_id, iid)
        if item.state != "uploaded":
            return item
        if not engine.intact(store, ev):
            raise HTTPException(409, "Original integrity failed")
    if ev.media_type.startswith("video/"):
        return process_video(store, iid, item, ev, actor, reason)
    result = extract(store.files / ev.sha256, ev.media_type)
    codes = []
    if ev.media_type.startswith("image/"):
        from app.label_scan import scan_file

        try:
            codes = scan_file(store.files / ev.sha256).get("codes", [])
        except HTTPException:
            pass
    raw = structured(result, codes)
    with store.transaction() as db:
        current = store.get(db, Intake, item_id, iid)
        check_version(current, item.version)
        ev = store.get(db, Evidence, ev.id, iid)
        ev.text, ev.extraction_pages, ev.extraction_method = (
            result["text"],
            result.get("pages", []),
            result["method"],
        )
        # Revalidate pages through Pydantic rather than retaining untyped dictionaries.
        ev = Evidence.model_validate(ev.model_dump())
        ev.facts, flags = parse_facts(result["text"])
        ev.quality_flags, ev.confirmed = sorted(set(result.get("flags", []) + flags)), False
        store.save(db, ev, actor, reason, "evidence.extracted")
        current.raw_extraction, current.category = raw, raw["category"]
        current.decision, current.candidates = resolve(store.list(db, Asset, iid), raw["fields"])
        current.state = "failed" if result["method"] == "failed" else "needs_review"
        current.error = (
            "Extraction failed. Original retained; use manual review." if current.state == "failed" else None
        )
        label = next((c["tag"] for c in current.candidates if c["method"] != "model_only"), "Unassigned")
        current.suggested_title = (
            f"{label}_{current.category}_{ev.captured_at.date()}{Path(ev.filename).suffix}"
        )
        return store.save(db, current, actor, reason, "intake.processed")


def save_upload(
    store,
    db,
    iid,
    content,
    filename,
    media,
    source,
    captured_at,
    actor,
    reason,
    parent=None,
    timestamp=None,
    transform=None,
):
    digest = persist_original(store.files, content)
    ev = Evidence(
        inspection_id=iid,
        kind="site_image",
        filename=filename,
        media_type=media,
        sha256=digest,
        byte_size=len(content),
        source=source,
        captured_at=captured_at,
    )
    store.save(db, ev, actor, reason, "evidence.uploaded")
    item = Intake(
        inspection_id=iid,
        evidence_id=ev.id,
        parent_id=parent,
        timestamp_seconds=timestamp,
        transform=transform or {},
    )
    store.save(db, item, actor, reason, "intake.uploaded")
    inspection = store.get(db, Inspection, iid, iid)
    if inspection.state != "active":
        inspection.state = "active"
        store.save(db, inspection, actor, reason, "inspection.invalidated_or_started")
    return item


def process_video(store, iid, item, ev, actor, reason):
    from app.video import video_frames

    try:
        metadata, frames = video_frames(store.files / ev.sha256)
    except HTTPException as exc:
        with store.transaction() as db:
            current = store.get(db, Intake, item.id, iid)
            check_version(current, item.version)
            current.state, current.error = "failed", str(exc.detail)
            return store.save(db, current, actor, reason, "intake.video_failed")
    with store.transaction() as db:
        current = store.get(db, Intake, item.id, iid)
        check_version(current, item.version)
        children = []
        for timestamp, content in frames:
            child = save_upload(
                store,
                db,
                iid,
                content,
                f"frame-{timestamp:.2f}s.jpg",
                "image/jpeg",
                f"Video {ev.id} at {timestamp:.2f}s",
                ev.captured_at,
                actor,
                reason,
                item.id,
                timestamp,
            )
            children.append(child.id)
        current.raw_extraction = {"video": metadata, "frame_ids": children}
        current.state, current.category, current.decision = "needs_review", "video", "REVIEW_FRAMES"
        current.suggested_title = f"Video_{ev.captured_at.date()}{Path(ev.filename).suffix}"
        store.save(db, current, actor, reason, "intake.video_frames_extracted")
    # Frames use the same OCR, matching, review and original-file services as photographs.
    for child_id in children:
        process_item(store, iid, child_id, actor, reason)
    return current


def install_intake(app, store, authenticate):
    Actor = Annotated[str, Depends(authenticate)]
    router = APIRouter(
        prefix="/api/v1/inspections/{iid}", dependencies=[Depends(authenticate)], tags=["Intake"]
    )

    @router.get("/intake")
    def inbox(iid: str):
        with store.transaction(write=False) as db:
            store.get(db, Inspection, iid, iid)
            items = store.list(db, Intake, iid)
            assets = store.list(db, Asset, iid)
            # Re-evaluate candidates on read so registry edits never leave stale matching advice.
            for item in items:
                if item.state in {"needs_review", "failed"} and "fields" in item.raw_extraction:
                    item.decision, item.candidates = resolve(assets, item.raw_extraction["fields"])
            return items

    @router.post("/intake", status_code=201)
    def upload(
        iid: str,
        actor: Actor,
        file: Annotated[UploadFile, File()],
        source: Annotated[str, Form(min_length=1, max_length=200)],
        captured_at: Annotated[datetime, Form()],
        reason: Annotated[str, Form(min_length=1, max_length=4000)],
        idempotency_key: Annotated[str, Header()],
    ):
        from app.main import validate_file

        if (
            not captured_at.tzinfo
            or captured_at > datetime.now(UTC)
            or not source.strip()
            or not reason.strip()
        ):
            raise HTTPException(422, "Use a valid source, reason and past timezone-aware capture time")
        content = file.file.read(MAX_BYTES + 1)
        filename = Path((file.filename or "evidence").replace("\\", "/")).name[:200]
        media = (file.content_type or "").split(";")[0]
        if media.startswith("video/"):
            if Path(filename).suffix.lower() not in {".mp4", ".mov"} or media not in {
                "video/mp4",
                "video/quicktime",
            }:
                raise HTTPException(415, "Use MP4/MOV video")
            if not content or len(content) > MAX_BYTES:
                raise HTTPException(413, "Video must contain 1 byte to 12 MiB")
            if content[4:8] != b"ftyp":
                raise HTTPException(422, "Invalid video container signature")
        else:
            validate_file(content, filename, media)
        service = app.state.v2
        payload = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "filename": filename,
            "media": media,
            "source": source,
            "captured_at": captured_at.isoformat(),
            "reason": reason,
        }
        with store.transaction() as db:
            store.get(db, Inspection, iid, iid)
            old = service.retry(db, actor, "intake:" + iid, idempotency_key, payload)
            if old:
                return store.get(db, Intake, old, iid)
            item = save_upload(
                store, db, iid, content, filename, media, source.strip(), captured_at, actor, reason
            )
            service.receipt(db, actor, "intake:" + iid, idempotency_key, payload, item.id)
            return item

    @router.post("/intake/{item_id}/process")
    def process(iid: str, item_id: str, body: Reason, actor: Actor):
        return process_item(store, iid, item_id, actor, body.reason)

    @router.post("/intake/{item_id}/review")
    def review(iid: str, item_id: str, body: IntakeReview, actor: Actor):
        with store.transaction() as db:
            item = store.get(db, Intake, item_id, iid)
            check_version(item, body.version)
            ev = store.get(db, Evidence, item.evidence_id, iid)
            if not engine.intact(store, ev):
                raise HTTPException(409, "Original integrity failed")
            if item.state in {"assigned", "rejected"}:
                raise HTTPException(409, "This proposal has already been reviewed")
            if body.action == "reject":
                item.state = "rejected"
            else:
                if not body.checked_original:
                    raise HTTPException(422, "Review the original before saving a proposal")
                if ev.media_type.startswith("video/"):
                    raise HTTPException(
                        422,
                        "Review a specific timestamped frame instead of accepting a whole video as identity",
                    )
                decision, _candidates = resolve(
                    store.list(db, Asset, iid), item.raw_extraction.get("fields", {})
                )
                if (
                    decision in {"CONFLICT", "CONFLICTING_OR_PARTIAL", "UNKNOWN_IDENTIFIER"}
                    and not body.acknowledge_conflicts
                ):
                    raise HTTPException(
                        422, "Explain and explicitly acknowledge unresolved or conflicting identifiers"
                    )
                if body.action in {"create", "update"}:
                    if not body.fields:
                        raise HTTPException(422, "Reviewed registry fields required")
                    if body.action == "update":
                        if not body.target_id or body.target_version is None:
                            raise HTTPException(422, "Select a current target record/version")
                        asset = save_asset(
                            store,
                            db,
                            iid,
                            AssetUpdate(**body.fields.model_dump(), version=body.target_version),
                            actor,
                            body.target_id,
                        )
                    else:
                        asset = save_asset(store, db, iid, body.fields, actor)
                else:
                    if not body.target_id:
                        raise HTTPException(422, "Select the intended record")
                    asset = store.get(db, Asset, body.target_id, iid)
                claim = next(
                    c for c in store.list(db, Claim, iid) if c.asset_id == asset.id and c.kind == "identity"
                )
                locator = (
                    f"Frame {item.timestamp_seconds}s"
                    if item.timestamp_seconds is not None
                    else "Reviewed intake source"
                )
                store.save(
                    db,
                    EvidenceLink(
                        inspection_id=iid,
                        claim_id=claim.id,
                        evidence_id=ev.id,
                        relation="context",
                        locator=locator,
                    ),
                    actor,
                    body.reason,
                    "evidence.linked",
                )
                item.selected_asset_id, item.state = asset.id, "assigned"
            item.reviewed_by = actor
            return store.save(db, item, actor, body.reason, "intake.reviewed")

    @router.post("/intake/{item_id}/transform", status_code=201)
    def transform(iid: str, item_id: str, body: Transform, actor: Actor):
        import io

        from PIL import Image, ImageOps

        with store.transaction(write=False) as db:
            item = store.get(db, Intake, item_id, iid)
            check_version(item, body.version)
            ev = store.get(db, Evidence, item.evidence_id, iid)
            if not engine.intact(store, ev) or not ev.media_type.startswith("image/"):
                raise HTTPException(422, "Choose an intact photograph or video frame")
        with Image.open(store.files / ev.sha256) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            if body.crop:
                x, y, right, bottom = body.crop
                if not 0 <= x < right <= image.width or not 0 <= y < bottom <= image.height:
                    raise HTTPException(422, "Crop lies outside the source image")
                image = image.crop(body.crop)
            image = image.rotate(-body.rotate, expand=True)
            if body.autocontrast:
                image = ImageOps.autocontrast(image)
            content = io.BytesIO()
            image.save(content, format="JPEG", quality=95)
        with store.transaction() as db:
            current = store.get(db, Intake, item_id, iid)
            check_version(current, body.version)
            child = save_upload(
                store,
                db,
                iid,
                content.getvalue(),
                "adjusted-" + ev.filename.rsplit(".", 1)[0] + ".jpg",
                "image/jpeg",
                "Derived from " + ev.id,
                ev.captured_at,
                actor,
                body.reason,
                item.id,
                item.timestamp_seconds,
                body.model_dump(exclude={"reason", "version"}),
            )
        return child

    app.include_router(router)
