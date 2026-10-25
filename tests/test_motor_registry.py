import json
from pathlib import Path

from PIL import Image

from app.identifiers import parse_fields
from app.models import Asset, Claim, EvidenceLink
from app.nameplates import associate_nameplate
from app.store import Store
from scripts.import_motor_nameplates import run


def test_inline_nameplate_fields_are_observed_without_expected_values():
    fields = parse_fields("Model No. 121123 Serial No. 134678 [|")
    assert fields["serial"] == ["134678"]
    assert fields["model"] == ["121123"]
    assert fields["site"] == []


def test_registry_import_is_unverified_and_resumable(client, tmp_path):
    records = json.loads(Path("fixtures/motor-nameplates/assets.json").read_text(encoding="utf-8"))
    # Publisher filenames can end in .jpg while the untouched bytes are PNG.
    Image.new("RGB", (200, 200), "white").save(tmp_path / records[0]["source_image_filename"], "PNG")
    result = run(client, records, tmp_path)
    repeated = run(client, records, tmp_path)
    assert result == repeated
    assert (result["assets"], result["claims"], result["evidence"], result["supported"]) == (40, 240, 41, 0)
    report = client.get(f"/api/v1/inspections/{result['inspection_id']}/export").json()
    assert sum(a["serial"].startswith("UNVERIFIED-") for a in report["assets"]) == 14
    assert all(not e["confirmed"] for e in report["evidence"])
    assert all(l["relation"] == "context" for l in report["evidence_links"])
    sample = next(a for a in report["assets"] if a["tag"] == "MTR-031")
    assert sample["serial"] == "134678"
    assert sample["nameplate_metadata"]["scan_sample"] is True
    assert any(e["filename"] == "MTR-001-nameplate.png" for e in report["evidence"])
    missing = next(a for a in report["assets"] if a["serial"].startswith("UNVERIFIED-"))
    blocked = client.post(
        f"/api/v1/cases/{result['case_id']}/physical-assets",
        headers={"Idempotency-Key": "missing-serial-test"},
        json={
            "inspection_id": result["inspection_id"],
            "local_asset_id": missing["id"],
            "identity_evidence_id": report["evidence"][0]["id"],
            "identity_locator": "label",
            "reason": "Missing serial cannot become physical identity",
        },
    )
    assert blocked.status_code == 422 and "no verified serial" in blocked.text


def test_exact_scan_association_is_context_only_and_respects_intent(tmp_path):
    store = Store(tmp_path)
    with store.transaction() as db:
        for index, serial in enumerate(("134678", "UNVERIFIED-MTR-002")):
            a = Asset(
                inspection_id="visit",
                tag=f"MTR-{index + 1:03}",
                serial=serial,
                model="121123",
                site="Demo",
                invoice_ref="missing",
                payment_ref="missing",
                nameplate_metadata={"dataset_label_status": "auto_generated_unverified"},
            )
            store.save(db, a, "test", "fixture", "asset.created")
            store.save(
                db,
                Claim(inspection_id="visit", asset_id=a.id, kind="identity", expected=serial),
                "test",
                "fixture",
                "claim.declared",
            )
        assets = store.list(db, Asset, "visit")

        def associate(text, intended=None):
            return associate_nameplate(
                store, db, "visit", "photo", {"ocr_text": text}, intended, "test", "Scan exact token"
            )

        assert associate("Serial 134678", assets[1].id)["state"] == "CONTEXT_CONFLICT"
        assert not store.list(db, EvidenceLink, "visit")
        assert associate("Serial 0134678")["state"] == "NOT_FOUND"
        assert associate("Serial XX-134678")["state"] == "NOT_FOUND"
        assert associate("Serial UNVERIFIED-MTR-002")["state"] == "NOT_FOUND"
        assert associate("Serial No. 134678", assets[0].id)["state"] == "CONTEXT_LINKED"
        associate("Serial No. 134678", assets[0].id)
        links = store.list(db, EvidenceLink, "visit")
        assert len(links) == 1 and links[0].relation == "context"
        assert all(not c.confirmed for c in store.list(db, Claim, "visit"))
