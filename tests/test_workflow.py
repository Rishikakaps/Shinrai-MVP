import hashlib
import io
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.extraction import extract, parse_facts
from app.main import create_app
from scripts.demo import CAPTURED, PREFIX, accept, label_png, ok, pdf_bytes, seed, upload
from tests.conftest import JUDGE, TOKENS


def test_end_to_end_plant_a_and_restart(client, tmp_path):
    snapshot = seed(client)
    assert snapshot["inspection"]["state"] == "review_complete"
    assets = {a["id"]: a["tag"] for a in snapshot["assets"]}
    claims = {c["id"]: c for c in snapshot["claims"]}
    result = {
        (assets[claims[f["claim_id"]]["asset_id"]], claims[f["claim_id"]]["kind"]): f
        for f in snapshot["findings"]
    }
    assert len(result) == 18
    assert result["CNC-001", "commissioning"]["computed_status"] == "supported"
    assert result["CNC-002", "presence"]["computed_status"] == "supported"
    assert result["CNC-002", "commissioning"]["computed_status"] == "unresolved"
    assert result["CNC-003", "installation"]["computed_status"] == "unresolved"
    assert "packaged" in result["CNC-003", "installation"]["explanation"]
    assert len(snapshot["follow_ups"]) == 3
    assert any(e["extraction_method"] == "tesseract" and "SYN" in e["text"] for e in snapshot["evidence"])
    assert any(e["extraction_method"] == "pdf_text" and "100000" in e["text"] for e in snapshot["evidence"])
    assert all(f["reviewed_by"] == "Test Analyst" for f in snapshot["findings"])
    iid = snapshot["inspection"]["id"]
    assert client.get(f"{PREFIX}/inspections/{iid}/report").status_code == 200
    assert len(ok(client.get(f"{PREFIX}/inspections/{iid}/mission"))["items"]) == 3
    with TestClient(create_app(tmp_path, TOKENS), headers={"Authorization": "Bearer " + JUDGE}) as restarted:
        restored = ok(restarted.get(f"{PREFIX}/inspections/{iid}/export"))
        assert restored["evidence"] == snapshot["evidence"]
        assert restored["review_events"] == snapshot["review_events"]
        for ev in restored["evidence"]:
            raw = restarted.get(f"{PREFIX}/inspections/{iid}/evidence/{ev['id']}/original")
            assert hashlib.sha256(raw.content).hexdigest() == ev["sha256"]


def test_missing_evidence_is_unresolved_not_absence(case):
    findings = case.reconcile()
    assert all(f["computed_status"] == "unresolved" for f in findings.values())
    assert "certificate" in findings["commissioning"]["next_best_action"]


@pytest.mark.parametrize("kind", ["purchase", "payment", "installation", "commissioning"])
def test_sighting_does_not_prove_other_claims(case, kind):
    case.add("site_image", {**case.base, "present": True, "condition": "operating"}, kind)
    assert case.reconcile()[kind]["computed_status"] == "unresolved"


@pytest.mark.parametrize("flag", ["unreadable", "blurry", "duplicate_serial", "incomplete"])
def test_ambiguous_identity_never_supported(case, flag):
    case.add("site_image", case.base, "identity", flags=[flag])
    assert case.reconcile()["identity"]["computed_status"] == "unresolved"


def test_duplicate_declared_serial_blocks_identity(case):
    case.add("equipment_register", case.base, "identity")
    assert case.reconcile()["identity"]["computed_status"] == "supported"
    ok(
        case.client.post(
            case.url + "/assets",
            json={"tag": "CNC-DUP", **case.base, "invoice_ref": "INV-X", "payment_ref": "PAY-X"},
        )
    )
    assert case.reconcile()["identity"]["computed_status"] == "unresolved"


