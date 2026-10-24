"""Longitudinal records. Deliberately do not extend V1 evidence-basis models."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.models import Entity, Model, Short, Text, now

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Amount = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]


class Change(Model):
    reason: Text


class Revision(Change):
    version: int = Field(ge=1)


class Source(Model):
    kind: Literal["management_report", "analyst_observation", "submitted_document", "interview"]
    attribution: Short
    quote: Text
    segment_id: str | None = None
    segment_version: int | None = Field(default=None, ge=1)
    evidence_id: str | None = None
    locator: Short | None = None
    origin_group: Short | None = None


class Scoped(Entity):
    case_id: str
    updated_at: str = Field(default_factory=now)


class CaseCreate(Change):
    inspection_id: str
    company: Short
    site: Short
    timezone: Short = "Asia/Tokyo"


class CaseRecord(Entity):
    company: str
    site: str
    timezone: str = "Asia/Tokyo"
    synthetic: bool = True


class Membership(Scoped):
    pass


class EnrolInspection(Change):
    inspection_id: str


class PhysicalAssetCreate(Change):
    inspection_id: str
    local_asset_id: str
    identity_evidence_id: str
    identity_locator: Short
    manufacturer: Short | None = None


class PhysicalAsset(Scoped):
    label: str
    serial: str
    model: str
    manufacturer: str | None = None


class AssetBinding(Scoped):
    local_asset_id: str
    physical_asset_id: str
    identity_evidence_id: str
    identity_locator: str
    confirmed_by: str
    active: bool = True


class BindAsset(PhysicalAssetCreate):
    physical_asset_id: str


class AssetRole(Model):
    physical_asset_id: str
    role: Literal["existing", "replacement", "acquired", "supporting"]


class ProjectCreate(Change):
    inspection_id: str
    title: Short
    kind: Literal["replacement", "new_purchase", "repair", "upgrade", "expansion"]
    rationale: Text
    proposed_amount: Amount | None = None
    currency: Currency | None = None
    asset_links: list[AssetRole] = Field(default_factory=list, max_length=20)
    source: Source

    @model_validator(mode="after")
    def amount_currency(self):
        if self.proposed_amount is not None and self.currency is None:
            raise ValueError("Currency is required with an amount")
        ids = [item.physical_asset_id for item in self.asset_links]
        if len(ids) != len(set(ids)):
            raise ValueError("A physical asset may occur only once in a project")
        return self


class InvestmentProject(Scoped):
    title: str
    kind: str
    rationale: str
    proposed_amount: Decimal | None = None
    currency: str | None = None
    asset_links: list[AssetRole] = Field(default_factory=list)
    source: Source
    amount_source: Source | None = None
    stage: Literal["proposed", "evaluating", "in_progress", "outcome_review", "closed", "cancelled"] = (
        "proposed"
    )
    evidence_status: Literal["reported"] = "reported"


class ProjectUpdate(ProjectCreate, Revision):
    stage: Literal["proposed", "evaluating", "in_progress", "outcome_review", "closed", "cancelled"]


Metric = Literal["downtime_hours", "repair_cost", "output_rate", "defect_rate", "energy_consumption"]


class TargetCreate(Change):
    inspection_id: str
    metric: Metric
    unit: Short
    baseline_value: Decimal | None = Field(default=None, ge=0)
    baseline_period: Short | None = None
    target_type: Literal["absolute", "reduction_percent", "increase_percent"]
    target_value: Decimal = Field(ge=0)
    currency: Currency | None = None
    due_date: str | None = None
    relative_months: int | None = Field(default=None, ge=1, le=120)
    anchor: Literal["commissioning"] | None = None
    source: Source

    @model_validator(mode="after")
    def target_checks(self):
        if self.target_type == "reduction_percent" and self.target_value > 100:
            raise ValueError("A reduction target cannot exceed 100 percent")
        if self.metric == "repair_cost" and self.currency is None:
            raise ValueError("Repair-cost targets require a currency")
        if self.relative_months is not None and self.anchor is None:
            raise ValueError("Relative deadlines require a commissioning anchor")
        if self.relative_months is not None and self.due_date is not None:
            raise ValueError("Use a relative or absolute deadline, not both")
        if self.due_date:
            from datetime import date

            date.fromisoformat(self.due_date)
        return self


class InvestmentTarget(Scoped):
    project_id: str
    metric: Metric
    unit: str
    baseline_value: Decimal | None = None
    baseline_period: str | None = None
    target_type: str
    target_value: Decimal
    currency: str | None = None
    due_date: str | None = None
    relative_months: int | None = None
    anchor: str | None = None
    source: Source
    evidence_status: Literal["management_forecast"] = "management_forecast"


class TargetUpdate(TargetCreate, Revision):
    pass


class MeasurementSource(Model):
    evidence_id: str
    locator: Short
    quote: Text


class InvestmentReviewCreate(Change):
    inspection_id: str
    kind: Literal["purchase", "payment", "delivery", "installation", "commissioning", "outcome"]
    status: Literal[
        "reported", "supported", "contradicted", "unresolved", "not_yet_measurable", "inconclusive"
    ]
    target_id: str | None = None
    physical_asset_id: str | None = None
    measured_value: Decimal | None = Field(default=None, ge=0)
    unit: Short | None = None
    measurement_period: Short | None = None
    baseline_value: Decimal | None = Field(default=None, ge=0)
    baseline_period: Short | None = None
    currency: Currency | None = None
    comparable: bool = False
    methodology: Text
    baseline_source: MeasurementSource | None = None
    measurement_source: MeasurementSource | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    reviewed_date: str | None = None

    @model_validator(mode="after")
    def review_checks(self):
        if self.kind == "outcome" and not self.target_id:
            raise ValueError("Outcome review requires a target")
        if self.kind != "outcome" and self.target_id:
            raise ValueError("Only outcome reviews have a target")
        if self.status in ("not_yet_measurable", "unresolved") and self.measured_value is not None:
            raise ValueError("Unmeasured outcomes cannot contain a measured value")
        if self.reviewed_date:
            from datetime import date

            date.fromisoformat(self.reviewed_date)
        return self


class InvestmentReview(Scoped):
    project_id: str
    kind: str
    status: str
    target_id: str | None = None
    target_version: int | None = None
    physical_asset_id: str | None = None
    measured_value: Decimal | None = None
    unit: str | None = None
    measurement_period: str | None = None
    baseline_value: Decimal | None = None
    baseline_period: str | None = None
    currency: str | None = None
    comparable: bool = False
    methodology: str
    baseline_source: MeasurementSource | None = None
    measurement_source: MeasurementSource | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reviewed_date: str | None = None
    reviewed_by: str
    calculation: dict = Field(default_factory=dict)


class ClosureCreate(Change):
    inspection_id: str
    physical_asset_id: str | None = None
    claim_id: str | None = None
    project_id: str | None = None
    request: Text
    contact: Short
    reviewer: Short
    due_date: str
    priority: Literal["normal", "high"] = "normal"
    required_evidence: Text
    verification_method: Literal["document_review", "issuer_confirmation", "site_test", "site_inspection"]
    source: Source

    @field_validator("due_date")
    @classmethod
    def date_valid(cls, value):
        from datetime import date

        date.fromisoformat(value)
        return value


class FollowUpContext(Scoped):
    follow_up_id: str
    physical_asset_id: str | None = None
    project_id: str | None = None
    contact: str
    reviewer: str
    due_date: str
    priority: str
    required_evidence: str
    verification_method: str
    source: Source
    workflow_status: Literal[
        "open", "awaiting_information", "submitted_for_review", "needs_more_evidence", "closed"
    ] = "open"
    submitted_evidence_ids: list[str] = Field(default_factory=list)
    verified_evidence_ids: list[str] = Field(default_factory=list)
    verification_reason: str | None = None
    verified_by: str | None = None
    review_inspection_id: str | None = None


class ClosureTransition(Revision):
    status: Literal["open", "awaiting_information", "submitted_for_review", "needs_more_evidence", "closed"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    verification_supported: bool = False
    review_inspection_id: str | None = None


class ClosureEdit(ClosureCreate, Revision):
    pass


class InterviewCreate(Change):
    inspection_id: str
    physical_asset_id: str | None = None
    project_id: str | None = None
    speaker_label: Short
    speaker_confirmed: bool = False
    consent_confirmed: bool
    consent_note: Text
    synthetic: bool = True


class InterviewSession(Scoped):
    physical_asset_id: str | None = None
    project_id: str | None = None
    speaker_label: str
    speaker_confirmed: bool = False
    consent_confirmed: bool
    consent_note: str
    synthetic: bool = True


class SegmentCreate(Change):
    text: Text
    language: Literal["ja", "en"]
    english_translation: Text | None = None
    translation_origin: Literal["human", "provider"] | None = None
    recording_id: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)
    mode: Literal["manual", "prerecorded", "microphone_chunk", "synthetic_transcript"] = "manual"

    @model_validator(mode="after")
    def offsets(self):
        if self.recording_id:
            if self.start_ms is None or self.end_ms is None or self.start_ms >= self.end_ms:
                raise ValueError("Audio-linked segments need valid start/end offsets")
        elif self.start_ms is not None or self.end_ms is not None:
            raise ValueError("Manual text cannot have fabricated audio offsets")
        if self.mode in ("prerecorded", "microphone_chunk") and not self.recording_id:
            raise ValueError("Audio processing modes require an actual recording")
        if self.english_translation is not None and self.translation_origin is None:
            raise ValueError("Translation attribution is required")
        return self


class TranscriptSegment(Scoped):
    interview_id: str
    text: str
    language: str
    english_translation: str | None = None
    translation_origin: str | None = None
    recording_id: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    mode: str
    provider: str | None = None
    source_revision: int = 1
    final: bool = True
    provider_text: str | None = None
    provider_translation: str | None = None


class SegmentUpdate(SegmentCreate, Revision):
    pass


class Question(Model):
    topic: Literal[
        "identity",
        "purchase",
        "payment",
        "installation",
        "commissioning",
        "maintenance",
        "investment_target",
        "deadline",
        "other",
    ]
    question: Short
    why: Text
    proposed_evidence: Short
    priority: Literal["normal", "high"]
    source_quote: Text
    status: Literal["suggested", "asked", "dismissed"] = "suggested"


class CandidatePayload(Model):
    kind: Literal["reported_issue", "proposed_amount", "investment_target", "follow_up"]
    text: Text
    quote: Text
    metric: Metric | None = None
    value: Decimal | None = Field(default=None, ge=0)
    unit: Short | None = None
    currency: Currency | None = None
    target_type: Literal["absolute", "reduction_percent", "increase_percent"] | None = None
    due_date: str | None = None
    uncertainty: Text | None = None


class CopilotOutput(Model):
    questions: list[Question] = Field(max_length=3)
    candidates: list[CandidatePayload] = Field(max_length=6)


class CopilotAnalysis(Scoped):
    segment_id: str
    segment_version: int
    context_hash: str
    provider: str
    model: str
    questions: list[Question]
    candidate_ids: list[str]
    notices: list[str] = Field(default_factory=list)


class ExtractedCandidate(Scoped):
    segment_id: str
    segment_version: int
    physical_asset_id: str | None = None
    project_id: str | None = None
    payload: CandidatePayload
    review_status: Literal["pending", "accepted", "rejected", "stale"] = "pending"
    destination_id: str | None = None
    accepted_payload: CandidatePayload | None = None
    source_current: bool = True


class CandidateConfirmation(Revision):
    action: Literal["accept", "reject"]
    project_id: str | None = None
    project_version: int | None = Field(default=None, ge=1)
    edited: CandidatePayload | None = None
    confirmed_source: bool = False
    follow_up: ClosureCreate | None = None


class CandidateEdit(Revision):
    payload: CandidatePayload


class StatementRecord(Scoped):
    physical_asset_id: str | None = None
    requires_review: bool = False
    project_id: str | None = None
    text: str
    source: Source
    kind: str
    value: Decimal | None = None
    currency: str | None = None
    evidence_status: Literal["reported"] = "reported"


class AudioRecording(Scoped):
    speaker_label: str | None = None
    physical_asset_id: str | None = None
    field_session_id: str | None = None
    processing_state: str = "PERSISTED"
    processing_error: str | None = None
    capture_type: Literal["machine_acoustic", "interview_speech", "inspector_voice_note"]
    filename: str
    sha256: str
    byte_size: int
    media_type: str
    duration_seconds: float
    sample_rate: int
    channels: int
    captured_at: datetime
    captured_by: str
    device: str
    operating_mode: str
    load: str | None = None
    rpm: float | None = None
    microphone_distance_cm: float | None = None
    temperature_c: float | None = None
    humidity_percent: float | None = None
    background_noise: str | None = None
    signal_processing: str = "unknown"
    note: str
    consent_note: str
    share_with_judges: bool = False
    synthetic: bool = True
    quality_flags: list[str] = Field(default_factory=list)
    signal_features: dict = Field(default_factory=dict)


class AudioUpload(Model):
    speaker_label: Short | None = None
    inspection_id: str
    physical_asset_id: str | None = None
    field_session_id: str | None = None
    capture_type: Literal["machine_acoustic", "interview_speech", "inspector_voice_note"]
    captured_at: datetime
    device: Short
    operating_mode: Short
    load: Short | None = None
    rpm: float | None = Field(default=None, ge=0, le=100000)
    microphone_distance_cm: float | None = Field(default=None, ge=0, le=100000)
    temperature_c: float | None = Field(default=None, ge=-100, le=500)
    humidity_percent: float | None = Field(default=None, ge=0, le=100)
    background_noise: Short | None = None
    signal_processing: Literal["none_requested", "speech_enhancement", "unknown"] = "unknown"
    note: Text
    consent_confirmed: bool
    consent_note: Text
    share_with_judges: bool = False
    synthetic: bool = True
    reason: Text

    @model_validator(mode="after")
    def capture_checks(self):
        if self.capture_type == "machine_acoustic" and not self.physical_asset_id:
            raise ValueError("Machine acoustic recording requires a confirmed physical machine")
        from datetime import UTC

        if not self.captured_at.tzinfo or self.captured_at > datetime.now(UTC):
            raise ValueError("Capture timestamp must have a timezone and cannot be in the future")
        if not self.consent_confirmed:
            raise ValueError("Recording consent/authorization must be confirmed")
        if self.share_with_judges and not self.synthetic:
            raise ValueError("Only explicitly synthetic demo recordings can be shared with judges")
        return self


class AudioUpdate(Revision):
    physical_asset_id: str | None = None
    share_with_judges: bool
    note: Text


class AudioComparisonCreate(Change):
    first_id: str
    second_id: str


class AcousticComparison(Scoped):
    first_id: str
    first_version: int
    second_id: str
    second_version: int
    comparable: bool
    warnings: list[str]
    features: dict
    conclusion: str


class QuestionUpdate(Revision):
    index: int = Field(ge=0, le=2)
    status: Literal["asked", "dismissed"]


class AnalysisRequest(Change):
    allow_rule_fallback: bool = False


class TranslateRequest(Revision):
    pass


class TranscribeRequest(Change):
    interview_id: str
    language: Literal["ja", "en"] = "ja"
    mode: Literal["prerecorded", "microphone_chunk"] = "prerecorded"


class ReminderDelivery(Scoped):
    follow_up_id: str
    due_date: str
    recipient: str
    status: Literal["pending", "sent_to_test_inbox", "failed"]
    message_id: str
    error: str | None = None
    attempts: int = 0
    attempt_started_at: str | None = None


class ReminderRun(Change):
    retry_failed: bool = False
