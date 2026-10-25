"""Advisory row association from independently observed, exact serial tokens."""

import re

from app.identifiers import code_fields, normalized, parse_fields
from app.models import Asset, Claim, EvidenceLink


def associate_nameplate(store, db, iid, evidence_id, raw, intended_id, actor, reason):
    text = raw.get("ocr_text", "")
    serials = list((raw.get("ocr_fields") or parse_fields(text)).get("serial", []))
    for code in raw.get("codes", []):
        serials.extend(code_fields(code.get("text", "")).get("serial", []))
    if len({normalized(s) for s in serials}) > 1:
        return {"state": "CONFLICTING_SOURCES", "asset_id": None}
    matches = [
        a
        for a in store.list(db, Asset, iid)
        if a.nameplate_metadata
        and not a.serial.startswith("UNVERIFIED-")
        and len(a.serial) >= 4
        and re.search(r"(?<![\w./-])" + re.escape(a.serial) + r"(?![\w./-])", text, re.IGNORECASE)
    ]
    if len(matches) != 1:
        return {"state": "AMBIGUOUS" if matches else "NOT_FOUND", "asset_id": None}
    asset = matches[0]
    if serials and any(normalized(s) != normalized(asset.serial) for s in serials):
        return {"state": "CONFLICTING_SOURCES", "asset_id": None}
    if intended_id and intended_id != asset.id:
        return {"state": "CONTEXT_CONFLICT", "asset_id": asset.id, "tag": asset.tag}
    claim = next(c for c in store.list(db, Claim, iid) if c.asset_id == asset.id and c.kind == "identity")
    links = store.list(db, EvidenceLink, iid)
    if not any(l.active and l.claim_id == claim.id and l.evidence_id == evidence_id for l in links):
        store.save(
            db,
            EvidenceLink(
                inspection_id=iid,
                claim_id=claim.id,
                evidence_id=evidence_id,
                relation="context",
                locator="Exact serial token in OCR; source and identity require analyst review",
            ),
            actor,
            reason,
            "nameplate.context_associated",
        )
    return {"state": "CONTEXT_LINKED", "asset_id": asset.id, "tag": asset.tag, "accepted": False}
