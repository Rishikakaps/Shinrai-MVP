"""Real storage/OCR/video acceptance; no mocked recognition or provider claims."""

import hashlib
import io
import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.intake_understanding import extract_fields, resolve
from app.main import create_app
from app.models import Asset
from tests.conftest import ANALYST, JUDGE, TOKENS
from tests.test_field_workflow import label
from tests.test_v2_backend import post


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CDI_INTAKE_WORKER", "false")
    with TestClient(
        create_app(tmp_path, TOKENS, database_url=""), headers={"Authorization": "Bearer " + ANALYST}
    ) as c:
        yield c


@pytest.fixture
def intake(case, monkeypatch):
    monkeypatch.setenv("CDI_INTAKE_WORKER", "false")
    c = post(
        case.client,
        "/api/v1/cases",
        {
            "inspection_id": case.iid,
            "company": "Synthetic intake",
            "site": "Plant A",
            "reason": "Intake test",
        },
    ).json()
    return SimpleNamespace(
        case=case, client=case.client, case_id=c["id"], service=case.client.app.state.intake
    )


def pdf(text):
    output = io.BytesIO()
    doc = canvas.Canvas(output)
    for index, line in enumerate(text.splitlines()):
        doc.drawString(40, 790 - index * 24, line)
    doc.save()
    return output.getvalue()


CERT = "synthetic_demo\nCommissioning certificate\nAsset ID: CNC-001\nSerial: SYN-001\nModel: DemoMill X3\nSite: Plant A\nCommissioned: true\nCommissioning date: 2026-10-25"


