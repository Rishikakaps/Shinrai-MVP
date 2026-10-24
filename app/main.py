import hashlib
import hmac
import io
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image, UnidentifiedImageError

from app import engine
from app.extraction import MAX_BYTES, extract, parse_facts
from app.models import (
    Asset,
    AssetCreate,
    AssetUpdate,
    Claim,
    ClaimConfirmation,
    ClaimKind,
    Evidence,
    EvidenceCorrection,
    EvidenceKind,
    EvidenceLink,
    Finding,
    FindingReview,
    FollowUpAction,
    FollowUpCreate,
    FollowUpUpdate,
    Inspection,
    InspectionCreate,
    LinkCreate,
    LinkRetraction,
    Mission,
    MissionItem,
    Observation,
    ObservationCreate,
    Reason,
    Report,
    ReviewEvent,
    now,
)
from app.store import Store

bearer = HTTPBearer(auto_error=False)


class BodyLimit:
    """Bound the entire multipart request, including chunked requests without Content-Length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > MAX_BYTES + 65536:
                return await JSONResponse({"detail": "Request exceeds 12 MiB evidence limit"}, 413)(
                    scope, receive, send
                )
            chunks.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay():
            nonlocal index
            if index < len(chunks):
                message = chunks[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay, send)


def validate_file(content, filename, content_type):
    suffix = Path(filename).suffix.lower()
    types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".txt": "text/plain",
    }
    if suffix not in types or types[suffix] != content_type:
        raise HTTPException(415, "Use PDF, PNG, JPEG, or UTF-8 TXT with matching MIME type")
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(413, "Empty file or file exceeds 12 MiB")
    try:
        if suffix == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("Invalid PDF signature")
            try:
                subprocess.run(
                    [sys.executable, "-m", "app.validation"],
                    input=content,
                    capture_output=True,
                    check=True,
                    timeout=10,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                raise ValueError("Malformed, encrypted, or excessive PDF") from exc
        elif content_type.startswith("image/"):
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > 20_000_000:
                    raise ValueError("Image exceeds 20 MP")
                if image.format != ("PNG" if suffix == ".png" else "JPEG"):
                    raise ValueError("Image signature mismatch")
                image.verify()
        else:
            text = content.decode("utf-8")
            if "\x00" in text:
                raise ValueError("Binary data in text file")
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Malformed or oversized document/image") from exc
    return types[suffix]


def create_app(data_dir: Path | str | None = None, tokens: dict | None = None) -> FastAPI:
    tokens = tokens if tokens is not None else json.loads(os.environ.get("CDI_TOKENS", "{}"))
    if not tokens or any(
        len(key) < 32
        or not isinstance(value, dict)
        or set(value) != {"actor", "role"}
        or not value["actor"]
        or value["role"] not in ("analyst", "judge")
        for key, value in tokens.items()
    ):
        raise RuntimeError("Set CDI_TOKENS to a JSON token map with 32+ character secrets and actor/role")
    origins = [x.strip() for x in os.environ.get("CDI_CORS_ORIGINS", "").split(",") if x.strip()]
    if "*" in origins:
        raise RuntimeError("Use explicit CORS origins")
    store = Store(Path(data_dir or os.environ.get("CDI_DATA_DIR", "data")))
    app = FastAPI(
        title="Capital Deployment Integrity V1",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.add_middleware(BodyLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authenticate(
        request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ):
        principal = None
        if credentials and credentials.scheme.lower() == "bearer":
            for token, value in tokens.items():
                if hmac.compare_digest(token, credentials.credentials):
                    principal = value
        if principal is None:
            raise HTTPException(401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"})
        if request.method not in ("GET", "HEAD", "OPTIONS") and principal["role"] != "analyst":
            raise HTTPException(403, "Judge access is read-only")
        return principal["actor"]

    Actor = Annotated[str, Depends(authenticate)]
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate)])

    def inspection(db, iid):
        return store.get(db, Inspection, iid, iid)

    def activate(db, iid, actor, reason):
        item = inspection(db, iid)
        if item.state != "active":
            item.state = "active"
            store.save(db, item, actor, reason, "inspection.invalidated_or_started")

    def version_check(obj, version):
        if obj.version != version:
            raise HTTPException(409, "Stale version; reload and review changes")

    def save_original(content):
        digest = hashlib.sha256(content).hexdigest()
        path = store.files / digest
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise HTTPException(409, "Existing original failed integrity check; restore from backup")
        else:
            try:
                with path.open("xb") as file:
                    os.chmod(path, 0o600)
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise HTTPException(409, "Concurrent file integrity conflict")
        return digest

    def get_report(db, iid):
        item = inspection(db, iid)
        current = engine.current_findings(store, db, iid)
        # Detect external file corruption even after review completion.
        claims = store.list(db, Claim, iid)
        if item.state == "review_complete" and len(current) != len(claims):
            item = item.model_copy(update={"state": "active"})
        return Report(
            inspection=item,
            assets=store.list(db, Asset, iid),
            claims=claims,
            evidence=store.list(db, Evidence, iid),
            evidence_links=store.list(db, EvidenceLink, iid),
            findings=current,
            finding_history=store.list(db, Finding, iid),
            reconciliation_current=bool(claims) and len(current) == len(claims),
            integrity_issues=[e.id for e in store.list(db, Evidence, iid) if not engine.intact(store, e)],
            observations=store.list(db, Observation, iid),
            follow_ups=store.list(db, FollowUpAction, iid),
            review_events=store.events(db, iid),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/openapi.json", dependencies=[Depends(authenticate)])
    def openapi_schema() -> dict:
        return app.openapi()

    @router.post("/inspections", response_model=Inspection, status_code=201)
    def create_inspection(body: InspectionCreate, actor: Actor):
        item = Inspection(inspection_id="", name=body.name, site=body.site)
        item.inspection_id = item.id
        with store.transaction() as db:
            return store.save(db, item, actor, body.reason, "inspection.created")

    @router.get("/inspections", response_model=list[Inspection])
    def list_inspections():
        with store.transaction() as db:
            return store.list(db, Inspection)

    @router.get("/inspections/{iid}", response_model=Inspection)
    def get_inspection(iid: str):
        with store.transaction() as db:
            item = inspection(db, iid)
            if item.state == "review_complete" and len(engine.current_findings(store, db, iid)) != len(
                store.list(db, Claim, iid)
            ):
                item.state = "active"
            return item

    @router.post("/inspections/{iid}/assets", response_model=Asset, status_code=201)
    def create_asset(iid: str, body: AssetCreate, actor: Actor):
        with store.transaction() as db:
            inspection(db, iid)
            if any(engine.norm(a.tag) == engine.norm(body.tag) for a in store.list(db, Asset, iid)):
                raise HTTPException(409, "Asset tag already exists")
            asset = Asset(inspection_id=iid, **body.model_dump(exclude={"reason"}))
            store.save(db, asset, actor, body.reason, "asset.created")
            expectations = {
                "identity": body.serial,
                "purchase": body.invoice_ref,
                "payment": body.payment_ref,
                "presence": "present",
                "installation": "installed",
                "commissioning": "commissioned",
            }
            for kind in ClaimKind:
                store.save(
                    db,
                    Claim(inspection_id=iid, asset_id=asset.id, kind=kind, expected=expectations[kind]),
                    actor,
                    body.reason,
                    "claim.declared",
                )
            activate(db, iid, actor, body.reason)
            return asset

    @router.patch("/inspections/{iid}/assets/{aid}", response_model=Asset)
    def update_asset(iid: str, aid: str, body: AssetUpdate, actor: Actor):
        with store.transaction() as db:
            item = store.get(db, Asset, aid, iid)
            version_check(item, body.version)
            if any(
                a.id != aid and engine.norm(a.tag) == engine.norm(body.tag)
                for a in store.list(db, Asset, iid)
            ):
                raise HTTPException(409, "Asset tag already exists")
            for field in ("tag", "serial", "model", "site", "invoice_ref", "payment_ref"):
                setattr(item, field, getattr(body, field))
            store.save(db, item, actor, body.reason, "asset.corrected")
            expected = {
                "identity": item.serial,
                "purchase": item.invoice_ref,
                "payment": item.payment_ref,
                "presence": "present",
                "installation": "installed",
                "commissioning": "commissioned",
            }
            for claim in store.list(db, Claim, iid):
                if claim.asset_id == aid:
                    claim.expected = expected[claim.kind]
                    claim.confirmed = False
                    store.save(db, claim, actor, body.reason, "claim.declaration_corrected")
            activate(db, iid, actor, body.reason)
            return item

    @router.get("/inspections/{iid}/claims", response_model=list[Claim])
    def list_claims(iid: str):
        with store.transaction() as db:
            inspection(db, iid)
            return store.list(db, Claim, iid)

    @router.patch("/inspections/{iid}/claims/{cid}/confirmation", response_model=Claim)
    def confirm_claim(iid: str, cid: str, body: ClaimConfirmation, actor: Actor):
        with store.transaction() as db:
            item = store.get(db, Claim, cid, iid)
            version_check(item, body.version)
            asset = store.get(db, Asset, item.asset_id, iid)
            locked = {
                "identity": asset.serial,
                "purchase": asset.invoice_ref,
                "payment": asset.payment_ref,
                "presence": "present",
                "installation": "installed",
                "commissioning": "commissioned",
            }
            if body.expected != locked[item.kind]:
                raise HTTPException(
                    422,
                    "Change asset declarations through the audited asset correction endpoint first",
                )
            item.confirmed = body.confirmed
            store.save(
                db, item, actor, body.reason, "claim.confirmed" if body.confirmed else "claim.unconfirmed"
            )
            activate(db, iid, actor, body.reason)
            return item

    @router.post("/inspections/{iid}/evidence", response_model=Evidence, status_code=201)
    def upload(
        iid: str,
        actor: Actor,
        file: Annotated[UploadFile, File()],
        kind: Annotated[EvidenceKind, Form()],
        source: Annotated[str, Form(min_length=1, max_length=200)],
        captured_at: Annotated[datetime, Form()],
        reason: Annotated[str, Form(min_length=1, max_length=4000)],
    ):
        if not captured_at.tzinfo or captured_at > datetime.now(UTC):
            raise HTTPException(422, "Capture timestamp must have a timezone and cannot be in the future")
        if not source.strip() or not reason.strip():
            raise HTTPException(422, "Source and reason cannot be blank")
        content = file.file.read(MAX_BYTES + 1)
        media_type = validate_file(content, file.filename or "", file.content_type)
        filename = Path((file.filename or "evidence").replace("\\", "/")).name[:200]
        with store.transaction() as db:
            inspection(db, iid)
            digest = save_original(content)
            item = Evidence(
                inspection_id=iid,
                kind=kind,
                filename=filename,
                media_type=media_type,
                sha256=digest,
                byte_size=len(content),
                source=source.strip(),
                captured_at=captured_at,
            )
            store.save(db, item, actor, reason, "evidence.uploaded")
            activate(db, iid, actor, reason)
            return item

    @router.get("/inspections/{iid}/evidence", response_model=list[Evidence])
    def list_evidence(iid: str):
        with store.transaction() as db:
            inspection(db, iid)
            return store.list(db, Evidence, iid)

    @router.get("/inspections/{iid}/evidence/{eid}", response_model=Evidence)
    def get_evidence(iid: str, eid: str):
        with store.transaction() as db:
            return store.get(db, Evidence, eid, iid)

    @router.get("/inspections/{iid}/evidence/{eid}/original")
    def original(iid: str, eid: str):
        with store.transaction() as db:
            item = store.get(db, Evidence, eid, iid)
            if not engine.intact(store, item):
                raise HTTPException(409, "Original integrity check failed")
            return FileResponse(
                store.files / item.sha256,
                media_type=item.media_type,
                filename=item.filename,
                headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
            )

    @router.post("/inspections/{iid}/evidence/{eid}/extract", response_model=Evidence)
    def extract_evidence(iid: str, eid: str, body: Reason, actor: Actor):
        with store.transaction() as db:
            item = store.get(db, Evidence, eid, iid)
            if not engine.intact(store, item):
                raise HTTPException(409, "Original integrity check failed")
        result = extract(store.files / item.sha256, item.media_type)
        facts, parse_flags = parse_facts(result["text"])
        with store.transaction() as db:
            fresh = store.get(db, Evidence, eid, iid)
            version_check(fresh, item.version)
            fresh.text, fresh.facts = result["text"], facts
            fresh.extraction_pages = result["pages"]
            fresh.extraction_method = result["method"]
            fresh.quality_flags = sorted(set(result["flags"] + parse_flags))
            fresh.confidence = None  # OCR certainty is not proof confidence.
            fresh.confirmed = False
            store.save(db, fresh, actor, body.reason, "evidence.extracted")
            activate(db, iid, actor, body.reason)
            return fresh

    @router.patch("/inspections/{iid}/evidence/{eid}/correction", response_model=Evidence)
    def correct_evidence(iid: str, eid: str, body: EvidenceCorrection, actor: Actor):
        with store.transaction() as db:
            item = store.get(db, Evidence, eid, iid)
            version_check(item, body.version)
            if body.confirmed and not engine.intact(store, item):
                raise HTTPException(409, "Original integrity check failed")
            for field in ("text", "facts", "quality_flags", "confidence", "confirmed"):
                setattr(item, field, getattr(body, field))
            store.save(db, item, actor, body.reason, "evidence.analyst_correction")
            activate(db, iid, actor, body.reason)
            return item

    @router.post("/inspections/{iid}/evidence-links", response_model=EvidenceLink, status_code=201)
    def link_evidence(iid: str, body: LinkCreate, actor: Actor):
        with store.transaction() as db:
            store.get(db, Claim, body.claim_id, iid)
            ev = store.get(db, Evidence, body.evidence_id, iid)
            if (
                ev.kind in (EvidenceKind.financial_statement, EvidenceKind.management_statement)
                and body.relation != "context"
            ):
                raise HTTPException(422, "Statements are context only")
            if any(
                l.active
                and l.claim_id == body.claim_id
                and l.evidence_id == body.evidence_id
                and l.relation == body.relation
                for l in store.list(db, EvidenceLink, iid)
            ):
                raise HTTPException(409, "Active evidence link already exists")
            item = EvidenceLink(inspection_id=iid, **body.model_dump(exclude={"reason"}))
            store.save(db, item, actor, body.reason, "link.created")
            activate(db, iid, actor, body.reason)
            return item

    @router.post("/inspections/{iid}/evidence-links/{lid}/retract", response_model=EvidenceLink)
    def retract_link(iid: str, lid: str, body: LinkRetraction, actor: Actor):
        with store.transaction() as db:
            item = store.get(db, EvidenceLink, lid, iid)
            version_check(item, body.version)
            item.active = False
            store.save(db, item, actor, body.reason, "link.retracted")
            activate(db, iid, actor, body.reason)
            return item

    @router.post("/inspections/{iid}/observations", response_model=Observation, status_code=201)
    def observe(iid: str, body: ObservationCreate, actor: Actor):
        if not body.captured_at.tzinfo or body.captured_at > datetime.now(UTC):
            raise HTTPException(422, "Observation timestamp must have a timezone and cannot be in the future")
        with store.transaction() as db:
            store.get(db, Asset, body.asset_id, iid)
            content = body.model_dump_json().encode()
            digest = save_original(content)
            ev = Evidence(
                inspection_id=iid,
                kind=(
                    EvidenceKind.site_observation
                    if body.source == "analyst"
                    else EvidenceKind.management_statement
                ),
                filename="observation.json",
                media_type="application/json",
                sha256=digest,
                byte_size=len(content),
                source=actor if body.source == "analyst" else "Management statement recorded by " + actor,
                captured_at=body.captured_at,
                text=body.text,
                facts=body.facts,
                confirmed=True,
                extraction_method="analyst_observation",
            )
            store.save(db, ev, actor, body.reason, "evidence.observed")
            item = Observation(
                inspection_id=iid,
                asset_id=body.asset_id,
                evidence_id=ev.id,
                text=body.text,
                source=body.source,
            )
            store.save(db, item, actor, body.reason, "observation.created")
            activate(db, iid, actor, body.reason)
            return item

    @router.get("/inspections/{iid}/mission", response_model=Mission)
    def mission(iid: str):
        with store.transaction() as db:
            inspection(db, iid)
            claims = {c.id: c for c in store.list(db, Claim, iid)}
            findings = engine.current_findings(store, db, iid)
            items = []
            for asset in store.list(db, Asset, iid):
                actions = [
                    "Confirm serial plate, model and site",
                    "Record machine condition and capture timestamp",
                    "Check installation and request commissioning certificate",
                ]
                actions += [
                    f.next_best_action
                    for f in findings
                    if claims[f.claim_id].asset_id == asset.id and f.computed_status != "supported"
                ]
                items.append(
                    MissionItem(asset_id=asset.id, tag=asset.tag, checklist=list(dict.fromkeys(actions)))
                )
            return Mission(inspection_id=iid, items=items)

    @router.post("/inspections/{iid}/reconcile", response_model=list[Finding])
    def reconcile(iid: str, body: Reason, actor: Actor):
        with store.transaction() as db:
            inspection(db, iid)
            current = engine.current_findings(store, db, iid)
            if current and len(current) == len(store.list(db, Claim, iid)):
                return current
            findings = engine.evaluate(store, db, iid, engine.basis(store, db, iid))
            for finding in findings:
                store.save(db, finding, actor, body.reason, "finding.computed")
            activate(db, iid, actor, body.reason)
            return findings

    @router.patch("/inspections/{iid}/findings/{fid}/review", response_model=Finding)
    def review(iid: str, fid: str, body: FindingReview, actor: Actor):
        with store.transaction() as db:
            item = store.get(db, Finding, fid, iid)
            version_check(item, body.version)
            if item.id not in {f.id for f in engine.current_findings(store, db, iid)}:
                raise HTTPException(409, "Finding is stale; reconcile before review")
            item.reviewed_status, item.reviewed_by = body.status, actor
            item.reviewed_at, item.review_reason = now(), body.reason
            store.save(db, item, actor, body.reason, "finding.reviewed_or_overridden")
            activate(db, iid, actor, body.reason)
            return item

    @router.post("/inspections/{iid}/review-complete", response_model=Inspection)
    def complete(iid: str, body: Reason, actor: Actor):
        with store.transaction() as db:
            item = inspection(db, iid)
            claims = store.list(db, Claim, iid)
            findings = engine.current_findings(store, db, iid)
            if (
                not claims
                or not all(c.confirmed for c in claims)
                or len(findings) != len(claims)
                or not all(f.reviewed_by for f in findings)
            ):
                raise HTTPException(409, "Confirm every claim and review every current finding first")
            item.state = "review_complete"
            return store.save(db, item, actor, body.reason, "inspection.review_complete")

    @router.post("/inspections/{iid}/follow-ups", response_model=FollowUpAction, status_code=201)
    def create_follow_up(iid: str, body: FollowUpCreate, actor: Actor):
        with store.transaction() as db:
            store.get(db, Claim, body.claim_id, iid)
            item = FollowUpAction(inspection_id=iid, claim_id=body.claim_id, request=body.request)
            return store.save(db, item, actor, body.reason, "follow_up.created")

    @router.patch("/inspections/{iid}/follow-ups/{aid}", response_model=FollowUpAction)
    def change_follow_up(iid: str, aid: str, body: FollowUpUpdate, actor: Actor):
        with store.transaction() as db:
            item = store.get(db, FollowUpAction, aid, iid)
            version_check(item, body.version)
            item.state, item.resolution = body.state, body.resolution
            return store.save(db, item, actor, body.reason, "follow_up.updated")

    @router.get("/inspections/{iid}/follow-ups", response_model=list[FollowUpAction])
    def follow_ups(iid: str):
        with store.transaction() as db:
            inspection(db, iid)
            return store.list(db, FollowUpAction, iid)

    @router.get("/inspections/{iid}/review-events", response_model=list[ReviewEvent])
    def events(iid: str):
        with store.transaction() as db:
            inspection(db, iid)
            return store.events(db, iid)

    @router.get("/inspections/{iid}/export", response_model=Report)
    def export(iid: str):
        with store.transaction() as db:
            return get_report(db, iid)

    @router.get("/inspections/{iid}/report", response_class=PlainTextResponse)
    def report(iid: str):
        with store.transaction() as db:
            snapshot = get_report(db, iid)
        claims = {c.id: c for c in snapshot.claims}
        assets = {a.id: a for a in snapshot.assets}
        lines = [
            "Capital Deployment Integrity V1",
            f"Inspection: {snapshot.inspection.name}",
            f"Site: {snapshot.inspection.site}",
            f"Review state: {snapshot.inspection.state}",
            snapshot.scope,
            "Review completion is separate from evidentiary support.",
            "Findings stale or not yet computed."
            if len(snapshot.findings) != len(snapshot.claims)
            else "Current findings:",
        ]
        for finding in snapshot.findings:
            claim = claims[finding.claim_id]
            lines += [
                (
                    f"{assets[claim.asset_id].tag} / {claim.kind}: computed={finding.computed_status}; "
                    f"reviewed={finding.reviewed_status or 'pending'}"
                ),
                finding.explanation,
                "Next action: " + finding.next_best_action,
                "Accepted evidence: " + ", ".join(finding.evidence_ids),
            ]
        lines += ["Follow-up actions:"] + [
            f"{a.state}: {a.request}; {a.resolution or ''}" for a in snapshot.follow_ups
        ]
        lines += ["Contextual observations:"] + [f"{o.source}: {o.text}" for o in snapshot.observations]
        return "\n".join(lines) + "\n"

    app.include_router(router)
    return app
