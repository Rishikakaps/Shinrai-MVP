"""Authenticated media and interview ingestion; manual and provider paths share storage."""

import hashlib
from pathlib import Path
from typing import Annotated

from fastapi import Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.extraction import MAX_BYTES
from app.v2_media import compare_recordings, persist_original, process_audio
from app.v2_models import (
    AcousticComparison,
    AudioComparisonCreate,
    AudioRecording,
    AudioUpdate,
    AudioUpload,
    ExtractedCandidate,
    InterviewCreate,
    InterviewSession,
    InvestmentProject,
    SegmentCreate,
    SegmentUpdate,
    TranscribeRequest,
    TranscriptSegment,
    TranslateRequest,
)
from app.v2_providers import GeminiProvider
from app.v2_store import check_version


def authorize_audio(request, item):
    if request.state.principal["role"] != "analyst" and not (item.synthetic and item.share_with_judges):
        raise HTTPException(403, "This recording is restricted to analysts")


def audio_intact(store, item):
    path = store.files / item.sha256
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256:
        raise HTTPException(409, "Audio original integrity check failed")
    return path


def visible_audio(request, item):
    return request.state.principal["role"] == "analyst" or (item.synthetic and item.share_with_judges)


def check_segment_access(service, db, request, segment):
    if segment.recording_id:
        recording = service.get(db, AudioRecording, segment.recording_id, segment.case_id)
        authorize_audio(request, recording)


def stale_candidates(service, db, segment_id, case_id, actor, reason):
    for candidate in service.list(db, ExtractedCandidate, case_id):
        if candidate.segment_id == segment_id and candidate.review_status == "pending":
            candidate.review_status = "stale"
            service.save(db, candidate, actor, reason, "v2.candidate.source_invalidated")


