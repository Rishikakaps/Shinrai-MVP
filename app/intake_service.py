"""Durable single-host intake queue, shared originals and existing evidentiary records."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

from fastapi import HTTPException

from app.intake_models import IntakeRecord
from app.intake_understanding import classify, extract_fields, resolve
from app.models import Asset, Evidence, Facts, now
from app.v2_media import persist_original
from app.v2_models import AudioRecording, AudioUpload
from app.v2_store import check_version

KINDS = {
    "commissioning_certificate": "commissioning_certificate",
    "purchase_invoice": "invoice",
    "machine_nameplate": "site_image",
    "installation_evidence": "installation_record",
    "maintenance_record": "maintenance_record",
}


class IntakeService:
    def __init__(self, store, service, activate):
        self.store, self.service, self.activate = store, service, activate
        self.stopping, self.thread = Event(), None
        self.derived = store.root / "intake-derived"
        self.derived.mkdir(exist_ok=True)
        # Index history without changing source acceptance or the V1 reconciliation basis.
        with store.transaction() as db:
            indexed = {r.evidence_id for r in self.records(db)}
            for evidence in store.list(db, Evidence):
                if evidence.id not in indexed:
                    self.register_existing(
                        db,
                        evidence,
                        "Intake index",
                        "Index existing original without reprocessing or changing acceptance",
                    )

    def start(self):
        if os.environ.get("CDI_INTAKE_WORKER", "true").lower() == "false":
            return
        self.stopping.clear()
        self.thread = Thread(target=self.loop, daemon=True, name="evidence-intake")
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=125)

    def loop(self):
        import logging

        while not self.stopping.is_set():
            try:
                self.run_once()
            except Exception:
                logging.getLogger("uvicorn.error").exception("Intake queue tick failed")
            self.stopping.wait(0.5)

    def records(self, db, case_id=None, iid=None):
        return [r for r in self.store.list(db, IntakeRecord, iid) if case_id is None or r.case_id == case_id]

    def get(self, db, identifier):
        item = self.store.get(db, IntakeRecord, identifier)
        if item.case_id:
            self.service.require_visit(db, item.case_id, item.inspection_id)
        return item

    def save(self, db, item, actor, reason, action):
        return (
            self.service.save(db, item, actor, reason, "v2.intake." + action)
            if item.case_id
            else self.store.save(db, item, actor, reason, "v2.intake." + action)
        )

    def register_existing(self, db, evidence, actor, reason):
        """Legacy/manual uploads share the index but keep their existing manual workflow."""
        try:
            case_id = self.service.case_for_visit(db, evidence.inspection_id)
        except HTTPException:
            case_id = None
        item = IntakeRecord(
            inspection_id=evidence.inspection_id,
            case_id=case_id,
            evidence_id=evidence.id,
            uploader=actor,
            original_filename=evidence.filename,
            display_filename=evidence.filename,
            media_type=evidence.media_type,
            size_bytes=evidence.byte_size,
            content_sha256=evidence.sha256,
            storage_key=evidence.sha256,
            source_type="legacy",
            captured_at=evidence.captured_at,
            processing_status="uploaded",
        )
        return self.save(db, item, actor, reason, "registered")

    def upload(self, body, file, actor, retry_key):
        from app.main import validate_file

        media = (file.content_type or "").split(";", 1)[0].lower()
        suffix = Path(file.filename or "").suffix.lower()
        types = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".txt": "text/plain",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".webm": "audio/webm",
            ".m4a": "audio/mp4",
        }
        if body.audio_purpose and suffix == ".mp4":
            types[".mp4"] = "audio/mp4"
        if suffix not in types or media != types[suffix]:
            raise HTTPException(
                415,
                "Use PDF, PNG/JPEG, UTF-8 text, MP4/MOV video or WAV/WebM/M4A audio with the correct media type",
            )
        if (media.startswith(("video/", "audio/"))) and not body.recording_authorized:
            raise HTTPException(422, "Recording authorization must be confirmed")
        limit = (
            min(100, max(1, int(os.environ.get("CDI_INTAKE_VIDEO_MB", "100")))) * 1024 * 1024
            if media.startswith("video/")
            else 12 * 1024 * 1024
        )
        with self.store.transaction(write=False) as db:
            self.service.get_case(db, body.case_id)
            iid = body.inspection_id
            if iid is None:
                from app.v2_models import Membership

                visits = self.service.list(db, Membership, body.case_id)
                if len(visits) != 1:
                    raise HTTPException(422, "Select an inspection visit explicitly")
                iid = visits[0].inspection_id
            self.service.require_visit(db, body.case_id, iid)
            if body.asset_hint:
                self.store.get(db, Asset, body.asset_hint, iid)
            if body.physical_asset_id:
                binding = self.service.binding(db, body.case_id, body.physical_asset_id, iid)
                if body.asset_hint and body.asset_hint != binding.local_asset_id:
                    raise HTTPException(422, "Confirmed identity and asset hint differ")
        content = file.file.read(limit + 1)
        if not content or len(content) > limit:
            raise HTTPException(413, "File is empty or exceeds the intake upload limit")
        filename = Path((file.filename or "evidence").replace("\\", "/")).name[:200]
        if not media.startswith(("video/", "audio/")):
            validate_file(content, filename, media)
        elif media.startswith("video/") and content[4:8] != b"ftyp" and suffix != ".mov":
            raise HTTPException(422, "Video signature does not match MP4")
        digest = hashlib.sha256(content).hexdigest()
        payload = {
            "metadata": body.model_dump(mode="json"),
            "sha256": digest,
            "filename": filename,
            "media_type": media,
        }
        operation = "intake.upload:" + body.case_id
        with self.store.transaction(write=False) as db:
            previous = self.service.retry(db, actor, operation, retry_key, payload)
            if previous:
                return self.get(db, previous)
        persist_original(self.store.files, content)
        with self.store.transaction() as db:
            self.service.require_visit(db, body.case_id, iid)
            previous = self.service.retry(db, actor, operation, retry_key, payload)
            if previous:
                return self.get(db, previous)
            duplicates = [r for r in self.records(db, body.case_id) if r.content_sha256 == digest]
            evidence = None
            if not media.startswith(("audio/", "video/")):
                evidence = Evidence(
                    inspection_id=iid,
                    kind="other",
                    filename=filename,
                    media_type=media,
                    sha256=digest,
                    byte_size=len(content),
                    source=body.source_type + " intake",
                    captured_at=body.captured_at,
                )
                self.store.save(db, evidence, actor, body.reason, "evidence.uploaded")
                self.activate(db, iid, actor, body.reason)
            item = IntakeRecord(
                inspection_id=iid,
                case_id=body.case_id,
                evidence_id=evidence.id if evidence else None,
                uploader=actor,
                original_filename=filename,
                display_filename=filename,
                media_type=media,
                size_bytes=len(content),
                content_sha256=digest,
                storage_key=digest,
                source_type=body.source_type,
                source_id=body.source_id,
                captured_at=body.captured_at,
                synthetic_demo=body.synthetic_demo,
                asset_hint=body.asset_hint,
                physical_asset_id=body.physical_asset_id,
                metadata=body.model_dump(mode="json"),
                duplicate_of=duplicates[0].id if duplicates else None,
            )
            self.save(db, item, actor, body.reason, "uploaded_queued")
            self.service.receipt(db, actor, operation, retry_key, payload, item.id)
            return item

    def run_once(self):
        with self.store.transaction() as db:
            candidates = self.records(db)
            cutoff = (datetime.now(UTC) - timedelta(seconds=150)).isoformat()
            for item in candidates:
                if item.processing_status == "processing" and item.started_at and item.started_at < cutoff:
                    item.processing_status = "queued"
                    self.save(db, item, "Intake worker", "Recover interrupted processing lease", "recovered")
            item = next((r for r in candidates if r.processing_status == "queued"), None)
            if not item:
                return False
            item.processing_status, item.started_at = "processing", now()
            item.attempts += 1
            self.save(db, item, "Intake worker", "Claim durable processing job", "processing")
            version = item.version
            evidence = (
                self.store.get(db, Evidence, item.evidence_id, item.inspection_id)
                if item.evidence_id
                else None
            )
            cached = next(
                (
                    r
                    for r in candidates
                    if r.id != item.id
                    and r.inspection_id == item.inspection_id
                    and r.content_sha256 == item.content_sha256
                    and r.raw_result
                    and r.processing_status in {"needs_review", "linked", "rejected"}
                    and r.pipeline_version == item.pipeline_version
                ),
                None,
            )
        try:
            path = self.store.files / item.content_sha256
            if hashlib.sha256(path.read_bytes()).hexdigest() != item.content_sha256:
                raise ValueError("Original integrity check failed")
            if cached:
                raw = json.loads(json.dumps(cached.raw_result))
            else:
                directory = self.derived / item.id / str(item.attempts)
                process = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "app.intake_perception",
                        str(path),
                        item.media_type,
                        str(directory),
                        item.original_filename,
                    ],
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                if process.returncode or len(process.stdout) > 2 * 1024 * 1024:
                    raise ValueError("Media processing failed or exceeded its resource limit")
                raw = json.loads(process.stdout)
                if "error" in raw:
                    raise ValueError(raw["error"])
                raw["artifact"] = {"record_id": item.id, "attempt": item.attempts}
            if item.metadata.get("source_timestamp_seconds") is not None:
                for page in raw["pages"]:
                    page["timestamp"] = item.metadata["source_timestamp_seconds"]
            fields = extract_fields(raw["pages"])
            category, method = classify(raw.get("text", ""), item.media_type)
            with self.store.transaction() as db:
                current = self.get(db, item.id)
                check_version(current, version)
                current.raw_result = {
                    **raw,
                    "fields": fields,
                    "classification": {"category": category, "method": method},
                }
                current.category, current.classification_method = category, method
                current.cached_from = cached.id if cached else None
                current.resolution = resolve(
                    fields, self.store.list(db, Asset, item.inspection_id), item.asset_hint
                )
                current.processing_status, current.completed_at, current.last_error = (
                    "needs_review",
                    now(),
                    None,
                )
                current.display_filename = (category.replace("_", " ") + " · " + item.original_filename)[:240]
                if evidence is None and item.media_type.startswith("video/"):
                    evidence = Evidence(
                        inspection_id=item.inspection_id,
                        kind="other",
                        filename=item.original_filename,
                        media_type=item.media_type,
                        sha256=item.content_sha256,
                        byte_size=item.size_bytes,
                        source=item.source_type + " validated video intake",
                        captured_at=item.captured_at,
                    )
                    self.store.save(
                        db,
                        evidence,
                        "Intake worker",
                        "Validate video stream before team-readable evidence",
                        "evidence.uploaded",
                    )
                    current.evidence_id = evidence.id
                if evidence:
                    fresh = self.store.get(db, Evidence, evidence.id, item.inspection_id)
                    check_version(fresh, evidence.version)
                    fresh.text = raw.get("text", "")[:100000]
                    fresh.extraction_pages = [
                        {k: p[k] for k in ("page", "text", "method")} for p in raw["pages"]
                    ]
                    fresh.extraction_method, fresh.confirmed = raw["method"], False
                    fresh.kind = KINDS.get(category, "other")
                    fresh.quality_flags = [
                        f
                        for f in raw.get("flags", [])
                        if f in {"unreadable", "blurry", "incomplete", "duplicate_serial"}
                    ]
                    fresh.facts = Facts()  # Source-linked suggestions require a separate human acceptance.
                    self.store.save(
                        db,
                        fresh,
                        "Intake worker",
                        "Store unconfirmed source text; preserve original",
                        "evidence.extracted",
                    )
                    self.activate(db, item.inspection_id, "Intake worker", "Evidence extraction changed")
                self.save(
                    db,
                    current,
                    "Intake worker",
                    "Advisory classification and asset candidates; no evidence accepted",
                    "processed",
                )
        except Exception as exc:  # noqa: BLE001 -- every failed durable job must retain its source and state
            with self.store.transaction() as db:
                current = self.get(db, item.id)
                current.processing_status, current.completed_at = "failed", now()
                current.last_error = str(exc.detail if isinstance(exc, HTTPException) else exc)[:500]
                self.save(db, current, "Intake worker", "Processing failed; original retained", "failed")
        return True

    def acoustic_handoff(self, db, item, physical_id, actor, reason):
        binding = self.service.binding(db, item.case_id, physical_id, item.inspection_id)
        if item.assigned_asset_id and binding.local_asset_id != item.assigned_asset_id:
            raise HTTPException(422, "Confirmed physical identity differs from the reviewed asset")
        decoded = item.raw_result.get("audio")
        if not decoded:
            raise HTTPException(422, "Process and validate the audio original first")
        metadata = item.metadata
        body = AudioUpload(
            inspection_id=item.inspection_id,
            physical_asset_id=physical_id,
            capture_type=metadata.get("audio_purpose") or "machine_acoustic",
            captured_at=item.captured_at,
            device=metadata.get("device", "Intake upload"),
            operating_mode="unknown",
            note=metadata.get("capture_conditions", "Unknown capture conditions"),
            consent_confirmed=metadata.get("recording_authorized", False),
            consent_note="Authorized intake upload",
            synthetic=item.synthetic_demo,
            reason=reason,
        )
        audio = AudioRecording(
            case_id=item.case_id,
            filename=item.original_filename,
            sha256=item.content_sha256,
            byte_size=item.size_bytes,
            captured_by=actor,
            **decoded,
            **body.model_dump(exclude={"reason", "consent_confirmed"}),
        )
        self.service.save(db, audio, actor, reason, "v2.audio.uploaded")
        item.audio_recording_id, item.physical_asset_id = audio.id, physical_id
        item.assigned_asset_id, item.processing_status = binding.local_asset_id, "linked"
        item.reviewed_by, item.reviewed_at, item.review_reason = actor, now(), reason
        return audio
