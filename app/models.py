from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def now() -> str:
    return datetime.now(UTC).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class ClaimKind(StrEnum):
    identity = "identity"
    purchase = "purchase"
    payment = "payment"
    presence = "presence"
    installation = "installation"
    commissioning = "commissioning"


class Status(StrEnum):
    supported = "supported"
    partly_supported = "partly_supported"
    unresolved = "unresolved"
    potentially_inconsistent = "potentially_inconsistent"
    not_assessed = "not_assessed"


class EvidenceKind(StrEnum):
    equipment_register = "equipment_register"
    declared_asset = "declared_asset"
    invoice = "invoice"
    payment_extract = "payment_extract"
    site_image = "site_image"
    site_observation = "site_observation"
    installation_record = "installation_record"
    commissioning_certificate = "commissioning_certificate"
    financial_statement = "financial_statement"
    management_statement = "management_statement"
    operating_log = "operating_log"
    maintenance_record = "maintenance_record"
    production_record = "production_record"
    utility_record = "utility_record"


class Facts(Model):
    serial: Short | None = None
    model: Short | None = None
    site: Short | None = None
    invoice_ref: Short | None = None
    payment_ref: Short | None = None
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    present: bool | None = None
    installed: bool | None = None
    commissioned: bool | None = None
    condition: Literal["operating", "packaged", "idle", "unknown"] | None = None


class Entity(Model):
    id: str = Field(default_factory=lambda: str(uuid4()))
    inspection_id: str
    version: int = 1
    created_at: str = Field(default_factory=now)


class InspectionCreate(Model):
    name: Short
    site: Short
    reason: Text = "Inspection setup"


class Inspection(Entity):
    name: str
    site: str
    state: Literal["draft", "active", "review_complete"] = "draft"


class AssetCreate(Model):
    nameplate_metadata: dict[str, str | bool | None] = Field(default_factory=dict, max_length=24)
    tag: Short
    serial: Short
    model: Short
    site: Short
    invoice_ref: Short
    payment_ref: Short
    reason: Text = "Declared asset setup"


class AssetUpdate(AssetCreate):
    version: int = Field(ge=1)


class Asset(Entity):
    nameplate_metadata: dict[str, str | bool | None] = Field(default_factory=dict, max_length=24)
    tag: str
    serial: str
    model: str
    site: str
    invoice_ref: str
    payment_ref: str


class Claim(Entity):
    asset_id: str
    kind: ClaimKind
    expected: str
    confirmed: bool = False


class ClaimConfirmation(Model):
    expected: Short
    confirmed: bool
    version: int = Field(ge=1)
    reason: Text


class ExtractionPage(Model):
    page: int = Field(ge=1, le=12)
    text: Annotated[str, StringConstraints(max_length=100000)]
    method: Literal["pdf_text", "tesseract", "structured_text"]


class Evidence(Entity):
    kind: EvidenceKind
    filename: str
    media_type: str
    sha256: str
    byte_size: int
    source: str
    captured_at: datetime
    received_at: str = Field(default_factory=now)
    text: str = ""
    facts: Facts = Field(default_factory=Facts)
    quality_flags: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    confirmed: bool = False
    extraction_method: str = "pending"
    extraction_pages: list[ExtractionPage] = Field(default_factory=list)


class EvidenceCorrection(Model):
    version: int = Field(ge=1)
    text: Annotated[str, StringConstraints(max_length=100000)]
    facts: Facts
    quality_flags: list[
        Literal["unreadable", "blurry", "duplicate_serial", "incomplete", "manual_correction"]
    ]
    confidence: float | None = Field(default=None, ge=0, le=1)
    confirmed: bool
    reason: Text


class LinkCreate(Model):
    claim_id: str
    evidence_id: str
    relation: Literal["supports", "contradicts", "context"]
    locator: Short  # e.g. page 2, row 4, photo label plate
    reason: Text


class EvidenceLink(Entity):
    claim_id: str
    evidence_id: str
    relation: Literal["supports", "contradicts", "context"]
    locator: str
    active: bool = True


class LinkRetraction(Model):
    version: int = Field(ge=1)
    reason: Text


class ObservationCreate(Model):
    asset_id: str
    text: Text
    facts: Facts = Field(default_factory=Facts)
    source: Literal["analyst", "management"]
    captured_at: datetime
    reason: Text


class Observation(Entity):
    asset_id: str
    evidence_id: str
    text: str
    source: str


class Finding(Entity):
    claim_id: str
    computed_status: Status
    explanation: str
    next_best_action: str
    evidence_ids: list[str]
    basis_hash: str
    rule_version: str = "v1.1"
    reviewed_status: Status | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_reason: str | None = None


class FindingReview(Model):
    version: int = Field(ge=1)
    status: Status
    reason: Text


class FollowUpCreate(Model):
    claim_id: str
    request: Text
    reason: Text


class FollowUpAction(Entity):
    claim_id: str | None = None
    request: str
    state: Literal["open", "resolved"] = "open"
    resolution: str | None = None


class FollowUpUpdate(Model):
    version: int = Field(ge=1)
    state: Literal["open", "resolved"]
    resolution: Text
    reason: Text


class ReviewEvent(Model):
    id: str
    inspection_id: str
    entity_id: str
    action: str
    author: str
    time: str
    reason: str
    before: dict | None
    after: dict | None


class Reason(Model):
    reason: Text


class MissionItem(Model):
    asset_id: str
    tag: str
    checklist: list[str]


class Mission(Model):
    inspection_id: str
    items: list[MissionItem]


class Report(Model):
    schema_version: str = "1.0"
    generated_at: str = Field(default_factory=now)
    inspection: Inspection
    assets: list[Asset]
    claims: list[Claim]
    evidence: list[Evidence]
    evidence_links: list[EvidenceLink]
    findings: list[Finding]
    reconciliation_current: bool
    integrity_issues: list[str]
    finding_history: list[Finding]
    observations: list[Observation]
    follow_ups: list[FollowUpAction]
    review_events: list[ReviewEvent]
    scope: str = "Equipment/declared assets, invoices and payment extracts only. Financial statements are contextual; no underwriting or fraud conclusion. Synthetic demo data only."


class ExtractionRequest(Reason):
    force_ocr: bool = False