def install_capture(router, app, service, authenticate):
    store = service.store
    Actor = Annotated[str, Depends(authenticate)]
    app.state.ai = GeminiProvider()

    @router.post("/cases/{case_id}/audio", response_model=AudioRecording, status_code=201)
    def upload_audio(
        case_id: str,
        actor: Actor,
        file: Annotated[UploadFile, File()],
        metadata: Annotated[str, Form(max_length=16000)],
        idempotency_key: Annotated[str, Header()],
    ):
        try:
            body = AudioUpload.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(
                422, "Audio metadata is invalid: " + "; ".join(e["msg"] for e in exc.errors())
            ) from exc
        content = file.file.read(MAX_BYTES + 1)
        content_hash = hashlib.sha256(content).hexdigest()
        filename = Path((file.filename or "audio").replace("\\", "/")).name[:200]
        payload = {"metadata": body.model_dump(mode="json"), "sha256": content_hash, "filename": filename}
        operation = "audio.upload:" + case_id
        with store.transaction(write=False) as db:
            service.binding(db, case_id, body.physical_asset_id, body.inspection_id)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, AudioRecording, previous, case_id)
        decoded = process_audio(content, filename, file.content_type or "")
        # Commit only references to fully persisted original bytes.
        digest = persist_original(store.files, content)
        with store.transaction() as db:
            service.binding(db, case_id, body.physical_asset_id, body.inspection_id)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, AudioRecording, previous, case_id)
            item = AudioRecording(
                case_id=case_id,
                filename=filename,
                sha256=digest,
                byte_size=len(content),
                captured_by=actor,
                **decoded,
                **body.model_dump(exclude={"reason", "consent_confirmed"}),
            )
            service.save(db, item, actor, body.reason, "v2.audio.uploaded")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.get("/cases/{case_id}/audio", response_model=list[AudioRecording])
    def audio_list(case_id: str, request: Request, physical_asset_id: str | None = None):
        with store.transaction(write=False) as db:
            if physical_asset_id:
                service.physical(db, case_id, physical_asset_id)
            return [
                a
                for a in service.list(db, AudioRecording, case_id)
                if (not physical_asset_id or a.physical_asset_id == physical_asset_id)
                and visible_audio(request, a)
            ]

    @router.get("/cases/{case_id}/audio/{recording_id}/original")
    def audio_original(case_id: str, recording_id: str, request: Request):
        with store.transaction(write=False) as db:
            item = service.get(db, AudioRecording, recording_id, case_id)
            authorize_audio(request, item)
            path = audio_intact(store, item)
        return FileResponse(
            path,
            media_type=item.media_type,
            filename=item.filename,
            content_disposition_type="inline",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.patch("/cases/{case_id}/audio/{recording_id}", response_model=AudioRecording)
    def audio_correction(case_id: str, recording_id: str, body: AudioUpdate, actor: Actor):
        with store.transaction() as db:
            item = service.get(db, AudioRecording, recording_id, case_id)
            check_version(item, body.version)
            service.binding(db, case_id, body.physical_asset_id, item.inspection_id)
            if body.share_with_judges and not item.synthetic:
                raise HTTPException(422, "Only synthetic recordings may be shared with judges")
            association_changed = item.physical_asset_id != body.physical_asset_id
            item.physical_asset_id, item.share_with_judges, item.note = (
                body.physical_asset_id,
                body.share_with_judges,
                body.note,
            )
            service.save(db, item, actor, body.reason, "v2.audio.association_or_metadata_corrected")
            if association_changed:
                for segment in service.list(db, TranscriptSegment, case_id):
                    if segment.recording_id == item.id:
                        stale_candidates(service, db, segment.id, case_id, actor, body.reason)
            return item

    @router.post("/cases/{case_id}/audio-comparisons", response_model=AcousticComparison, status_code=201)
    def audio_comparison(case_id: str, body: AudioComparisonCreate, actor: Actor):
        with store.transaction() as db:
            first = service.get(db, AudioRecording, body.first_id, case_id)
            second = service.get(db, AudioRecording, body.second_id, case_id)
            service.binding(db, case_id, first.physical_asset_id, first.inspection_id)
            service.binding(db, case_id, second.physical_asset_id, second.inspection_id)
            audio_intact(store, first)
            audio_intact(store, second)
            result = compare_recordings(first, second)
            item = AcousticComparison(
                case_id=case_id,
                inspection_id=second.inspection_id,
                first_id=first.id,
                first_version=first.version,
                second_id=second.id,
                second_version=second.version,
                **result,
            )
            return service.save(db, item, actor, body.reason, "v2.acoustic.compared")

    @router.get("/cases/{case_id}/audio-comparisons")
    def comparisons(case_id: str, request: Request):
        with store.transaction(write=False) as db:
            results = []
            for item in service.list(db, AcousticComparison, case_id):
                first = service.get(db, AudioRecording, item.first_id, case_id)
                second = service.get(db, AudioRecording, item.second_id, case_id)
                if visible_audio(request, first) and visible_audio(request, second):
                    results.append(
                        {
                            "comparison": item,
                            "current": first.version == item.first_version
                            and second.version == item.second_version,
                        }
                    )
            return results

    @router.post("/cases/{case_id}/interviews", response_model=InterviewSession, status_code=201)
    def interview_create(
        case_id: str, body: InterviewCreate, actor: Actor, idempotency_key: Annotated[str, Header()]
    ):
        if not body.consent_confirmed:
            raise HTTPException(422, "Confirm interview consent/authorization")
        payload, operation = body.model_dump(mode="json"), "interview.create:" + case_id
        with store.transaction() as db:
            service.binding(db, case_id, body.physical_asset_id, body.inspection_id)
            if body.project_id:
                service.get(db, InvestmentProject, body.project_id, case_id)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, InterviewSession, previous, case_id)
            item = InterviewSession(case_id=case_id, **body.model_dump(exclude={"reason"}))
            service.save(db, item, actor, body.reason, "v2.interview.created")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    def segment_refs(db, case_id, interview, body):
        service.binding(db, case_id, interview.physical_asset_id, interview.inspection_id)
        if body.recording_id:
            recording = service.get(db, AudioRecording, body.recording_id, case_id)
            if (
                recording.inspection_id != interview.inspection_id
                or recording.physical_asset_id != interview.physical_asset_id
            ):
                raise HTTPException(422, "Recording belongs to a different interview context")
            if recording.capture_type == "machine_acoustic":
                raise HTTPException(
                    422, "A machine-acoustic sample cannot be represented as an interview source"
                )
            if body.end_ms > recording.duration_seconds * 1000 + 1:
                raise HTTPException(422, "Transcript offsets exceed the original recording")
            audio_intact(store, recording)

    @router.post(
        "/cases/{case_id}/interviews/{interview_id}/segments",
        response_model=TranscriptSegment,
        status_code=201,
    )
    def segment_create(
        case_id: str,
        interview_id: str,
        body: SegmentCreate,
        actor: Actor,
        idempotency_key: Annotated[str, Header()],
    ):
        if body.translation_origin == "provider" or body.mode in {"prerecorded", "microphone_chunk"}:
            raise HTTPException(
                422, "Use the actual transcription/translation endpoints for provider-generated content"
            )
        payload, operation = body.model_dump(mode="json"), "segment.create:" + interview_id
        with store.transaction() as db:
            interview = service.get(db, InterviewSession, interview_id, case_id)
            segment_refs(db, case_id, interview, body)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, TranscriptSegment, previous, case_id)
            item = TranscriptSegment(
                case_id=case_id,
                inspection_id=interview.inspection_id,
                interview_id=interview.id,
                **body.model_dump(exclude={"reason"}),
            )
            service.save(db, item, actor, body.reason, "v2.transcript.segment_saved")
            service.receipt(db, actor, operation, idempotency_key, payload, item.id)
            return item

    @router.get("/cases/{case_id}/interviews/{interview_id}/segments", response_model=list[TranscriptSegment])
    def segment_list(case_id: str, interview_id: str, request: Request):
        with store.transaction(write=False) as db:
            service.get(db, InterviewSession, interview_id, case_id)
            results = []
            for item in service.list(db, TranscriptSegment, case_id):
                if item.interview_id == interview_id:
                    if item.recording_id and not visible_audio(
                        request, service.get(db, AudioRecording, item.recording_id, case_id)
                    ):
                        continue
                    results.append(item)
            return results

    @router.get("/cases/{case_id}/segments/{segment_id}", response_model=TranscriptSegment)
    def segment_get(case_id: str, segment_id: str, request: Request):
        with store.transaction(write=False) as db:
            item = service.get(db, TranscriptSegment, segment_id, case_id)
            check_segment_access(service, db, request, item)
            return item

    @router.patch("/cases/{case_id}/segments/{segment_id}", response_model=TranscriptSegment)
    def segment_edit(case_id: str, segment_id: str, body: SegmentUpdate, actor: Actor):
        if body.translation_origin == "provider":
            raise HTTPException(422, "Edited translations must be attributed to a human")
        with store.transaction() as db:
            item = service.get(db, TranscriptSegment, segment_id, case_id)
            check_version(item, body.version)
            interview = service.get(db, InterviewSession, item.interview_id, case_id)
            segment_refs(db, case_id, interview, body)
            if body.mode in {"microphone_chunk", "prerecorded"} and body.mode != item.mode:
                raise HTTPException(422, "Manual edits cannot fabricate a provider/capture mode")
            for field, value in body.model_dump(exclude={"reason", "version"}).items():
                setattr(item, field, value)
            item.source_revision += 1
            service.save(db, item, actor, body.reason, "v2.transcript.analyst_corrected")
            stale_candidates(service, db, item.id, case_id, actor, body.reason)
            return item

    @router.post("/cases/{case_id}/segments/{segment_id}/translate", response_model=TranscriptSegment)
    def translate_segment(case_id: str, segment_id: str, body: TranslateRequest, actor: Actor):
        with store.transaction(write=False) as db:
            item = service.get(db, TranscriptSegment, segment_id, case_id)
            check_version(item, body.version)
            if item.language != "ja":
                raise HTTPException(422, "This endpoint translates Japanese originals to English")
        translated = app.state.ai.translate(item.text)
        with store.transaction() as db:
            fresh = service.get(db, TranscriptSegment, segment_id, case_id)
            check_version(fresh, body.version)
            fresh.english_translation, fresh.translation_origin = translated, "provider"
            fresh.provider = app.state.ai.name
            fresh.source_revision += 1
            service.save(db, fresh, actor, body.reason, "v2.transcript.translated")
            stale_candidates(service, db, fresh.id, case_id, actor, body.reason)
            return fresh

    @router.post(
        "/cases/{case_id}/audio/{recording_id}/transcribe", response_model=TranscriptSegment, status_code=201
    )
    def transcribe(
        case_id: str,
        recording_id: str,
        body: TranscribeRequest,
        actor: Actor,
        idempotency_key: Annotated[str, Header()],
    ):
        payload, operation = body.model_dump(mode="json"), "audio.transcribe:" + recording_id
        with store.transaction(write=False) as db:
            item = service.get(db, AudioRecording, recording_id, case_id)
            interview = service.get(db, InterviewSession, body.interview_id, case_id)
            service.binding(db, case_id, item.physical_asset_id, item.inspection_id)
            if item.capture_type == "machine_acoustic" or "silence_or_very_low_signal" in item.quality_flags:
                raise HTTPException(422, "No usable interview speech source selected")
            if (
                interview.inspection_id != item.inspection_id
                or interview.physical_asset_id != item.physical_asset_id
            ):
                raise HTTPException(422, "Recording does not match this interview's confirmed machine")
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, TranscriptSegment, previous, case_id)
            path = audio_intact(store, item)
        text, translation = app.state.ai.transcribe(path, item.filename, item.media_type, body.language)
        with store.transaction() as db:
            fresh = service.get(db, AudioRecording, recording_id, case_id)
            check_version(fresh, item.version)
            previous = service.retry(db, actor, operation, idempotency_key, payload)
            if previous:
                return service.get(db, TranscriptSegment, previous, case_id)
            service.binding(db, case_id, item.physical_asset_id, item.inspection_id)
            segment = TranscriptSegment(
                case_id=case_id,
                inspection_id=item.inspection_id,
                interview_id=interview.id,
                text=text,
                language=body.language,
                english_translation=translation,
                translation_origin="provider" if translation else None,
                recording_id=item.id,
                start_ms=0,
                end_ms=int(item.duration_seconds * 1000),
                mode=body.mode,
                provider=app.state.ai.name,
            )
            service.save(db, segment, actor, body.reason, "v2.transcript.provider_segment_saved")
            service.receipt(db, actor, operation, idempotency_key, payload, segment.id)
            return segment
