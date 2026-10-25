"""V2 shares the V1 typed store, transactions and immutable audit ledger.

Relational indexes enforce case membership, physical associations and retry identity.
No extra fields enter the V1 engine's evidence basis.
"""

import hashlib
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from app import engine
from app.models import Asset, Claim, Evidence, FollowUpAction, Inspection, now
from app.v2_models import (
    AssetBinding,
    CaseRecord,
    ClosureTransition,
    FollowUpContext,
    InvestmentProject,
    Membership,
    PhysicalAsset,
    Source,
    TranscriptSegment,
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def check_version(item, version):
    if item.version != version:
        raise HTTPException(409, "Stale version; reload before saving")


class V2Store:
    def __init__(self, store):
        self.store = store
        prefix = "cdi." if store.backend == "postgres" else ""
        self.members = prefix + "v2_memberships"
        self.index = prefix + "v2_case_objects"
        self.bindings = prefix + "v2_bindings"
        self.retries = prefix + "v2_idempotency"
        self.migrations = prefix + "schema_migrations"
        objects = store.objects_table
        statements = [
            f"CREATE TABLE IF NOT EXISTS {self.migrations} (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)",
            f"""CREATE TABLE IF NOT EXISTS {self.members} (
                inspection_id TEXT PRIMARY KEY REFERENCES {objects}(id),
                case_id TEXT NOT NULL REFERENCES {objects}(id),
                membership_id TEXT NOT NULL UNIQUE REFERENCES {objects}(id))""",
            f"""CREATE TABLE IF NOT EXISTS {self.index} (
                object_id TEXT PRIMARY KEY REFERENCES {objects}(id),
                case_id TEXT NOT NULL REFERENCES {objects}(id), kind TEXT NOT NULL)""",
            f"CREATE INDEX IF NOT EXISTS v2_case_scope ON {self.index}(case_id,kind)",
            f"""CREATE TABLE IF NOT EXISTS {self.bindings} (
                binding_id TEXT PRIMARY KEY REFERENCES {objects}(id),
                case_id TEXT NOT NULL REFERENCES {objects}(id),
                inspection_id TEXT NOT NULL REFERENCES {objects}(id),
                local_asset_id TEXT NOT NULL REFERENCES {objects}(id),
                physical_asset_id TEXT NOT NULL REFERENCES {objects}(id),
                active INTEGER NOT NULL CHECK(active IN (0,1)))""",
            f"CREATE UNIQUE INDEX IF NOT EXISTS v2_active_local ON {self.bindings}(local_asset_id) WHERE active=1",
            f"CREATE UNIQUE INDEX IF NOT EXISTS v2_active_visit ON {self.bindings}(physical_asset_id,inspection_id) WHERE active=1",
            f"""CREATE TABLE IF NOT EXISTS {self.retries} (
                actor TEXT NOT NULL, operation TEXT NOT NULL, retry_key TEXT NOT NULL,
                request_hash TEXT NOT NULL, result_id TEXT NOT NULL REFERENCES {objects}(id),
                PRIMARY KEY(actor,operation,retry_key))""",
        ]
        with store.transaction() as db:
            for sql in statements:
                store.execute(db, sql)
            store.execute(
                db,
                f"INSERT INTO {self.migrations}(version,applied_at) VALUES (?,?) ON CONFLICT(version) DO NOTHING",
                (2, now()),
            )
            if store.backend == "sqlite":
                current = db.execute("PRAGMA user_version").fetchone()[0]
                if current > 2:
                    raise RuntimeError("Database schema is newer than this application")
                db.execute("PRAGMA user_version=2")

    def get_case(self, db, case_id):
        return self.store.get(db, CaseRecord, case_id)

    def require_visit(self, db, case_id, inspection_id):
        self.get_case(db, case_id)
        self.store.get(db, Inspection, inspection_id, inspection_id)
        row = self.store.execute(
            db, f"SELECT case_id FROM {self.members} WHERE inspection_id=?", (inspection_id,)
        ).fetchone()
        if not row or row["case_id"] != case_id:
            raise HTTPException(404, "Inspection is not a member of this case")

    def case_for_visit(self, db, inspection_id):
        row = self.store.execute(
            db, f"SELECT case_id FROM {self.members} WHERE inspection_id=?", (inspection_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Inspection has not been enrolled in a V2 case")
        return row["case_id"]

    def get(self, db, cls, identifier, case_id):
        item = self.store.get(db, cls, identifier)
        if getattr(item, "case_id", item.id) != case_id:
            raise HTTPException(404, "Record is outside this case")
        return item

    def list(self, db, cls, case_id):
        self.get_case(db, case_id)
        rows = self.store.execute(
            db,
            f"SELECT object_id FROM {self.index} WHERE case_id=? AND kind=? ORDER BY object_id",
            (case_id, cls.__name__),
        ).fetchall()
        return sorted(
            [self.get(db, cls, r["object_id"], case_id) for r in rows], key=lambda r: (r.created_at, r.id)
        )

    def save(self, db, item, actor, reason, action):
        if hasattr(item, "updated_at"):
            item.updated_at = now()
        self.store.save(db, item, actor, reason, action)
        case_id = getattr(item, "case_id", item.id)
        self.store.execute(
            db,
            f"INSERT INTO {self.index}(object_id,case_id,kind) VALUES (?,?,?) ON CONFLICT(object_id) DO NOTHING",
            (item.id, case_id, type(item).__name__),
        )
        return item

    def enrol(self, db, case, inspection_id, actor, reason):
        self.store.get(db, Inspection, inspection_id, inspection_id)
        previous = self.store.execute(
            db, f"SELECT * FROM {self.members} WHERE inspection_id=?", (inspection_id,)
        ).fetchone()
        if previous:
            if previous["case_id"] != case.id:
                raise HTTPException(409, "Inspection already belongs to another case")
            return self.get(db, Membership, previous["membership_id"], case.id)
        item = Membership(inspection_id=inspection_id, case_id=case.id)
        self.save(db, item, actor, reason, "v2.inspection.enrolled")
        self.store.execute(
            db,
            f"INSERT INTO {self.members}(inspection_id,case_id,membership_id) VALUES (?,?,?)",
            (inspection_id, case.id, item.id),
        )
        return item

    @staticmethod
    def timezone(value):
        try:
            return ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise HTTPException(422, "Use a valid IANA timezone") from exc

    def evidence(self, db, evidence_id, case_id, accepted=False):
        item = self.store.get(db, Evidence, evidence_id)
        self.require_visit(db, case_id, item.inspection_id)
        if not engine.intact(self.store, item):
            raise HTTPException(409, "Original evidence integrity failed")
        if accepted and (
            not item.confirmed
            or item.kind in ("management_statement", "financial_statement")
            or {"unreadable", "blurry", "incomplete", "duplicate_serial"}.intersection(item.quality_flags)
        ):
            raise HTTPException(422, "Sufficient accepted non-context evidence is required")
        return item

    def validate_source(self, db, source: Source, case_id):
        if source.segment_id:
            segment = self.get(db, TranscriptSegment, source.segment_id, case_id)
            if source.segment_version != segment.version:
                raise HTTPException(409, "Source transcript changed; review its current revision")
            text = segment.text + "\n" + (segment.english_translation or "")
            if source.quote not in text:
                raise HTTPException(422, "Quoted source span is not present in the transcript")
        if source.evidence_id:
            self.evidence(db, source.evidence_id, case_id)
        if source.kind == "submitted_document" and (not source.evidence_id or not source.locator):
            raise HTTPException(422, "Document sources require an original and locator")
        if source.kind == "interview" and not source.segment_id:
            raise HTTPException(422, "Interview sources require a stored source segment")

    def physical(self, db, case_id, physical_id, inspection_id=None):
        item = self.get(db, PhysicalAsset, physical_id, case_id)
        if inspection_id is not None:
            self.binding(db, case_id, physical_id, inspection_id)
        return item

    def binding(self, db, case_id, physical_id, inspection_id):
        self.require_visit(db, case_id, inspection_id)
        row = self.store.execute(
            db,
            f"SELECT binding_id FROM {self.bindings} WHERE case_id=? AND physical_asset_id=? AND inspection_id=? AND active=1",
            (case_id, physical_id, inspection_id),
        ).fetchone()
        if not row:
            raise HTTPException(422, "Confirm this machine's identity in this inspection before capture")
        binding = self.get(db, AssetBinding, row["binding_id"], case_id)
        evidence = self.evidence(db, binding.identity_evidence_id, case_id, accepted=True)
        asset = self.store.get(db, Asset, binding.local_asset_id, inspection_id)
        if not all(
            engine.norm(getattr(evidence.facts, k)) == engine.norm(getattr(asset, k))
            for k in ("serial", "model", "site")
        ):
            raise HTTPException(409, "Identity source changed; review and re-establish this binding")
        return binding

    def confirm_identity(self, db, case_id, body, actor, physical=None):
        self.require_visit(db, case_id, body.inspection_id)
        asset = self.store.get(db, Asset, body.local_asset_id, body.inspection_id)
        if asset.nameplate_metadata and (asset.serial or "").startswith("UNVERIFIED-"):
            raise HTTPException(
                422,
                "This source has no verified serial. Review and correct the declaration before establishing physical identity.",
            )
        if not asset.serial:
            raise HTTPException(422, "Record a reviewed serial before confirming physical identity")
        ev = self.evidence(db, body.identity_evidence_id, case_id, accepted=True)
        if ev.inspection_id != body.inspection_id:
            raise HTTPException(422, "Identity must be established using this visit's evidence")
        if not all(
            engine.norm(getattr(ev.facts, key)) == engine.norm(getattr(asset, key))
            for key in ("serial", "model", "site")
        ):
            raise HTTPException(422, "Identity evidence must match serial, model and site")
        if (
            sum(
                engine.norm(a.serial) == engine.norm(asset.serial)
                for a in self.store.list(db, Asset, asset.inspection_id)
            )
            != 1
        ):
            raise HTTPException(409, "Duplicate serial identity needs clarification before association")
        if physical and (
            engine.norm(physical.serial) != engine.norm(asset.serial)
            or engine.norm(physical.model) != engine.norm(asset.model)
        ):
            raise HTTPException(
                422, "Replacement or conflicting machine requires a distinct physical identity"
            )
        if self.store.execute(
            db, f"SELECT binding_id FROM {self.bindings} WHERE local_asset_id=? AND active=1", (asset.id,)
        ).fetchone():
            raise HTTPException(409, "This inspection asset already has a confirmed identity")
        if not physical:
            if any(
                engine.norm(p.serial) == engine.norm(asset.serial)
                for p in self.list(db, PhysicalAsset, case_id)
            ):
                raise HTTPException(
                    409,
                    "This serial already exists in the case; confirm or clarify its physical identity instead of creating a duplicate",
                )
            physical = PhysicalAsset(
                inspection_id=body.inspection_id,
                case_id=case_id,
                label=asset.tag,
                serial=asset.serial,
                model=asset.model,
                manufacturer=body.manufacturer,
            )
            self.save(db, physical, actor, body.reason, "v2.physical_asset.created")
        elif self.store.execute(
            db,
            f"SELECT binding_id FROM {self.bindings} WHERE physical_asset_id=? AND inspection_id=? AND active=1",
            (physical.id, asset.inspection_id),
        ).fetchone():
            raise HTTPException(409, "This physical machine is already associated in this visit")
        binding = AssetBinding(
            inspection_id=asset.inspection_id,
            case_id=case_id,
            local_asset_id=asset.id,
            physical_asset_id=physical.id,
            identity_evidence_id=ev.id,
            identity_locator=body.identity_locator,
            confirmed_by=actor,
        )
        self.save(db, binding, actor, body.reason, "v2.asset_identity.confirmed")
        self.store.execute(
            db,
            f"INSERT INTO {self.bindings}(binding_id,case_id,inspection_id,local_asset_id,physical_asset_id,active) VALUES (?,?,?,?,?,1)",
            (binding.id, case_id, asset.inspection_id, asset.id, physical.id),
        )
        return physical, binding

    def project_refs(self, db, case_id, body):
        self.require_visit(db, case_id, body.inspection_id)
        self.validate_source(db, body.source, case_id)
        for link in body.asset_links:
            self.physical(db, case_id, link.physical_asset_id)

    def follow_context(self, db, case_id, follow_up_id):
        return next(
            (c for c in self.list(db, FollowUpContext, case_id) if c.follow_up_id == follow_up_id), None
        )

    def create_follow_up(self, db, case_id, body, actor):
        self.require_visit(db, case_id, body.inspection_id)
        binding = (
            self.binding(db, case_id, body.physical_asset_id, body.inspection_id)
            if body.physical_asset_id
            else None
        )
        if not binding and (body.claim_id or not body.project_id):
            raise HTTPException(
                422, "A case/project request needs a project; machine claims need confirmed identity"
            )
        self.validate_source(db, body.source, case_id)
        if body.reviewer not in self.analysts:
            raise HTTPException(422, "Choose a configured analyst identity as reviewer")
        if body.claim_id:
            claim = self.store.get(db, Claim, body.claim_id, body.inspection_id)
            if claim.asset_id != binding.local_asset_id:
                raise HTTPException(422, "Claim belongs to another physical asset")
        if body.project_id:
            self.get(db, InvestmentProject, body.project_id, case_id)
        task = FollowUpAction(inspection_id=body.inspection_id, claim_id=body.claim_id, request=body.request)
        self.store.save(db, task, actor, body.reason, "follow_up.created")
        context = FollowUpContext(
            inspection_id=body.inspection_id,
            case_id=case_id,
            follow_up_id=task.id,
            **body.model_dump(exclude={"inspection_id", "claim_id", "request", "reason"}),
        )
        self.save(db, context, actor, body.reason, "v2.follow_up.details_created")
        return task, context

    def transition(self, db, case_id, follow_up_id, body: ClosureTransition, actor):
        context = self.follow_context(db, case_id, follow_up_id)
        if context is None:
            raise HTTPException(404, "Enhanced follow-up not found")
        check_version(context, body.version)
        task = self.store.get(db, FollowUpAction, follow_up_id, context.inspection_id)
        allowed = {
            "open": {"awaiting_information", "submitted_for_review"},
            "awaiting_information": {"submitted_for_review"},
            "submitted_for_review": {"needs_more_evidence", "closed"},
            "needs_more_evidence": {"awaiting_information", "submitted_for_review"},
            "closed": {"open"},
        }
        if body.status not in allowed[context.workflow_status]:
            raise HTTPException(409, "Invalid follow-up transition")
        review_iid = body.review_inspection_id or context.review_inspection_id or context.inspection_id
        if context.physical_asset_id:
            self.binding(db, case_id, context.physical_asset_id, review_iid)
        else:
            self.require_visit(db, case_id, review_iid)
        for evidence_id in body.evidence_ids:
            self.evidence(db, evidence_id, case_id)
        if body.status == "submitted_for_review":
            if not body.evidence_ids:
                raise HTTPException(422, "Submit stored evidence before requesting review")
            context.submitted_evidence_ids = list(dict.fromkeys(body.evidence_ids))
            context.review_inspection_id = review_iid
            context.verified_evidence_ids = []
            context.verified_by = context.verification_reason = None
        if body.status == "closed":
            if actor != context.reviewer:
                raise HTTPException(403, "Only the assigned analyst reviewer may close this request")
            if not body.verification_supported:
                raise HTTPException(422, "Explicit verification of the underlying requirement is required")
            ids = body.evidence_ids or context.submitted_evidence_ids
            if not ids or not set(ids).issubset(context.submitted_evidence_ids):
                raise HTTPException(422, "Review the evidence submitted for this request")
            for evidence_id in ids:
                self.evidence(db, evidence_id, case_id, accepted=True)
            if task.claim_id:
                original_claim = self.store.get(db, Claim, task.claim_id, task.inspection_id)
                local = self.binding(db, case_id, context.physical_asset_id, review_iid)
                relevant = [
                    c
                    for c in self.store.list(db, Claim, review_iid)
                    if c.asset_id == local.local_asset_id and c.kind == original_claim.kind
                ]
                findings = engine.current_findings(self.store, db, review_iid)
                if not relevant or not any(
                    f.claim_id == relevant[0].id
                    and f.computed_status == "supported"
                    and f.reviewed_status == "supported"
                    and f.reviewed_by
                    and set(f.evidence_ids).intersection(ids)
                    for f in findings
                ):
                    raise HTTPException(409, "Underlying claim is not currently supported and reviewed")
            context.verified_evidence_ids = list(ids)
            context.verified_by = actor
            context.verification_reason = body.reason
            context.review_inspection_id = review_iid
        if body.status == "open":
            context.verified_by = context.verification_reason = None
            context.verified_evidence_ids = []
        context.workflow_status = body.status
        task.state = "resolved" if body.status == "closed" else "open"
        task.resolution = body.reason
        self.store.save(db, task, actor, body.reason, "follow_up.updated")
        self.save(db, context, actor, body.reason, "v2.follow_up.transitioned")
        return task, context

    def due(self, db, case_id):
        case = self.get_case(db, case_id)
        today = datetime.now(self.timezone(case.timezone)).date()
        contexts = [c for c in self.list(db, FollowUpContext, case_id) if c.workflow_status != "closed"]
        return [
            {
                "task": self.store.get(db, FollowUpAction, c.follow_up_id),
                "details": c,
                "overdue": date.fromisoformat(c.due_date) < today,
                "due_today": date.fromisoformat(c.due_date) == today,
            }
            for c in contexts
        ]

    def retry(self, db, actor, operation, key, payload):
        if not key or len(key) > 128:
            raise HTTPException(422, "An Idempotency-Key of 1–128 characters is required")
        row = self.store.execute(
            db,
            f"SELECT * FROM {self.retries} WHERE actor=? AND operation=? AND retry_key=?",
            (actor, operation, key),
        ).fetchone()
        if row and row["request_hash"] != fingerprint(payload):
            raise HTTPException(409, "Idempotency key was already used with different input")
        return row["result_id"] if row else None

    def receipt(self, db, actor, operation, key, payload, result_id):
        self.store.execute(
            db,
            f"INSERT INTO {self.retries}(actor,operation,retry_key,request_hash,result_id) VALUES (?,?,?,?,?)",
            (actor, operation, key, fingerprint(payload), result_id),
        )
