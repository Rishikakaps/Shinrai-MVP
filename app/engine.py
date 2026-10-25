"""Deterministic claim-level rules. No AI, scoring model, or underwriting."""

import hashlib
import json
from decimal import Decimal

from app.models import Asset, Claim, Evidence, EvidenceLink, Finding, Status
from app.models import EvidenceKind as EK

ACTIONS = {
    "identity": "Capture a readable serial plate and confirm model/site; clarify duplicate identifiers.",
    "purchase": "Request the invoice and matching equipment register/declared asset entry.",
    "payment": "Request a payment extract matching the invoice reference, amount and currency.",
    "presence": "Capture a dated site sighting tied to the confirmed machine identity.",
    "installation": "Confirm installation using an analyst observation or installation record; clarify packaged equipment.",
    "commissioning": "Request and review the commissioning certificate for this machine.",
}


def norm(value):
    # Deliberately do not remove punctuation: near identifiers are not exact identifiers.
    return str(value or "").strip().casefold()


def intact(store, evidence):
    path = store.files / evidence.sha256
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == evidence.sha256
    except OSError:
        return False


def basis(store, db, scope):
    payload = {}
    for cls in (Asset, Claim, Evidence, EvidenceLink):
        payload[cls.__name__] = [o.model_dump(mode="json") for o in store.list(db, cls, scope)]
    payload["integrity"] = {e.id: intact(store, e) for e in store.list(db, Evidence, scope)}
    payload["rules"] = "v1.1"
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def evaluate(store, db, scope, fingerprint):
    assets = store.list(db, Asset, scope)
    evidence = {e.id: e for e in store.list(db, Evidence, scope)}
    links = store.list(db, EvidenceLink, scope)
    results = []
    for claim in store.list(db, Claim, scope):
        asset = next(a for a in assets if a.id == claim.asset_id)
        relevant = [l for l in links if l.active and l.claim_id == claim.id]
        accepted = [
            (l, evidence[l.evidence_id])
            for l in relevant
            if evidence[l.evidence_id].confirmed
            and intact(store, evidence[l.evidence_id])
            and not {"unreadable", "blurry", "incomplete"}.intersection(evidence[l.evidence_id].quality_flags)
        ]
        # Management and financial statements never establish a core claim.
        proof = [
            (l, e)
            for l, e in accepted
            if l.relation != "context" and e.kind not in (EK.management_statement, EK.financial_statement)
        ]
        supports = [e for l, e in proof if l.relation == "supports"]
        contradictions = [e for l, e in proof if l.relation == "contradicts"]
        status, explanation = Status.unresolved, "No sufficient accepted evidence for this atomic claim."
        if not claim.confirmed:
            status, explanation = Status.not_assessed, "Analyst has not confirmed the declared claim."
        else:
            scoped = [e for e in supports if asset.serial and norm(e.facts.serial) == norm(asset.serial)]
            # A label accepted by an analyst still cannot resolve duplicated serial identities.
            duplicate = sum(norm(a.serial) == norm(asset.serial) for a in assets) > 1
            if claim.kind == "identity":
                exact = [
                    e
                    for e in scoped
                    if norm(e.facts.serial) == norm(claim.expected)
                    and norm(e.facts.model) == norm(asset.model)
                    and norm(e.facts.site) == norm(asset.site)
                ]
                if duplicate or any("duplicate_serial" in e.quality_flags for e in supports):
                    explanation = "Duplicate serial identifier; analyst clarification required."
                elif exact:
                    status, explanation = (
                        Status.supported,
                        "Exact serial with model and site corroboration, accepted by analyst.",
                    )
                elif scoped:
                    status, explanation = (
                        Status.partly_supported,
                        "Serial matches; model or site corroboration is missing.",
                    )
            elif claim.kind == "purchase":
                invoices = [
                    e
                    for e in scoped
                    if e.kind == EK.invoice and norm(e.facts.invoice_ref) == norm(claim.expected)
                ]
                registers = [
                    e
                    for e in scoped
                    if e.kind in (EK.equipment_register, EK.declared_asset)
                    and norm(e.facts.invoice_ref) == norm(claim.expected)
                ]
                pairs = [(i, r) for i in invoices for r in registers]
                if any(
                    i.facts.amount is not None
                    and r.facts.amount is not None
                    and i.facts.amount != r.facts.amount
                    or (
                        i.facts.currency is not None
                        and r.facts.currency is not None
                        and i.facts.currency != r.facts.currency
                    )
                    for i, r in pairs
                ):
                    status, explanation = (
                        Status.potentially_inconsistent,
                        "Invoice and register amounts/currencies differ; clarify.",
                    )
                elif any(
                    i.facts.amount is not None
                    and r.facts.amount is not None
                    and i.facts.currency
                    and r.facts.currency
                    for i, r in pairs
                ):
                    status, explanation = (
                        Status.supported,
                        "Invoice reference and machine identifier match the register/declared asset.",
                    )
                elif invoices or registers:
                    status, explanation = (
                        Status.partly_supported,
                        "Invoice/register evidence is incomplete; verify identifier, reference, amount and currency.",
                    )
            elif claim.kind == "payment":
                payments = [
                    e
                    for e in scoped
                    if e.kind == EK.payment_extract and norm(e.facts.payment_ref) == norm(claim.expected)
                ]
                invoices = [
                    e
                    for e in scoped
                    if e.kind == EK.invoice and norm(e.facts.invoice_ref) == norm(asset.invoice_ref)
                ]
                matches, mismatches = [], []
                for p in payments:
                    for i in invoices:
                        pf, inf = p.facts, i.facts
                        if (
                            not pf.invoice_ref
                            or inf.amount is None
                            or pf.amount is None
                            or not inf.currency
                            or not pf.currency
                        ):
                            continue
                        ok = (
                            norm(pf.invoice_ref) == norm(inf.invoice_ref)
                            and Decimal(pf.amount) == Decimal(inf.amount)
                            and pf.currency == inf.currency
                        )
                        (matches if ok else mismatches).append(p)
                if mismatches:
                    status, explanation = (
                        Status.potentially_inconsistent,
                        "Payment and invoice reference/amount/currency mismatch; clarify.",
                    )
                elif matches:
                    status, explanation = (
                        Status.supported,
                        "Accepted payment reference, invoice reference, amount and currency reconcile.",
                    )
                elif payments or invoices:
                    status, explanation = Status.partly_supported, "Payment/invoice pair is incomplete."
            else:
                eligible = {
                    "presence": ({EK.site_image, EK.site_observation}, "present", "present"),
                    "installation": ({EK.installation_record, EK.site_observation}, "installed", "installed"),
                    "commissioning": ({EK.commissioning_certificate}, "commissioned", "commissioned"),
                }
                kinds, field, expected = eligible[claim.kind]
                candidates = [e for e in scoped if e.kind in kinds]
                positives = [e for e in candidates if getattr(e.facts, field) is True]
                negatives = [e for e in candidates if getattr(e.facts, field) is False]
                if positives and norm(claim.expected) == expected:
                    status, explanation = (
                        Status.supported,
                        f"Accepted {field} evidence tied to this serial identifier.",
                    )
                if negatives:
                    status, explanation = (
                        Status.potentially_inconsistent,
                        f"Explicit accepted observation conflicts with declared {field}; clarify.",
                    )
                # Packaged condition is a request for clarification, not a negative assertion.
                if (
                    claim.kind == "installation"
                    and any(e.facts.condition == "packaged" for e in scoped)
                    and not positives
                    and not negatives
                ):
                    status, explanation = (
                        Status.unresolved,
                        "Equipment is packaged; installation requires clarification.",
                    )
                if claim.kind == "commissioning" and not candidates:
                    explanation = (
                        "Commissioning certificate is missing or unaccepted; operation alone is insufficient."
                    )
            conflicts = [
                e
                for e in supports
                if any(
                    getattr(e.facts, field) is not None
                    and norm(getattr(e.facts, field)) != norm(getattr(asset, field))
                    for field in ("serial", "model", "site")
                )
            ]
            if claim.kind in ("purchase", "payment"):
                conflicts += [
                    e
                    for e in supports
                    if e.kind in (EK.invoice, EK.equipment_register, EK.declared_asset, EK.payment_extract)
                    and e.facts.invoice_ref
                    and norm(e.facts.invoice_ref) != norm(asset.invoice_ref)
                ]
            if claim.kind == "payment":
                conflicts += [
                    e
                    for e in supports
                    if e.kind == EK.payment_extract
                    and e.facts.payment_ref
                    and norm(e.facts.payment_ref) != norm(claim.expected)
                ]
            if conflicts:
                status, explanation = (
                    Status.potentially_inconsistent,
                    "Accepted linked evidence has conflicting machine/site/reference identifiers; clarify.",
                )
            if contradictions:
                status, explanation = (
                    Status.potentially_inconsistent,
                    "Accepted contradictory evidence exists; analyst review required.",
                )
        invalid = [evidence[l.evidence_id].id for l in relevant if not intact(store, evidence[l.evidence_id])]
        if invalid:
            explanation += " Original integrity check failed; affected evidence excluded."
        results.append(
            Finding(
                inspection_id=scope,
                claim_id=claim.id,
                computed_status=status,
                explanation=explanation,
                next_best_action=(
                    "Review finding and preserve supporting evidence."
                    if status == Status.supported
                    else ACTIONS[claim.kind]
                ),
                evidence_ids=sorted({e.id for _, e in accepted}),
                basis_hash=fingerprint,
            )
        )
    return results


def current_findings(store, db, scope):
    fingerprint = basis(store, db, scope)
    latest = {}
    for finding in store.list(db, Finding, scope):
        latest[finding.claim_id] = finding
    return [f for f in latest.values() if f.basis_hash == fingerprint]
