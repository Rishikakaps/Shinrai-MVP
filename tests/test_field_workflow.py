"""Real SQLite/files/OCR/ZXing/FFmpeg tests; Gemini fixtures are explicitly mocked."""

import hashlib
import io
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.identifiers import compare_scan, parse_fields
from app.main import create_app
from app.v2_models import CandidatePayload, CopilotOutput
from scripts.demo import CAPTURED, accept, upload
from tests.conftest import ANALYST, JUDGE, TOKENS
from tests.test_label_scan import qr
from tests.test_v2_backend import post, wav_bytes


@pytest.fixture
def field(case):
    c = post(
        case.client,
        "/api/v1/cases",
        {
            "inspection_id": case.iid,
            "company": "Synthetic field company",
            "site": "Plant A",
            "reason": "Field test",
        },
    )
    assert c.status_code == 201, c.text
    return case, "/api/v1/cases/" + c.json()["id"]


def session(field, **kwargs):
    case, root = field
    r = post(
        case.client,
        root + "/field-sessions",
        {
            "inspection_id": case.iid,
            "purpose": "identifier",
            "device": "Synthetic tablet",
            "intended_asset_id": case.asset["id"],
            "reason": "Start capture before binding",
            **kwargs,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def label(serial="SYN-001", code=None):
    image = Image.new("RGB", (1000, 650), "white")
    draw, font = ImageDraw.Draw(image), ImageFont.load_default(size=35)
    for index, text in enumerate(
        ["Manufacturer: Example Corp", "Model: DemoMill X3", "Serial: " + serial, "Site: Plant A"]
    ):
        draw.text((25, 30 + index * 55), text, fill="black", font=font)
    if code:
        image.paste(qr(code).convert("RGB"), (550, 275))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def capture(field, s, data=None, key=None):
    case, root = field
    return case.client.post(
        root + "/field-sessions/" + s["id"] + "/captures",
        data={
            "metadata": json.dumps(
                {"captured_at": CAPTURED, "reason": "Deliberate synthetic evidence capture"}
            )
        },
        files={"file": ("label.png", data or label(code="SYN-001"), "image/png")},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def test_source_conflicts_partial_and_no_guessing():
    raw = {"ocr_text": "Serial: XR400-00192", "codes": [{"text": "XR400-00182", "format": "Code128"}]}
    result = compare_scan(raw, {"serial": "XR400-00192"})
    assert result["decision"] == "CONFLICTING_SOURCES"
    assert result["observed_fields"]["serial"] is None
    raw["ocr_text"] = "Serial: XR400-0019?"
    raw["codes"] = []
    assert parse_fields(raw["ocr_text"])["serial"] == ["XR400-0019?"]
    result = compare_scan(raw, {"serial": "XR400-00192"})
    assert result["decision"] == "PARTIAL_IDENTIFIER"
    assert result["observed_fields"]["serial"] == "XR400-0019?"
    raw = {"ocr_text": "Serial: axO1", "codes": []}
    assert compare_scan(raw, {"serial": "ax01"})["decision"] == "IDENTIFIER_MISMATCH"
    raw = {"codes": [{"text": "https://example.test/SYN-001", "format": "QRCode"}]}
    assert compare_scan(raw, {"serial": "SYN-001"})["decision"] == "NO_IDENTIFIER_FOUND"


def test_preview_is_bounded_ephemeral_scoped_and_retry_safe(field):
    case, root = field
    before = case.reconcile()
    s = session(field)
    original_count = len(list(case.client.app.state.store.files.iterdir()))
    stream = io.BytesIO()
    Image.new("RGB", (320, 240), "gray").save(stream, format="JPEG")
    url = root + "/field-sessions/" + s["id"] + "/preview?sequence=0"
    first = case.client.post(url, content=stream.getvalue())
    assert first.status_code == 200, first.text
    assert case.client.post(url, content=stream.getvalue()).json()["duplicate"]
    assert (
        case.client.post(url.replace("sequence=0", "sequence=1"), content=stream.getvalue()).status_code
        == 429
    )
    state = case.client.get(root + "/field-sessions/" + s["id"]).json()
    assert state["transport"]["received_samples"] == 1
    assert state["transport"]["state"] == "CONNECTED"
    assert len(list(case.client.app.state.store.files.iterdir())) == original_count
    assert case.reconcile() == before
    assert case.client.post(url, content=b"bad").status_code == 422
    assert case.client.post(url, content=b"x" * (256 * 1024 + 1)).status_code == 413
    case.client.headers["Authorization"] = "Bearer " + JUDGE
    assert case.client.post(url, content=stream.getvalue()).status_code == 403


def test_real_capture_review_binding_retry_restart_and_retrieval(field):
    case, root = field
    s, retry_key = session(field), str(uuid4())
    content = label(code="SYN-001")
    response = capture(field, s, content, retry_key)
    assert response.status_code == 201, response.text
    c = response.json()
    assert c["raw_result"]["ocr_fields"]["serial"] == ["SYN-001"]
    assert c["comparison"]["decision"] == "MATCH_CANDIDATE", c
    assert not case.client.get(case.url + "/evidence/" + c["evidence_id"]).json()["confirmed"]
    assert capture(field, s, content, retry_key).json()["id"] == c["id"]
    assert capture(field, s, label(serial="SYN-999"), retry_key).status_code == 409
    url = root + "/visual-captures/" + c["id"] + "/review"
    body = {
        "version": c["version"],
        "action": "accept",
        "fields": c["working_fields"],
        "checked_original": False,
        "reason": "Checked the synthetic plate",
    }
    assert case.client.patch(url, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code == 422
    body["checked_original"] = True
    review_key = str(uuid4())
    r = case.client.patch(url, json=body, headers={"Idempotency-Key": review_key})
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted["state"] == "ACCEPTED" and accepted["physical_asset_id"]
    assert accepted["raw_result"] == c["raw_result"]
    assert case.client.patch(url, json=body, headers={"Idempotency-Key": review_key}).json()["id"] == c["id"]
    assert len(case.client.get(root + "/physical-assets").json()) == 1
    original_url = case.url + "/evidence/" + c["evidence_id"] + "/original"
    assert hashlib.sha256(case.client.get(original_url).content).digest() == hashlib.sha256(content).digest()
    with TestClient(
        create_app(case.client.app.state.store.root, TOKENS), headers={"Authorization": "Bearer " + ANALYST}
    ) as restarted:
        assert restarted.get(root + "/visual-captures").json()[0]["state"] == "ACCEPTED"
        assert (
            restarted.get(root + "/field-sessions/" + s["id"]).json()["transport"]["state"] == "INTERRUPTED"
        )
        assert restarted.get(original_url).content == content
        assert "Visual identity" in restarted.get(root + "/report").text


def test_conflict_requires_explicit_resolution_and_raw_is_immutable(field):
    case, root = field
    s = session(field)
    response = capture(field, s, label(code="SYN-999"))
    assert response.status_code == 201, response.text
    c = response.json()
    assert c["comparison"]["decision"] == "CONFLICTING_SOURCES"
    body = {
        "version": c["version"],
        "action": "accept",
        "fields": {**case.base, "manufacturer": "Example Corp"},
        "checked_original": True,
        "reason": "Resolve conflicting synthetic code by explicit analyst review",
    }
    url = root + "/visual-captures/" + c["id"] + "/review"
    assert case.client.patch(url, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code == 422
    assert case.client.get(root + "/physical-assets").json() == []
    body["acknowledge_conflicts"] = True
    r = case.client.patch(url, json=body, headers={"Idempotency-Key": str(uuid4())})
    assert r.status_code == 200, r.text
    assert r.json()["raw_result"] == c["raw_result"]


def test_processor_failure_retains_original_and_retry_record(field, monkeypatch):
    def fail(*args):
        raise HTTPException(503, "Synthetic OCR failure")

    monkeypatch.setattr("app.field_routes.scan_file", fail)
    case, root = field
    c = capture(field, session(field)).json()
    assert c["state"] == "PROCESSING_FAILED"
    assert case.client.get(case.url + "/evidence/" + c["evidence_id"] + "/original").status_code == 200
    assert case.client.get(root + "/physical-assets").json() == []


def test_documentary_quantity_does_not_create_physical_identities(field):
    case, root = field
    ev = upload(case.client, case.iid, "invoice", "SYNTHETIC invoice\nQuantity: 400\nSupplier: Example Corp")
    ev = accept(case.client, case.iid, ev, case.base)
    body = {
        "inspection_id": case.iid,
        "proposition": "400 machines purchased",
        "verification_plan": "Review supplier invoice and register quantity; no physical inspection of all units",
        "declared_quantity": 400,
        "supported_quantity": 400,
        "evidence_ids": [ev["id"]],
        "locator": "Invoice page 1, quantity row",
        "status": "DOCUMENTARILY_SUPPORTED",
        "checked_originals": True,
        "reason": "Analyst reviewed documentary assertion only",
    }
    r = post(case.client, root + "/documentary-reviews", body)
    assert r.status_code == 201, r.text
    assert r.json()["verification_basis"] == "DOCUMENTARY"
    assert case.client.get(root + "/physical-assets").json() == []
    result = case.client.get(root + "/documentary-reviews").json()[0]
    assert result["source_current"] and not result["physically_verified"]
    accept(case.client, case.iid, ev, case.base)
    assert not case.client.get(root + "/documentary-reviews").json()[0]["source_current"]


def test_company_interview_original_transcript_and_source_edit(field):
    case, root = field
    s = session(field, purpose="interview", intended_asset_id=None)
    metadata = {
        "inspection_id": case.iid,
        "capture_type": "interview_speech",
        "field_session_id": s["id"],
        "captured_at": CAPTURED,
        "device": "Synthetic tablet",
        "operating_mode": "interview",
        "note": "Synthetic generated tone, not real speech",
        "consent_confirmed": True,
        "consent_note": "Synthetic test authorized",
        "reason": "Preserve source",
    }
    upload_response = case.client.post(
        root + "/audio",
        data={"metadata": json.dumps(metadata)},
        files={"file": ("interview.wav", wav_bytes(), "audio/wav")},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert upload_response.status_code == 201, upload_response.text
    audio = upload_response.json()
    closed = case.client.patch(
        root + "/field-sessions/" + s["id"],
        json={"version": s["version"], "state": "CLOSED", "reason": "Recording saved; process later"},
    )
    assert closed.status_code == 200
    i = post(
        case.client,
        root + "/interviews",
        {
            "inspection_id": case.iid,
            "speaker_label": "Analyst-entered CFO label",
            "consent_confirmed": True,
            "consent_note": "Synthetic fixture",
            "reason": "Company interview without fabricated machine",
        },
    ).json()

    class MockProvider:
        name, model = "mock_test", "mock_test"

        def transcribe(self, *args):
            return "We did not reduce downtime; repair cost was 8000000 JPY.", None

        def analyse(self, text, context):
            return CopilotOutput(
                questions=[],
                candidates=[
                    CandidatePayload(
                        kind="reported_issue",
                        text="Reported repair cost",
                        quote="repair cost was 8000000 JPY.",
                    )
                ],
            )

    case.client.app.state.ai = MockProvider()
    response = post(
        case.client,
        root + "/audio/" + audio["id"] + "/transcribe",
        {"interview_id": i["id"], "language": "en", "reason": "Explicit mocked speech adapter test"},
    )
    assert response.status_code == 201, response.text
    segment = response.json()
    assert "did not" in segment["text"] and segment["provider_text"] == segment["text"]
    analysis = post(
        case.client,
        root + "/segments/" + segment["id"] + "/analyse",
        {"reason": "Explicit mocked proposal test"},
    )
    assert analysis.status_code == 201, analysis.text
    candidate = case.client.get(root + "/candidates").json()[0]
    r = post(
        case.client,
        root + "/candidates/" + candidate["id"] + "/confirm",
        {
            "version": candidate["version"],
            "action": "accept",
            "confirmed_source": True,
            "reason": "Accept as attributed report, not independent verification",
        },
    )
    assert r.status_code == 200, r.text
    edited = case.client.patch(
        root + "/segments/" + segment["id"],
        json={
            "version": segment["version"],
            "text": "Corrected: repair cost is uncertain.",
            "language": "en",
            "recording_id": segment["recording_id"],
            "start_ms": segment["start_ms"],
            "end_ms": segment["end_ms"],
            "mode": segment["mode"],
            "reason": "Correct uncertain reported amount",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["provider_text"] == segment["text"]
    assert not case.client.get(root + "/candidates").json()[0]["source_current"]
    assert case.client.get(root + "/export").json()["statements"][0]["requires_review"]
    case.client.headers["Authorization"] = "Bearer " + JUDGE
    assert case.client.get(root + "/audio/" + audio["id"] + "/original").status_code == 403


def test_field_login_redirect_and_cross_case_isolation(field):
    case, _root = field
    s = session(field)
    other = post(case.client, "/api/v1/inspections", {"name": "Other", "site": "Other"}).json()
    other_case = post(
        case.client,
        "/api/v1/cases",
        {"inspection_id": other["id"], "company": "Other", "site": "Other", "reason": "Isolation"},
    ).json()
    assert (
        case.client.get("/api/v1/cases/" + other_case["id"] + "/field-sessions/" + s["id"]).status_code == 404
    )
    with TestClient(create_app(case.client.app.state.store.root, TOKENS)) as browser:
        result = browser.get("/field-test", follow_redirects=False)
        assert result.status_code == 303 and result.headers["location"] == "/login?next=/field-test"


def test_unknown_target_can_be_reviewed_later_and_closed_session_refuses_capture(field):
    case, root = field
    s = session(field, intended_asset_id=None)
    c = capture(field, s).json()
    assert c["intended_asset_id"] is None and c["physical_asset_id"] is None
    response = case.client.patch(
        root + "/visual-captures/" + c["id"] + "/review",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "version": c["version"],
            "action": "accept",
            "checked_original": True,
            "fields": {**case.base, "manufacturer": "Example Corp"},
            "intended_asset_id": case.asset["id"],
            "reason": "Selected target after reading original",
        },
    )
    assert response.status_code == 200, response.text
    latest = case.client.get(root + "/field-sessions/" + s["id"]).json()["session"]
    closed = case.client.patch(
        root + "/field-sessions/" + s["id"],
        json={"version": latest["version"], "state": "CLOSED", "reason": "Close device session"},
    )
    assert closed.status_code == 200
    assert capture(field, s).status_code == 409


def test_stale_capture_and_changed_upload_metadata_are_rejected(field):
    case, root = field
    s, retry_key = session(field), str(uuid4())
    c = capture(field, s, key=retry_key).json()
    r = case.client.post(
        root + "/field-sessions/" + s["id"] + "/captures",
        data={
            "metadata": json.dumps(
                {"captured_at": CAPTURED, "reason": "Deliberate synthetic evidence capture"}
            )
        },
        files={"file": ("different.png", label(code="SYN-001"), "image/png")},
        headers={"Idempotency-Key": retry_key},
    )
    assert r.status_code == 409
    url = root + "/visual-captures/" + c["id"] + "/review"
    body = {
        "version": c["version"],
        "action": "correct",
        "fields": c["working_fields"],
        "reason": "Preserve analyst working correction",
    }
    assert case.client.patch(url, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code == 200
    body["action"] = "accept"
    body["checked_original"] = True
    assert case.client.patch(url, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code == 409


def test_scanner_concurrency_is_bounded():
    from app.label_scan import SCAN_SLOTS, scan_file

    assert SCAN_SLOTS.acquire(blocking=False)
    assert SCAN_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as error:
            scan_file("unused")
        assert error.value.status_code == 429
    finally:
        SCAN_SLOTS.release()
        SCAN_SLOTS.release()


def test_translation_retries_preserve_first_provider_output_and_manual_provenance(field):
    case, root = field
    interview = post(
        case.client,
        root + "/interviews",
        {
            "inspection_id": case.iid,
            "speaker_label": "Analyst-attributed manager",
            "consent_confirmed": True,
            "consent_note": "Synthetic authorized test",
            "reason": "Company interview",
        },
    ).json()
    segment = post(
        case.client,
        root + "/interviews/" + interview["id"] + "/segments",
        {
            "text": "停止時間は減っていません。",
            "language": "ja",
            "mode": "manual",
            "reason": "Human-entered synthetic original",
        },
    ).json()

    class MockTranslation:
        name = "mock_translation"
        output = "Downtime did not decrease."

        def translate(self, text):
            return self.output

    provider = MockTranslation()
    case.client.app.state.ai = provider
    url = root + "/segments/" + segment["id"]
    first = case.client.post(
        url + "/translate", json={"version": segment["version"], "reason": "Mock provider translation"}
    ).json()
    provider.output = "Reported downtime has not decreased."
    second = case.client.post(
        url + "/translate", json={"version": first["version"], "reason": "Explicit translation retry"}
    ).json()
    assert second["provider_translation"] == first["english_translation"]
    assert second["english_translation"] == provider.output
    edited = case.client.patch(
        url,
        json={
            "version": second["version"],
            "text": "訂正：まだ減っていません。",
            "language": "ja",
            "mode": "manual",
            "reason": "Human correction of human source",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["provider_text"] is None
    assert edited.json()["provider_translation"] == first["english_translation"]


def test_project_followup_without_fabricated_machine_uses_existing_tracker(field):
    case, root = field
    source = {
        "kind": "management_report",
        "attribution": "Analyst-entered manager",
        "quote": "Considering expansion",
    }
    project = post(
        case.client,
        root + "/investments",
        {
            "inspection_id": case.iid,
            "title": "Reported expansion",
            "kind": "expansion",
            "rationale": source["quote"],
            "source": source,
            "reason": "Record proposal without inventing a physical machine",
        },
    )
    assert project.status_code == 201, project.text
    response = post(
        case.client,
        root + "/follow-ups",
        {
            "inspection_id": case.iid,
            "project_id": project.json()["id"],
            "request": "Obtain approved expansion budget",
            "contact": "Reported manager",
            "reviewer": "Test Analyst",
            "due_date": "2026-10-28",
            "required_evidence": "Accepted approved budget with project locator",
            "verification_method": "document_review",
            "source": source,
            "reason": "Use existing follow-up tracker",
        },
    )
    assert response.status_code == 201, response.text
    follow_up = response.json()
    assert follow_up["details"]["physical_asset_id"] is None
    transition = post(
        case.client,
        root + "/follow-ups/" + follow_up["task"]["id"] + "/transition",
        {
            "version": follow_up["details"]["version"],
            "status": "awaiting_information",
            "reason": "Await requested documentary record",
        },
    )
    assert transition.status_code == 200, transition.text
    assert case.client.get(root + "/physical-assets").json() == []


def test_real_code128_and_ocr_keep_distinct_sources(field):
    import zxingcpp

    code = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("SYN-001", zxingcpp.BarcodeFormat.Code128), scale=3
    )
    barcode = Image.frombytes("L", (code.shape[1], code.shape[0]), bytes(code)).convert("RGB")
    image = Image.open(io.BytesIO(label()))
    assert barcode.width < image.width
    image.paste(barcode, (30, 300))
    content = io.BytesIO()
    image.save(content, format="PNG")
    response = capture(field, session(field), data=content.getvalue())
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["raw_result"]["ocr_fields"]["serial"] == ["SYN-001"]
    assert any(c["text"] == "SYN-001" and "128" in c["format"] for c in result["raw_result"]["codes"])
    assert {s["source"] for s in result["comparison"]["sources"]} == {"ocr", "barcode"}
    assert result["comparison"]["decision"] == "MATCH_CANDIDATE"