@pytest.mark.parametrize(
    "facts,expected",
    [
        ({"serial": "SYN-001"}, "partly_supported"),
        ({"serial": "SYN001", "model": "DemoMill X3", "site": "Plant A"}, "potentially_inconsistent"),
        ({"serial": "SYN-001", "model": "Wrong", "site": "Plant A"}, "potentially_inconsistent"),
    ],
)
def test_identity_exact_match_and_corroboration(case, facts, expected):
    case.add("site_image", facts, "identity")
    assert case.reconcile()["identity"]["computed_status"] == expected


def test_unconfirmed_claim_not_assessed(case):
    claim = case.claims["presence"]
    ok(
        case.client.patch(
            case.url + f"/claims/{claim['id']}/confirmation",
            json={
                "expected": claim["expected"],
                "version": claim["version"],
                "confirmed": False,
                "reason": "Needs checking",
            },
        )
    )
    case.add("site_observation", {**case.base, "present": True}, "presence")
    assert case.reconcile()["presence"]["computed_status"] == "not_assessed"


def test_unconfirmed_evidence_and_context_do_not_prove(case):
    case.add("site_image", {**case.base, "present": True}, "presence", confirmed=False)
    case.add("management_statement", {**case.base, "present": True}, "presence", relation="context")
    case.add("financial_statement", {**case.base, "present": True}, "presence", relation="context")
    assert case.reconcile()["presence"]["computed_status"] == "unresolved"
    ev = upload(case.client, case.iid, "management_statement", "management says paid")
    response = case.client.post(
        case.url + "/evidence-links",
        json={
            "claim_id": case.claims["payment"]["id"],
            "evidence_id": ev["id"],
            "relation": "supports",
            "locator": "page 1",
            "reason": "Test contextual restriction",
        },
    )
    assert response.status_code == 422


def test_explicit_negative_and_conflicting_support(case):
    case.add("site_observation", {**case.base, "installed": True}, "installation")
    case.add("site_observation", {**case.base, "installed": False}, "installation")
    assert case.reconcile()["installation"]["computed_status"] == "potentially_inconsistent"


def test_all_accepted_evidence_contradiction_wins(case):
    case.add("site_image", {**case.base, "present": True}, "presence")
    case.add("site_observation", {**case.base, "present": False}, "presence", relation="contradicts")
    assert case.reconcile()["presence"]["computed_status"] == "potentially_inconsistent"


@pytest.mark.parametrize(
    "change", [{"amount": "90000.00"}, {"currency": "USD"}, {"invoice_ref": "INV-OTHER"}]
)
def test_payment_mismatch(case, change):
    common = {**case.base, "invoice_ref": "INV-001", "amount": "100000.00", "currency": "INR"}
    case.add("invoice", common, "payment")
    case.add("payment_extract", {**common, "payment_ref": "PAY-001", **change}, "payment")
    assert case.reconcile()["payment"]["computed_status"] == "potentially_inconsistent"


def test_payment_decimal_match_and_conflicting_second_payment(case):
    common = {**case.base, "invoice_ref": "INV-001", "amount": "100000.00", "currency": "INR"}
    case.add("invoice", common, "payment")
    case.add("payment_extract", {**common, "payment_ref": "PAY-001", "amount": "100000"}, "payment")
    assert case.reconcile()["payment"]["computed_status"] == "supported"
    case.add("payment_extract", {**common, "payment_ref": "PAY-001", "amount": "50000"}, "payment")
    assert case.reconcile()["payment"]["computed_status"] == "potentially_inconsistent"


def test_purchase_register_invoice_discrepancy(case):
    common = {**case.base, "invoice_ref": "INV-001", "amount": "100000.00", "currency": "INR"}
    case.add("invoice", common, "purchase")
    assert case.reconcile()["purchase"]["computed_status"] == "partly_supported"
    case.add("declared_asset", {**common, "amount": "50000"}, "purchase")
    assert case.reconcile()["purchase"]["computed_status"] == "potentially_inconsistent"


