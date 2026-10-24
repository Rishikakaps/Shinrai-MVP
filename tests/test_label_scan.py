"""Actual decoder, source persistence and scan authorization tests."""

import hashlib
import io

import pytest
import zxingcpp
from PIL import Image, ImageFilter

from app.label_scan import scan_file
from tests.conftest import JUDGE


def qr(text):
    image = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode), scale=12
    )
    return Image.frombytes("L", (image.shape[1], image.shape[0]), bytes(image))


def uploaded(case, image):
    out = io.BytesIO()
    image.save(out, format="PNG")
    payload = out.getvalue()
    r = case.client.post(
        case.url + "/evidence",
        data={
            "kind": "site_image",
            "source": "Synthetic phone label",
            "captured_at": "2026-10-01T01:00:00+00:00",
            "reason": "Save synthetic camera fixture",
        },
        files={"file": ("label.png", payload, "image/png")},
    )
    assert r.status_code == 201, r.text
    return r.json(), payload


def scan(case, ev, asset_id=None):
    return case.client.post(
        case.url + "/evidence/" + ev["id"] + "/scan-label",
        json={
            "asset_id": asset_id or case.asset["id"],
            "reason": "Review barcode without accepting identity",
        },
    )


def test_real_barcode_matches_without_accepting_evidence_or_identity(case):
    ev, content = uploaded(case, qr(case.base["serial"]))
    before = case.reconcile()
    result = scan(case, ev)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["identity_result"] == "matches_declared_serial"
    assert data["identity_confirmed"] is False and data["evidence_accepted"] is False
    saved = case.client.get(case.url + "/evidence/" + ev["id"]).json()
    assert not saved["confirmed"]
    original = case.client.get(case.url + "/evidence/" + ev["id"] + "/original")
    assert hashlib.sha256(original.content).hexdigest() == hashlib.sha256(content).hexdigest()
    after = case.reconcile()
    assert [v["id"] for v in before.values()] == [v["id"] for v in after.values()]


def test_wrong_serial_is_a_mismatch_not_a_silent_rebind(case):
    ev, _ = uploaded(case, qr("OTHER-MACHINE-999"))
    result = scan(case, ev).json()
    assert result["identity_result"] == "differs_from_declared_serial"
    assert result["serial_suggestions"] == ["OTHER-MACHINE-999"]
    assert not result["identity_confirmed"]


def test_blank_photo_returns_rescan_flags_and_no_guessed_serial(case):
    ev, _ = uploaded(case, Image.new("RGB", (600, 400), "white"))
    result = scan(case, ev).json()
    assert result["identity_result"] == "not_read"
    assert not result["serial_suggestions"]
    assert "low_contrast" in result["quality_flags"] and "serial_not_read" in result["quality_flags"]


def test_heavily_blurred_code_does_not_guess_identity(case):
    ev, _ = uploaded(case, qr(case.base["serial"]).filter(ImageFilter.GaussianBlur(30)))
    result = scan(case, ev).json()
    assert not result["identity_confirmed"]
    assert result["identity_result"] == "not_read"


def test_scan_denies_judge_and_foreign_asset(case):
    ev, _ = uploaded(case, qr(case.base["serial"]))
    endpoint = case.url + "/evidence/" + ev["id"] + "/scan-label"
    assert (
        case.client.post(
            endpoint, json={"reason": "Not permitted"}, headers={"Authorization": "Bearer " + JUDGE}
        ).status_code
        == 403
    )
    assert scan(case, ev, "unknown-asset").status_code == 404


def test_scan_requires_image_and_unchanged_original(case):
    from scripts.demo import upload

    ev = upload(case.client, case.iid, "equipment_register", "Serial: SYN-001")
    assert scan(case, ev).status_code == 415
    image, _ = uploaded(case, qr(case.base["serial"]))
    (case.client.app.state.store.files / image["sha256"]).write_bytes(b"corrupt fixture")
    assert scan(case, image).status_code == 409


def test_decoder_timeout_has_truthful_preserved_source_error(tmp_path, monkeypatch):
    import subprocess

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("label scan", 28)

    monkeypatch.setattr("app.label_scan.subprocess.run", timeout)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        scan_file(tmp_path / "original")
    assert e.value.status_code == 422 and "original is saved" in e.value.detail


def test_synthetic_camera_label_is_protected_and_demo_only(case, tmp_path):
    assert case.client.get(case.url + "/demo-label/" + case.asset["id"]).status_code == 403
    trial = case.client.post(
        "/api/v1/demo/prepare", json={"reason": "Prepare separate synthetic scan fixture"}
    ).json()
    report = case.client.get("/api/v1/inspections/" + trial["id"] + "/export").json()
    machine = report["assets"][0]
    result = case.client.get("/api/v1/inspections/" + trial["id"] + "/demo-label/" + machine["id"])
    assert result.status_code == 200 and result.content.startswith(b"\x89PNG")
    p = tmp_path / "label.png"
    p.write_bytes(result.content)
    decoded = scan_file(p)
    assert machine["serial"] in decoded["serial_suggestions"]
    assert "SYNTHETIC" in decoded["ocr_text"]
