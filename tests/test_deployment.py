"""Regression coverage for deployment behavior and audit findings."""

import io
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.extraction import extract
from app.main import create_app
from scripts.demo import CAPTURED, PREFIX, label_png, ok, pdf_bytes
from tests.conftest import TOKENS


def test_missing_currency_is_incomplete(case):
    facts = {**case.base, "invoice_ref": "INV-001", "amount": "100.00"}
    case.add("invoice", {**facts, "currency": "INR"}, "purchase")
    case.add("equipment_register", facts, "purchase")
    assert case.reconcile()["purchase"]["computed_status"] == "partly_supported"


def test_currency_conflict_survives_missing_amount(case):
    facts = {**case.base, "invoice_ref": "INV-001"}
    case.add("invoice", {**facts, "amount": "100.00", "currency": "INR"}, "purchase")
    case.add("equipment_register", {**facts, "currency": "USD"}, "purchase")
    assert case.reconcile()["purchase"]["computed_status"] == "potentially_inconsistent"


def test_pdf_single_page_truncation_is_flagged(tmp_path):
    path = tmp_path / "large.pdf"
    path.write_bytes(pdf_bytes("serial: SYN-001\n" + "x" * 100100 + "\nserial: CONFLICT"))
    result = extract(path, "application/pdf")
    assert len(result["text"]) == 100000
    assert "incomplete" in result["flags"]


def test_structured_text_worker_is_portable(tmp_path):
    path = tmp_path / "facts.txt"
    path.write_text("serial: SYN-001", encoding="utf-8")
    result = extract(path, "text/plain")
    assert result["method"] == "structured_text"
    assert result["text"] == "serial: SYN-001"
    assert not result["flags"]


def test_mixed_scan_is_flagged_for_ocr_retry(tmp_path):
    stream = io.BytesIO()
    page = canvas.Canvas(stream, pagesize=(700, 800))
    page.drawString(20, 780, "Scanned invoice")
    page.drawImage(ImageReader(io.BytesIO(label_png("serial: SYN-001\namount: 100"))), 0, 300, 700, 350)
    page.save()
    path = tmp_path / "mixed.pdf"
    path.write_bytes(stream.getvalue())
    result = extract(path, "application/pdf")
    assert result["method"] == "pdf_text"
    assert "incomplete" in result["flags"]


def test_force_ocr_option_reaches_worker(case, monkeypatch):
    import app.main

    ev = case.add("invoice", case.base, "identity")
    seen = []

    def extraction(path, media_type, force_ocr=False):
        seen.append(force_ocr)
        return {"text": "serial: SYN-001", "pages": [], "method": "structured_text", "flags": []}

    monkeypatch.setattr(app.main, "extract", extraction)
    result = ok(
        case.client.post(
            case.url + f"/evidence/{ev['id']}/extract", json={"reason": "Retry scan", "force_ocr": True}
        )
    )
    assert seen == [True]
    assert not result["confirmed"]


def test_inspection_list_and_export_agree_after_corruption(case):
    ev = case.add("site_image", {**case.base, "present": True}, "presence")
    for f in case.reconcile().values():
        ok(
            case.client.patch(
                case.url + f"/findings/{f['id']}/review",
                json={"version": f["version"], "status": f["computed_status"], "reason": "Reviewed"},
            )
        )
    ok(case.client.post(case.url + "/review-complete", json={"reason": "Complete"}))
    (case.client.app.state.store.files / ev["sha256"]).write_bytes(b"corrupt")
    listed = next(i for i in ok(case.client.get(PREFIX + "/inspections")) if i["id"] == case.iid)
    assert listed["state"] == ok(case.client.get(case.url))["state"] == "active"
    assert ok(case.client.get(case.url + "/export"))["inspection"]["state"] == "active"


def test_report_includes_override_reason(case):
    f = case.reconcile()["presence"]
    reason = "Analyst verified provenance remains insufficient"
    ok(
        case.client.patch(
            case.url + f"/findings/{f['id']}/review",
            json={"version": f["version"], "status": "unresolved", "reason": reason},
        )
    )
    text = case.client.get(case.url + "/report").text
    assert reason in text and "Test Analyst" in text


def test_report_shows_current_observation(case):
    obs = ok(
        case.client.post(
            case.url + "/observations",
            json={
                "asset_id": case.asset["id"],
                "text": "Original installed observation",
                "facts": {**case.base, "installed": True},
                "source": "analyst",
                "captured_at": CAPTURED,
                "reason": "Record observation",
            },
        )
    )
    ev = ok(case.client.get(case.url + f"/evidence/{obs['evidence_id']}"))
    ok(
        case.client.patch(
            case.url + f"/evidence/{ev['id']}/correction",
            json={
                "version": ev["version"],
                "text": "Corrected: installation unverified",
                "facts": case.base,
                "quality_flags": ["manual_correction"],
                "confirmed": True,
                "reason": "Correct observation",
            },
        )
    )
    report = case.client.get(case.url + "/report").text
    assert "Corrected: installation unverified" in report
    assert "Original installed observation" not in report
    assert "superseded" in report


def test_invalid_non_ascii_bearer_is_unauthorized(tmp_path):
    with TestClient(create_app(tmp_path, TOKENS, database_url=""), raise_server_exceptions=False) as client:
        assert (
            client.get(PREFIX + "/inspections", headers={b"authorization": b"Bearer \xff"}).status_code == 401
        )


def test_ready_and_metadata(client, monkeypatch):
    assert client.get("/ready").json() == {"status": "ready", "database": "sqlite"}
    meta = ok(client.get(PREFIX + "/meta"))
    assert len(meta["claim_kinds"]) == 6 and meta["max_original_bytes"] == 12 * 1024 * 1024
    monkeypatch.setattr(
        client.app.state.store, "ready", lambda: (_ for _ in ()).throw(RuntimeError("secret"))
    )
    response = client.get("/ready")
    assert response.status_code == 503 and "secret" not in response.text


def test_read_only_get_does_not_take_writer_lock(case):
    store = case.client.app.state.store
    with store.transaction(), ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(case.client.get, case.url).result(timeout=3)
    assert response.status_code == 200


def test_backup_refuses_missing_source(tmp_path):
    source = tmp_path / "wrong"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.backup", str(tmp_path / "backup")],
        env={**os.environ, "CDI_DATA_DIR": str(source), "DATABASE_URL": ""},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert not source.exists()


def test_backup_refuses_corrupt_original(case, tmp_path):
    ev = case.add("site_image", {**case.base, "present": True}, "presence")
    store = case.client.app.state.store
    (store.files / ev["sha256"]).write_bytes(b"corrupt")
    result = subprocess.run(
        [sys.executable, "-m", "scripts.backup", str(tmp_path.parent / (tmp_path.name + "-bad"))],
        env={**os.environ, "CDI_DATA_DIR": str(store.root), "DATABASE_URL": ""},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0


def test_postgres_required_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("CDI_REQUIRE_POSTGRES", "true")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(tmp_path, TOKENS, database_url="")


def test_supabase_rejects_unencrypted_connection_before_network(tmp_path):
    from app.postgres import PostgresStore

    with pytest.raises(RuntimeError, match="encrypted"):
        PostgresStore(tmp_path, "postgresql://postgres:dummy@db.example.supabase.co/postgres?sslmode=disable")