def test_revision_history_stale_review_and_override(case):
    ev = case.add("site_image", {**case.base, "present": True}, "presence")
    finding = case.reconcile()["presence"]
    reviewed = ok(
        case.client.patch(
            case.url + f"/findings/{finding['id']}/review",
            json={
                "version": finding["version"],
                "status": "unresolved",
                "reason": "Analyst requires stronger provenance",
            },
        )
    )
    assert reviewed["computed_status"] == "supported"
    assert reviewed["reviewed_status"] == "unresolved"
    accept(case.client, case.iid, ev, {**case.base, "present": False})
    assert (
        case.client.patch(
            case.url + f"/findings/{finding['id']}/review",
            json={"version": reviewed["version"], "status": "supported", "reason": "stale"},
        ).status_code
        == 409
    )
    assert not ok(case.client.get(case.url + "/export"))["findings"]
    updated = case.reconcile()["presence"]
    assert updated["computed_status"] == "potentially_inconsistent"
    assert updated["reviewed_status"] is None
    export = ok(case.client.get(case.url + "/export"))
    assert len(export["finding_history"]) == 12
    events = export["review_events"]
    changes = [e for e in events if e["action"] == "evidence.analyst_correction"]
    assert len(changes) == 2
    assert changes[-1]["before"]["facts"]["present"] is True
    assert changes[-1]["after"]["facts"]["present"] is False
    assert all(e["author"] == "Test Analyst" for e in events)


def test_review_complete_can_include_unresolved_and_invalidates(case):
    findings = case.reconcile()
    assert case.client.post(case.url + "/review-complete", json={"reason": "Not ready"}).status_code == 409
    for f in findings.values():
        ok(
            case.client.patch(
                case.url + f"/findings/{f['id']}/review",
                json={
                    "version": f["version"],
                    "status": f["computed_status"],
                    "reason": "Reviewed missing evidence",
                },
            )
        )
    assert (
        ok(case.client.post(case.url + "/review-complete", json={"reason": "Review is complete"}))["state"]
        == "review_complete"
    )
    case.add("site_image", {**case.base, "present": True}, "presence")
    assert ok(case.client.get(case.url))["state"] == "active"


def test_follow_up_resolution_does_not_prove_claim(case):
    action = ok(
        case.client.post(
            case.url + "/follow-ups",
            json={
                "claim_id": case.claims["commissioning"]["id"],
                "request": "Certificate please",
                "reason": "Missing certificate",
            },
        )
    )
    ok(
        case.client.patch(
            case.url + f"/follow-ups/{action['id']}",
            json={
                "version": action["version"],
                "state": "resolved",
                "resolution": "Management replied",
                "reason": "Record reply",
            },
        )
    )
    assert case.reconcile()["commissioning"]["computed_status"] == "unresolved"


def test_integrity_failure_excludes_evidence_and_blocks_download(case):
    ev = case.add("site_image", {**case.base, "present": True}, "presence")
    assert case.reconcile()["presence"]["computed_status"] == "supported"
    path = case.client.app.state.store.files / ev["sha256"]
    path.write_bytes(b"tampered")
    assert case.client.get(case.url + f"/evidence/{ev['id']}/original").status_code == 409
    finding = case.reconcile()["presence"]
    assert finding["computed_status"] == "unresolved"
    assert "integrity" in finding["explanation"]


def test_cross_inspection_references_rejected(case):
    other = ok(case.client.post(PREFIX + "/inspections", json={"name": "Other", "site": "Plant B"}))["id"]
    ev = upload(case.client, other, "invoice", "other private evidence")
    assert case.client.get(case.url + f"/evidence/{ev['id']}").status_code == 404
    assert (
        case.client.post(
            case.url + "/evidence-links",
            json={
                "claim_id": case.claims["purchase"]["id"],
                "evidence_id": ev["id"],
                "relation": "supports",
                "locator": "page 1",
                "reason": "Wrong inspection",
            },
        ).status_code
        == 404
    )