def upload(i, content=None, name="IMG_0028.pdf", mime="application/pdf", key=None, **metadata):
    return i.client.post(
        "/api/evidence/intake",
        files={"file": (name, content if content is not None else pdf(CERT), mime)},
        data={
            "metadata": json.dumps(
                {
                    "case_id": i.case_id,
                    "inspection_id": i.case.iid,
                    "captured_at": "2026-10-24T00:00:00+00:00",
                    "synthetic_demo": True,
                    "reason": "Upload synthetic intake fixture",
                    **metadata,
                }
            )
        },
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def processed(i, response):
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    i.service.run_once()
    data = i.client.get("/api/evidence/" + identifier + "/processing-status").json()
    assert data["intake"]["processing_status"] == "needs_review", data
    return data


def test_pdf_review_reconciliation_and_restart(intake):
    i = intake
    data = processed(i, upload(i))
    r, ev = data["intake"], data["evidence"]
    assert r["category"] == "commissioning_certificate"
    assert r["resolution"]["decision"] == "EXACT_SERIAL_CANDIDATE"
    assert not ev["confirmed"] and ev["facts"]["commissioned"] is None
    root = "/api/evidence/" + r["id"]
    body = {
        "version": r["version"],
        "action": "confirm",
        "asset_id": i.case.asset["id"],
        "checked_original": True,
        "reason": "Reviewed synthetic source identity",
    }
    associated = i.client.post(root + "/confirm-asset", json=body)
    assert associated.status_code == 200, associated.text
    assert not i.client.get(root + "/processing-status").json()["evidence"]["confirmed"]
    reviewed = i.client.post(
        root + "/review-document",
        json={
            "version": associated.json()["version"],
            "evidence_version": ev["version"],
            "category": r["category"],
            "facts": data["proposed_facts"],
            "checked_original": True,
            "reason": "Confirm each field against the synthetic certificate",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    linked = i.client.post(
        i.case.url + "/evidence-links",
        json={
            "claim_id": i.case.claims["commissioning"]["id"],
            "evidence_id": ev["id"],
            "relation": "supports",
            "locator": "Page 1, serial and commissioning lines",
            "reason": "Explicit analyst link",
        },
    )
    assert linked.status_code == 201, linked.text
    assert i.case.reconcile()["commissioning"]["computed_status"] == "supported"
    assert (
        i.client.get("/api/assets/" + i.case.asset["id"] + "/evidence").json()["intake"][0]["id"] == r["id"]
    )
    with TestClient(
        create_app(i.client.app.state.store.root, TOKENS), headers={"Authorization": "Bearer " + ANALYST}
    ) as restarted:
        original = restarted.get(root + "/original").content
        assert hashlib.sha256(original).hexdigest() == r["content_sha256"]
        assert (
            restarted.get(root + "/processing-status").json()["intake"]["assigned_asset_id"]
            == i.case.asset["id"]
        )


@pytest.mark.parametrize(
    "text,decision",
    [
        ("Model: DemoMill X3", "MODEL_ONLY_NOT_IDENTITY"),
        ("Asset ID: CNC-001\nSerial: SYN-999", "CONTRADICTORY_IDENTIFIERS"),
        ("Serial: SYN-00?", "PARTIAL_IDENTIFIER"),
        ("No recognizable fields", "UNASSIGNED"),
        ("Serial: SYN-001\nSerial: SYN-003", "MULTIPLE_OR_CONFLICTING_IDENTIFIERS"),
    ],
)
def test_adversarial_resolution_never_auto_links(text, decision):
    fields = extract_fields([{"page": 1, "text": text, "method": "pdf_text"}])
    assets = [
        Asset(
            inspection_id="visit",
            tag="CNC-001",
            serial="SYN-001",
            model="DemoMill X3",
            site="Plant A",
            invoice_ref="INV",
            payment_ref="PAY",
        ),
        Asset(
            inspection_id="visit",
            tag="CNC-003",
            serial="SYN-003",
            model="DemoMill X3",
            site="Plant A",
            invoice_ref="INV3",
            payment_ref="PAY3",
        ),
    ]
    result = resolve(fields, assets)
    assert result["decision"] == decision
    assert not result["automatic_association"]


def test_duplicate_content_and_exact_retry_keep_audit_without_reprocessing(intake):
    i, key = intake, str(uuid4())
    content = pdf(CERT)
    first = processed(i, upload(i, content=content, key=key))["intake"]
    assert upload(i, content=content, key=key).json()["id"] == first["id"]
    assert upload(i, content=pdf(CERT + "\nChanged"), key=key).status_code == 409
    # ReportLab embeds timestamps/IDs; reuse the exact source bytes for a true duplicate.
    original = i.client.get("/api/evidence/" + first["id"] + "/original").content
    second = processed(i, upload(i, content=original))["intake"]
    assert second["id"] != first["id"] and second["duplicate_of"] == first["id"]
    assert second["cached_from"] == first["id"]
    assert second["evidence_id"] != first["evidence_id"]


def test_conflict_override_and_judge_restrictions(intake):
    i = intake
    data = processed(i, upload(i, content=pdf(CERT.replace("SYN-001", "SYN-999"))))
    r = data["intake"]
    root = "/api/evidence/" + r["id"]
    body = {
        "version": r["version"],
        "action": "confirm",
        "asset_id": i.case.asset["id"],
        "checked_original": True,
        "reason": "Explicit reviewed association",
    }
    assert i.client.post(root + "/confirm-asset", json=body).status_code == 422
    body["acknowledge_conflicts"] = True
    assert i.client.post(root + "/confirm-asset", json=body).status_code == 200
    i.client.headers["Authorization"] = "Bearer " + JUDGE
    assert i.client.post(root + "/confirm-asset", json=body).status_code == 403
    assert upload(i).status_code == 403


def test_corrupted_pdf_and_cross_inspection_hint_rejected(intake):
    i = intake
    assert upload(i, content=b"%PDF-corrupt").status_code == 422
    assert upload(i, asset_hint="unrelated-asset").status_code == 404


def test_real_nameplate_ocr_qr_sources(intake):
    data = processed(
        intake, upload(intake, content=label(code="SYN-001"), name="camera.png", mime="image/png")
    )
    r = data["intake"]
    assert r["resolution"]["decision"] == "EXACT_SERIAL_CANDIDATE"
    fields = r["raw_result"]["fields"]
    assert any(f["method"] == "QR Code" for f in fields)
    assert any(f["name"] == "serial_number" and "tesseract" in f["method"] for f in fields)


def test_real_video_sampling_with_source_timestamps(intake, tmp_path):
    png, video = tmp_path / "label.png", tmp_path / "label.mp4"
    png.write_bytes(label(code="SYN-001"))
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(png),
            "-t",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(video),
        ],
        capture_output=True,
        check=True,
        timeout=20,
    )
    data = processed(
        intake,
        upload(
            intake, content=video.read_bytes(), name="phone.mp4", mime="video/mp4", recording_authorized=True
        ),
    )
    r = data["intake"]
    assert r["raw_result"]["sampled_frame_limit"] == 6
    assert 1 <= len(r["raw_result"]["pages"]) <= 3
    assert r["raw_result"]["pages"][0]["timestamp"] >= 0
    assert intake.client.get("/api/evidence/" + r["id"] + "/frames/1").status_code == 200


def test_bad_video_fails_but_original_is_retained(intake):
    i = intake
    response = upload(
        i,
        content=b"\x00\x00\x00\x18ftyp" + b"corrupt" * 50,
        name="bad.mp4",
        mime="video/mp4",
        recording_authorized=True,
    )
    assert response.status_code == 201, response.text
    i.service.run_once()
    root = "/api/evidence/" + response.json()["id"]
    assert i.client.get(root + "/processing-status").json()["intake"]["processing_status"] == "failed"
    assert i.client.get(root + "/original").status_code == 200
