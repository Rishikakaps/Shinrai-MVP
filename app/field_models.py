"""Device-independent field sessions and reviewed capture records in the V2 store."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import Field, field_validator

from app.models import Model, Short, Text
from app.v2_models import Change, Revision, Scoped

Purpose = Literal["identifier", "interview", "machine_acoustic", "documentary"]


class FieldSessionCreate(Change):
    inspection_id: str
    purpose: Purpose
    device: Short
    intended_asset_id: str | None = None
    physical_asset_id: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    expected_manufacturer: Short | None = None


class FieldSession(Scoped):
    purpose: Purpose
    device: str
    owner: str
    intended_asset_id: str | None = None
    physical_asset_id: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    expected_manufacturer: str | None = None
    state: Literal["CREATED", "CONNECTED", "INTERRUPTED", "CLOSED"] = "CREATED"


class SessionTransition(Revision):
    state: Literal["CONNECTED", "INTERRUPTED", "CLOSED"]


class CaptureInput(Change):
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def capture_time(cls, value):
        if value.tzinfo is None or value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Capture time must include a timezone and not be in the future")
        return value


class IdentifierFields(Model):
    serial: Short | None = None
    model: Short | None = None
    site: Short | None = None
    manufacturer: Short | None = None


class VisualCapture(Scoped):
    session_id: str
    evidence_id: str
    evidence_version: int
    intended_asset_id: str | None = None
    asset_version: int | None = None
    physical_asset_id: str | None = None
    state: Literal[
        "PERSISTED", "NEEDS_RESCAN", "NEEDS_REVIEW", "PROCESSING_FAILED", "ACCEPTED", "REJECTED"
    ] = "PERSISTED"
    raw_result: dict[str, Any] = Field(default_factory=dict)
    comparison: dict[str, Any] = Field(default_factory=dict)
    working_fields: IdentifierFields = Field(default_factory=IdentifierFields)
    reviewed_by: str | None = None
    review_reason: str | None = None
    captured_at: datetime
    received_at: str
    error: str | None = None


class CaptureReview(Revision):
    action: Literal["accept", "reject", "rescan", "correct"]
    fields: IdentifierFields = Field(default_factory=IdentifierFields)
    checked_original: bool = False
    acknowledge_conflicts: bool = False
    intended_asset_id: str | None = None


class DocumentaryInput(Change):
    inspection_id: str
    project_id: str | None = None
    proposition: Text
    verification_plan: Text
    declared_quantity: int = Field(ge=1, le=1000000)
    supported_quantity: int | None = Field(default=None, ge=0, le=1000000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    locator: Text
    status: Literal["DOCUMENTARILY_SUPPORTED", "PARTIALLY_SUPPORTED", "INCONCLUSIVE", "DISCREPANCY"]
    checked_originals: bool


class DocumentaryReview(Scoped):
    project_id: str | None = None
    proposition: str
    verification_plan: str
    declared_quantity: int
    supported_quantity: int | None = None
    evidence_versions: dict[str, int]
    locator: str
    status: str
    reviewed_by: str
    review_reason: str
    verification_basis: Literal["DOCUMENTARY"] = "DOCUMENTARY"