def test_optimistic_lock_and_concurrent_updates(case):
    ev = upload(case.client, case.iid, "invoice", "original")
    payload = {
        "version": ev["version"],
        "text": "edited",
        "facts": {},
        "quality_flags": [],
        "confirmed": True,
        "reason": "Simultaneous edit",
    }

    def update():
        return case.client.patch(case.url + f"/evidence/{ev['id']}/correction", json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: update(), range(2))) == [200, 409]


def test_link_retraction_preserves_audit(case):
    case.add("site_image", {**case.base, "present": True}, "presence")
    assert case.reconcile()["presence"]["computed_status"] == "supported"
    snapshot = ok(case.client.get(case.url + "/export"))
    item = snapshot["evidence_links"][0]
    ok(
        case.client.post(
            case.url + f"/evidence-links/{item['id']}/retract",
            json={"version": item["version"], "reason": "Linked wrong image"},
        )
    )
    assert case.reconcile()["presence"]["computed_status"] == "unresolved"
    assert any(e["action"] == "link.retracted" for e in ok(case.client.get(case.url + "/review-events")))


def test_audit_events_immutable_at_database_level(case):
    store = case.client.app.state.store
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM review_events")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE review_events SET data='{}'")


def test_auth_roles_schema_and_extra_fields(client):
    assert client.get(PREFIX + "/inspections", headers={"Authorization": ""}).status_code == 401
    assert client.get("/openapi.json", headers={"Authorization": "Bearer bad"}).status_code == 401
    schema = ok(client.get("/openapi.json"))
    assert "EvidenceCorrection" in schema["components"]["schemas"]
    assert (
        client.post(
            PREFIX + "/inspections",
            headers={"Authorization": "Bearer " + JUDGE},
            json={"name": "x", "site": "y"},
        ).status_code
        == 403
    )
    assert (
        client.post(PREFIX + "/inspections", json={"name": "x", "site": "y", "author": "fake"}).status_code
        == 422
    )
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "filename,mime,content,code",
    [
        ("evil.html", "text/html", b"<script>bad</script>", 415),
        ("file.png", "image/png", b"not an image", 422),
        ("file.txt", "text/plain", b"\x00bad", 422),
        ("file.pdf", "application/pdf", b"%PDF-1.4 garbage", 422),
        ("file.png", "image/jpeg", b"bad", 415),
        ("file.txt", "text/plain", b"", 413),
    ],
)
def test_upload_validation(case, filename, mime, content, code):
    response = case.client.post(
        case.url + "/evidence",
        data={"kind": "invoice", "source": "Synthetic", "captured_at": CAPTURED, "reason": "Validation test"},
        files={"file": (filename, content, mime)},
    )
    assert response.status_code == code


def test_upload_size_limit_chunked(client):
    payload = b"a" * (13 * 1024 * 1024)
    response = client.post(PREFIX + "/inspections", content=iter([payload[:1000000], payload[1000000:]]))
    assert response.status_code == 413


def test_pdf_encrypted_and_page_limit(case):
    writer = PdfWriter()
    writer.add_page(PdfReader(io.BytesIO(pdf_bytes("test"))).pages[0])
    writer.encrypt("secret")
    encrypted = io.BytesIO()
    writer.write(encrypted)
    for data in [encrypted.getvalue(), pdf_bytes("test")]:
        response = case.client.post(
            case.url + "/evidence",
            data={
                "kind": "invoice",
                "source": "Synthetic",
                "captured_at": CAPTURED,
                "reason": "Validation test",
            },
            files={"file": ("file.pdf", data, "application/pdf")},
        )
        assert response.status_code == (422 if data == encrypted.getvalue() else 201)
    writer = PdfWriter()
    for _ in range(13):
        writer.add_blank_page(100, 100)
    output = io.BytesIO()
    writer.write(output)
    response = case.client.post(
        case.url + "/evidence",
        data={"kind": "invoice", "source": "Synthetic", "captured_at": CAPTURED, "reason": "Validation test"},
        files={"file": ("long.pdf", output.getvalue(), "application/pdf")},
    )
    assert response.status_code == 422


