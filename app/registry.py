"""The operational registry service shared by declarations, imports and scan review."""

from fastapi import HTTPException

from app import engine
from app.models import Asset, Claim, ClaimKind, Inspection


def save_asset(store, db, iid, body, actor, aid=None):
    inspection = store.get(db, Inspection, iid, iid)
    if any(engine.norm(a.tag) == engine.norm(body.tag) and a.id != aid for a in store.list(db, Asset, iid)):
        raise HTTPException(409, "Asset tag already exists")
    values = body.model_dump(exclude={"reason", "version"})
    if aid and "nameplate_metadata" not in body.model_fields_set:
        values.pop("nameplate_metadata", None)
    if aid:
        asset = store.get(db, Asset, aid, iid)
        if asset.version != body.version:
            raise HTTPException(409, "Stale version; reload before saving")
        for key, value in values.items():
            setattr(asset, key, value)
    else:
        asset = Asset(inspection_id=iid, **values)
    store.save(db, asset, actor, body.reason, "asset.corrected" if aid else "asset.created")
    expected = {
        "identity": asset.serial or "Unknown serial — review required",
        "purchase": asset.invoice_ref or "Unknown invoice — review required",
        "payment": asset.payment_ref or "Unknown payment — review required",
        "presence": "present",
        "installation": "installed",
        "commissioning": "commissioned",
    }
    claims = [c for c in store.list(db, Claim, iid) if c.asset_id == aid] if aid else []
    for kind in ClaimKind:
        claim = next((c for c in claims if c.kind == kind), None)
        if claim:
            claim.expected, claim.confirmed = expected[kind], False
        else:
            claim = Claim(inspection_id=iid, asset_id=asset.id, kind=kind, expected=expected[kind])
        store.save(db, claim, actor, body.reason, "claim.declaration_corrected" if aid else "claim.declared")
    if inspection.state != "active":
        inspection.state = "active"
        store.save(db, inspection, actor, body.reason, "inspection.invalidated_or_started")
    return asset
