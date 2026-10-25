"""Advisory intake metadata; existing Evidence, AudioRecording and audit remain authoritative."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.models import Entity, Facts, Model, Short, Text

Category = Literal[
    "commissioning_certificate",
    "technical_specification",
    "purchase_invoice",
    "purchase_order",
    "machine_nameplate",
    "inspection_report",
    "maintenance_record",
    "installation_evidence",
    "acoustic_recording",
    "other",
]


class IntakeUpload(Model):
    case_id: str
    inspection_id: str | None = None
    asset_hint: str | None = None
    physical_asset_id: str | None = None
    source_type: Literal["browser", "mobile", "camera", "folder"] = "browser"
    source_id: Short | None = None
    captured_at: datetime
    synthetic_demo: bool = False
    audio_purpose: Literal["machine_acoustic", "interview_speech"] | None = None
    recording_authorized: bool = False
    device: Short = "Uploaded file; device unspecified"
    capture_conditions: Text = "Capture conditions not recorded"
    reason: Text

    @field_validator("captured_at")
    @classmethod
    def valid_time(cls, value):
        if value.tzinfo is None or value > datetime.now(UTC):
            raise ValueError("Use a timezone-aware capture time that is not in the future")
        return value


class IntakeRecord(Entity):
    case_id: str | None = None
    evidence_id: str | None = None
    audio_recording_id: str | None = None
    uploader: str
    original_filename: str
    display_filename: str
    media_type: str
    size_bytes: int
    content_sha256: str
    storage_key: str
    source_type: str
    source_id: str | None = None
    captured_at: datetime
    synthetic_demo: bool = False
    asset_hint: str | None = None
    physical_asset_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    processing_status: Literal[
        "uploaded", "queued", "processing", "needs_review", "linked", "rejected", "failed"
    ] = "queued"
    pipeline_version: str = "intake-v1"
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    last_error: str | None = None
    duplicate_of: str | None = None
    cached_from: str | None = None
    raw_result: dict[str, Any] = Field(default_factory=dict)
    category: Category = "other"
    classification_method: str = "pending"
    resolution: dict[str, Any] = Field(default_factory=dict)
    assigned_asset_id: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_reason: str | None = None


class IntakeReview(Model):
    version: int = Field(ge=1)
    action: Literal["confirm", "reject", "unassign"]
    asset_id: str | None = None
    checked_original: bool = False
    acknowledge_conflicts: bool = False
    reason: Text


class IntakeDocumentReview(Model):
    version: int = Field(ge=1)
    evidence_version: int = Field(ge=1)
    category: Category
    facts: Facts
    checked_original: bool
    quality_flags: list[
        Literal["unreadable", "blurry", "duplicate_serial", "incomplete", "manual_correction"]
    ] = Field(default_factory=list)
    reason: Text