def test_real_pdf_text_extraction_and_correction(case):
    text = "serial: SYN-001\nmodel: DemoMill X3\nsite: Plant A\ninvoice_ref: INV-001\namount: 100000.00\ncurrency: INR"
    content = pdf_bytes(text)
    ev = upload(case.client, case.iid, "invoice", text, "../invoice.pdf", "application/pdf", content)
    assert ev["filename"] == "invoice.pdf"
    ev = ok(case.client.post(case.url + f"/evidence/{ev['id']}/extract", json={"reason": "Read actual PDF"}))
    assert ev["facts"]["serial"] == "SYN-001"
    assert ev["facts"]["amount"] == "100000.00"
    assert ev["confirmed"] is False
    assert ev["extraction_pages"][0]["page"] == 1
    assert ev["extraction_method"] == "pdf_text"
    corrected = accept(case.client, case.iid, ev, {**case.base, "amount": "99999.00"}, ["manual_correction"])
    assert corrected["sha256"] == hashlib.sha256(content).hexdigest()
    assert case.client.get(case.url + f"/evidence/{ev['id']}/original").content == content


def test_real_image_and_scanned_pdf_ocr(case):
    assert shutil.which("tesseract"), "Install tesseract to run the required OCR acceptance test"
    assert shutil.which("pdftoppm"), "Install poppler to run scanned PDF acceptance test"
    label = "serial: SYN-001\nmodel: DemoMill X3\nsite: Plant A"
    image = label_png(label)
    ev = upload(case.client, case.iid, "site_image", label, "label.png", "image/png", image)
    ev = ok(case.client.post(case.url + f"/evidence/{ev['id']}/extract", json={"reason": "Real local OCR"}))
    assert "SYN" in ev["text"] and ev["extraction_method"] == "tesseract"
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    stream = io.BytesIO()
    page = canvas.Canvas(stream, pagesize=(700, 350))
    page.drawImage(ImageReader(io.BytesIO(image)), 0, 0, 700, 350)
    page.save()
    ev = upload(case.client, case.iid, "invoice", label, "scan.pdf", "application/pdf", stream.getvalue())
    ev = ok(
        case.client.post(case.url + f"/evidence/{ev['id']}/extract", json={"reason": "Real scanned PDF OCR"})
    )
    assert ev["extraction_method"] == "tesseract"
    assert "SYN" in ev["text"]
    assert ev["confirmed"] is False


def test_missing_ocr_engine_and_timeout_are_manual_fallback(case, monkeypatch):
    import subprocess

    from app import extraction

    path = case.client.app.state.store.files / "image"
    path.write_bytes(label_png("serial: SYN-001"))
    monkeypatch.setenv("PATH", "/nonexistent")
    result = extract(path, "image/png")
    assert result["method"] == "failed" and "incomplete" in result["flags"]

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 55)

    monkeypatch.setattr(extraction.subprocess, "run", timeout)
    assert extract(path, "image/png")["method"] == "failed"


def test_conflicting_extracted_fields_require_manual_correction():
    facts, flags = parse_facts("serial: A\nserial: B")
    assert facts.serial is None and flags == ["incomplete"]


