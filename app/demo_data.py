"""Create a separate, clearly synthetic Plant A trial. Never reset an existing inspection."""

import hashlib
import io
from datetime import UTC, datetime
from uuid import uuid4

from reportlab.pdfgen import canvas

from app import engine
from app.models import (
    Asset,
    Claim,
    ClaimKind,
    Evidence,
    EvidenceKind,
    EvidenceLink,
    Facts,
    FollowUpAction,
    Inspection,
    Observation,
    now,
)


def certificate_pdf(asset):
    stream = io.BytesIO()
    page = canvas.Canvas(stream, pagesize=(600, 800))
    page.setTitle("SYNTHETIC commissioning certificate — demo only")
    page.setFont("Helvetica-Bold", 16)
    page.drawString(35, 750, "SYNTHETIC DEMO — NOT AN OEM DOCUMENT")
    page.setFont("Helvetica", 14)
    for index, line in enumerate(
        [f"serial: {asset.serial}", f"model: {asset.model}", f"site: {asset.site}", "commissioned: true"]
    ):
        page.drawString(35, 690 - index * 30, line)
    page.save()
    return stream.getvalue()


def prepare_trial(store, actor):
    reason = "Create a separate synthetic Plant A trial; sample declarations and evidence reviewed"
    iid = str(uuid4())
    inspection = Inspection(
        id=iid,
        inspection_id=iid,
        name=f"Plant A trial · {now()[:16]} · {iid[:4]}",
        site="Plant A",
        state="active",
    )
    with store.transaction() as db:
        store.save(db, inspection, actor, reason, "inspection.synthetic_trial_created")
        for number in range(1, 4):
            asset = Asset(
                inspection_id=iid,
                tag=f"CNC-{number:03d}",
                serial=f"SYN-{number:03d}",
                model="DemoMill X3",
                site="Plant A",
                invoice_ref=f"INV-{number:03d}",
                payment_ref=f"PAY-{number:03d}",
            )
            store.save(db, asset, actor, reason, "asset.created")
            expected = {
                "identity": asset.serial,
                "purchase": asset.invoice_ref,
                "payment": asset.payment_ref,
                "presence": "present",
                "installation": "installed",
                "commissioning": "commissioned",
            }
            claims = {}
            for kind in ClaimKind:
                claim = Claim(
                    inspection_id=iid, asset_id=asset.id, kind=kind, expected=expected[kind], confirmed=True
                )
                store.save(db, claim, actor, reason, "claim.synthetic_declaration_confirmed")
                claims[kind] = claim

            def evidence(
                kind,
                facts,
                claim_kinds,
                text=None,
                media_type="text/plain",
                content=None,
                asset=asset,
                claims=claims,
            ):
                text = text or "SYNTHETIC DEMO\n" + "\n".join(
                    f"{k}: {str(v).lower() if isinstance(v, bool) else v}"
                    for k, v in facts.items()
                    if v is not None
                )
                content = content if content is not None else text.encode()
                digest = hashlib.sha256(content).hexdigest()
                path = store.files / digest
                if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("Existing synthetic original failed integrity check")
                if not path.exists():
                    with path.open("xb") as file:
                        file.write(content)
                ev = Evidence(
                    inspection_id=iid,
                    kind=kind,
                    filename=f"{asset.tag}-{kind}.txt",
                    media_type=media_type,
                    sha256=digest,
                    byte_size=len(content),
                    source="Prepared synthetic trial — analyst-reviewed sample",
                    captured_at=datetime.now(UTC),
                    facts=Facts(**facts),
                    text=text,
                    confirmed=True,
                    extraction_method="prepared_synthetic_record",
                )
                store.save(db, ev, actor, reason, "evidence.synthetic_sample_reviewed")
                for kind_name in claim_kinds:
                    store.save(
                        db,
                        EvidenceLink(
                            inspection_id=iid,
                            claim_id=claims[kind_name].id,
                            evidence_id=ev.id,
                            relation="supports",
                            locator="Synthetic record, row 1",
                        ),
                        actor,
                        reason,
                        "link.created",
                    )
                return ev

            common = {"serial": asset.serial, "model": asset.model, "site": asset.site}
            financial = {**common, "invoice_ref": asset.invoice_ref, "amount": "100000.00", "currency": "INR"}
            evidence(EvidenceKind.equipment_register, financial, ("identity", "purchase"))
            evidence(EvidenceKind.invoice, financial, ("purchase", "payment"))
            evidence(
                EvidenceKind.payment_extract, {**financial, "payment_ref": asset.payment_ref}, ("payment",)
            )
            condition = "operating" if number < 3 else "packaged"
            facts = {
                **common,
                "present": True,
                "condition": condition,
                "installed": True if number < 3 else None,
            }
            note = "Operating at site" if number < 3 else "Packaged; installation unverified"
            sighting = evidence(
                EvidenceKind.site_observation, facts, ("presence", "installation", "commissioning"), text=note
            )
            store.save(
                db,
                Observation(
                    inspection_id=iid, asset_id=asset.id, evidence_id=sighting.id, text=note, source="analyst"
                ),
                actor,
                reason,
                "observation.created",
            )
            if number == 1:
                evidence(
                    EvidenceKind.commissioning_certificate,
                    {**common, "commissioned": True},
                    ("commissioning",),
                )
            else:
                store.save(
                    db,
                    FollowUpAction(
                        inspection_id=iid,
                        claim_id=claims["commissioning"].id,
                        request="Provide commissioning certificate",
                    ),
                    actor,
                    reason,
                    "follow_up.created",
                )
            if number == 3:
                store.save(
                    db,
                    FollowUpAction(
                        inspection_id=iid,
                        claim_id=claims["installation"].id,
                        request="Clarify installation of packaged equipment",
                    ),
                    actor,
                    reason,
                    "follow_up.created",
                )
        for finding in engine.evaluate(store, db, iid, engine.basis(store, db, iid)):
            store.save(db, finding, actor, reason, "finding.computed")
            finding.reviewed_status, finding.reviewed_by = finding.computed_status, actor
            finding.reviewed_at, finding.review_reason = now(), reason
            store.save(db, finding, actor, reason, "finding.reviewed")
        inspection.state = "review_complete"
        store.save(db, inspection, actor, reason, "inspection.review_complete")
    return inspection