def test_fail_closed_configuration(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError):
        create_app(tmp_path, {})
    monkeypatch.setenv("CDI_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        create_app(tmp_path, TOKENS)


def test_explicit_cors(tmp_path, monkeypatch):
    monkeypatch.setenv("CDI_CORS_ORIGINS", "https://judge.example")
    with TestClient(create_app(tmp_path, TOKENS)) as client:
        response = client.options(
            PREFIX + "/inspections",
            headers={"Origin": "https://judge.example", "Access-Control-Request-Method": "POST"},
        )
        assert response.headers["access-control-allow-origin"] == "https://judge.example"
        denied = client.options(
            PREFIX + "/inspections",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert denied.status_code == 400


def test_asset_correction_resets_claims_and_preserves_history(case):
    case.add("equipment_register", case.base, "identity")
    assert case.reconcile()["identity"]["computed_status"] == "supported"
    payload = {k: case.asset[k] for k in ("tag", "serial", "model", "site", "invoice_ref", "payment_ref")}
    payload.update(serial="SYN-CORRECTED", version=case.asset["version"], reason="Correct declaration typo")
    ok(case.client.patch(case.url + f"/assets/{case.asset['id']}", json=payload))
    claims = ok(case.client.get(case.url + "/claims"))
    assert all(not c["confirmed"] for c in claims)
    assert next(c for c in claims if c["kind"] == "identity")["expected"] == "SYN-CORRECTED"
    assert all(f["computed_status"] == "not_assessed" for f in case.reconcile().values())
    events = ok(case.client.get(case.url + "/review-events"))
    event = next(e for e in events if e["action"] == "asset.corrected")
    assert event["before"]["serial"] == "SYN-001" and event["after"]["serial"] == "SYN-CORRECTED"


def test_purchase_missing_amount_is_incomplete(case):
    common = {**case.base, "invoice_ref": "INV-001"}
    case.add("invoice", common, "purchase")
    case.add("equipment_register", common, "purchase")
    assert case.reconcile()["purchase"]["computed_status"] == "partly_supported"


def test_support_and_conflicting_identifier_both_considered(case):
    case.add("site_image", case.base, "identity")
    case.add("equipment_register", {**case.base, "model": "Wrong model"}, "identity")
    assert case.reconcile()["identity"]["computed_status"] == "potentially_inconsistent"


def test_blank_ocr_is_flagged_unreadable(case):
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (300, 300), "white").save(stream, format="PNG")
    ev = upload(case.client, case.iid, "site_image", "", "blank.png", "image/png", stream.getvalue())
    ev = ok(
        case.client.post(
            case.url + f"/evidence/{ev['id']}/extract", json={"reason": "Check unreadable source"}
        )
    )
    assert ev["text"].strip() == ""
    assert "unreadable" in ev["quality_flags"]
    assert not ev["confirmed"]


def test_consistent_backup_restores_audit_and_originals(case, tmp_path):
    import os
    import subprocess
    import sys

    ev = case.add("site_image", {**case.base, "present": True}, "presence")
    case.reconcile()
    before = ok(case.client.get(case.url + "/export"))
    destination = tmp_path.parent / (tmp_path.name + "-backup")
    result = subprocess.run(
        [sys.executable, "-m", "scripts.backup", str(destination)],
        env={**os.environ, "CDI_DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "backup created" in result.stdout
    with TestClient(
        create_app(destination, TOKENS), headers={"Authorization": "Bearer " + JUDGE}
    ) as restored:
        after = ok(restored.get(case.url + "/export"))
        assert after["review_events"] == before["review_events"]
        assert after["findings"] == before["findings"]
        assert (
            hashlib.sha256(restored.get(case.url + f"/evidence/{ev['id']}/original").content).hexdigest()
            == ev["sha256"]
        )


def test_naive_future_and_blank_upload_metadata_rejected(case):
    for captured, source, reason in [
        ("2026-01-01T00:00:00", "Test", "Test"),
        ("2099-01-01T00:00:00Z", "Test", "Test"),
        (CAPTURED, " ", "Test"),
        (CAPTURED, "Test", " "),
    ]:
        response = case.client.post(
            case.url + "/evidence",
            data={"kind": "invoice", "source": source, "captured_at": captured, "reason": reason},
            files={"file": ("demo.txt", b"Synthetic", "text/plain")},
        )
        assert response.status_code == 422
