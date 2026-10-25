import io
from datetime import UTC, datetime

from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.intake_models import IntakeUpload
from scripts.demo import ok
from scripts.seed_motors import import_motors


def setup(case):
    c = case.client
    case_id = ok(
        c.post(
            "/api/v1/cases",
            headers={"Idempotency-Key": "registry-test-case"},
            json={
                "inspection_id": case.iid,
                "company": "Synthetic test",
                "site": "Plant A",
                "reason": "Test",
            },
        )
    )["id"]
    c.app.state.intake.stop()
    return case_id


def upload(case, case_id, data, name="test.txt", media="text/plain"):
    body = IntakeUpload(
        case_id=case_id,
        inspection_id=case.iid,
        captured_at=datetime.now(UTC),
        reason="Test",
        synthetic_demo=True,
    )
    item = case.client.app.state.intake.upload(
        body,
        UploadFile(io.BytesIO(data), filename=name, headers=Headers({"content-type": media})),
        "Test Analyst",
        name,
    )
    case.client.app.state.intake.run_once()
    return case.client.get("/api/evidence/" + item.id + "/processing-status").json()["intake"]


def test_motor_import_and_edit(client):
    result = import_motors(client)
    assert result["assets"] == 40 and result["claims"] == 240 and result["missing_serials"] == 14
    assert import_motors(client) == result
    url = f"/api/v1/inspections/{result['inspection_id']}"
    report = client.get(url + "/export").json()
    a = report["assets"][0]
    assert a["serial"] is None and not any(c["confirmed"] for c in report["claims"])
    body = {k: v for k, v in a.items() if k not in {"id", "inspection_id", "created_at"}}
    body.update(manufacturer="Reviewed maker", reason="Read original")
    assert client.patch(url + "/assets/" + a["id"], json=body).status_code == 200
    assert client.patch(url + "/assets/" + a["id"], json=body).status_code == 409
    saved = client.get(url + "/export").json()["assets"][0]
    renamed = {k: v for k, v in saved.items() if k not in {"id", "inspection_id", "created_at"}}
    renamed.update(tag="MTR-REVIEWED-001", reason="Reviewed internal tag")
    assert client.patch(url + "/assets/" + saved["id"], json=renamed).status_code == 200
    assert import_motors(client)["assets"] == 40
    events = client.get(url + "/review-events").json()
    assert any(
        e["action"] == "asset.corrected" and e["after"]["manufacturer"] == "Reviewed maker" for e in events
    )


def test_reviewed_create_update_and_no_auto_support(case):
    cid = setup(case)
    c = case.client
    item = upload(case, cid, b"Serial: NEW-44\nModel: NEW-MODEL\nManufacturer: Maker")
    assert item["processing_status"] == "needs_review"
    body = {
        "version": item["version"],
        "action": "create",
        "fields": {
            "tag": "NEW-44",
            "serial": "NEW-44",
            "model": "NEW-MODEL",
            "site": "Plant A",
            "reason": "Checked source",
        },
        "checked_original": True,
        "reason": "New source declaration",
    }
    url = "/api/evidence/" + item["id"] + "/registry-proposal"
    assert c.post(url, json=body).status_code == 422
    body["acknowledge_conflicts"] = True
    response = c.post(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["evidence_accepted"] is False
    assert c.post(url, json=body).status_code == 409
    report = c.get(case.url + "/export").json()
    assert len(report["assets"]) == 2 and len(report["claims"]) == 12
    assert not next(e for e in report["evidence"] if e["id"] == item["evidence_id"])["confirmed"]
    assert not report["reconciliation_current"]
    item2 = upload(
        case, cid, b"Serial: SYN-001\nModel: DemoMill X3\nManufacturer: Updated Maker", name="update.txt"
    )
    body.update(
        version=item2["version"],
        action="update",
        target_id=case.asset["id"],
        target_version=case.asset["version"],
        fields={
            "tag": "CNC-001",
            "serial": "SYN-001",
            "model": "DemoMill X3",
            "site": "Plant A",
            "manufacturer": "Updated Maker",
            "reason": "Read source",
        },
    )
    response = c.post("/api/evidence/" + item2["id"] + "/registry-proposal", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["asset"]["manufacturer"] == "Updated Maker"


def test_adjusted_image_same_pipeline_preserves_source(case):
    cid = setup(case)
    c = case.client
    data = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(data, "PNG")
    item = upload(case, cid, data.getvalue(), "source.png", "image/png")
    url = "/api/evidence/" + item["id"] + "/adjust-image"
    body = {
        "version": item["version"],
        "crop": [20, 20, 200, 100],
        "rotate": 90,
        "autocontrast": True,
        "reason": "Plate crop",
    }
    response = c.post(url, json=body)
    assert response.status_code == 201, response.text
    child = response.json()
    assert child["metadata"]["parent_intake_id"] == item["id"]
    assert child["metadata"]["adjustment"]["crop"] == body["crop"]
    assert c.get("/api/evidence/" + item["id"] + "/original").content == data.getvalue()
    adjusted = c.get("/api/evidence/" + child["id"] + "/original").content
    assert Image.open(io.BytesIO(adjusted)).size == (80, 180)
    body["crop"] = [0, 0, 999, 500]
    assert c.post(url, json=body).status_code == 422


def test_unknown_serial_does_not_support(case):
    c = case.client
    a = case.asset
    assert (
        c.patch(
            case.url + "/assets/" + a["id"],
            json={
                "tag": a["tag"],
                "serial": None,
                "model": a["model"],
                "site": a["site"],
                "version": a["version"],
                "reason": "Unknown serial",
            },
        ).status_code
        == 200
    )
    for cl in c.get(case.url + "/claims").json():
        c.patch(
            case.url + f"/claims/{cl['id']}/confirmation",
            json={
                "version": cl["version"],
                "expected": cl["expected"],
                "confirmed": True,
                "reason": "Review scope",
            },
        )
    case.add("site_image", {"model": a["model"], "site": a["site"], "present": True}, "presence")
    results = c.post(case.url + "/reconcile", json={"reason": "Check missing identity"}).json()
    assert not any(f["computed_status"] == "supported" for f in results)


def test_video_adjustment_keeps_timestamp_and_real_ocr(case, tmp_path):
    import subprocess

    from PIL import ImageDraw, ImageFont

    cid = setup(case)
    image = Image.new("RGB", (1200, 700), "white")
    font = ImageFont.truetype("app/fonts/NotoSansJP.ttf", 40)
    ImageDraw.Draw(image).multiline_text(
        (45, 60),
        "SYNTHETIC DEMO\nSerial: SYN-001\nModel: DemoMill X3\nSite: Plant A",
        font=font,
        fill="black",
        spacing=20,
    )
    path = tmp_path / "label.png"
    image.save(path)
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(path),
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "1",
            "-y",
            str(video),
        ],
        check=True,
        timeout=20,
    )
    body = IntakeUpload(
        case_id=cid,
        inspection_id=case.iid,
        captured_at=datetime.now(UTC),
        recording_authorized=True,
        synthetic_demo=True,
        reason="Synthetic clip",
    )
    item = case.client.app.state.intake.upload(
        body,
        UploadFile(
            io.BytesIO(video.read_bytes()),
            filename="clip.mp4",
            headers=Headers({"content-type": "video/mp4"}),
        ),
        "Test Analyst",
        "video-trial",
    )
    case.client.app.state.intake.run_once()
    item = case.client.get("/api/evidence/" + item.id + "/processing-status").json()["intake"]
    assert item["processing_status"] == "needs_review"
    assert "SYN-001" in item["raw_result"]["text"]
    page = item["raw_result"]["pages"][0]
    response = case.client.post(
        "/api/evidence/" + item["id"] + "/adjust-image",
        json={
            "version": item["version"],
            "frame_number": page["page"],
            "crop": [20, 20, 1000, 500],
            "rotate": 0,
            "reason": "Crop label from timestamped video",
        },
    )
    assert response.status_code == 201, response.text
    child = response.json()
    assert child["metadata"]["source_timestamp_seconds"] == page["timestamp"]
    assert child["metadata"]["source_frame_sha256"] == page["frame"]["sha256"]
    assert child["processing_status"] == "queued"
    case.client.app.state.intake.run_once()
    child = case.client.get("/api/evidence/" + child["id"] + "/processing-status").json()["intake"]
    assert "SYN-001" in child["raw_result"]["text"]
    assert child["resolution"]["decision"] == "EXACT_SERIAL_CANDIDATE"


def test_mp3_real_decode(tmp_path):
    import subprocess

    from app.v2_media import process_audio

    path = tmp_path / "synthetic.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-y",
            str(path),
        ],
        check=True,
        timeout=20,
    )
    result = process_audio(path.read_bytes(), "synthetic.mp3", "audio/mpeg")
    assert result["duration_seconds"] > 0


def test_serial_alias_retains_source_span():
    from app.intake_understanding import extract_fields

    fields = extract_fields([{"page": 1, "text": "Ser No.:FM 14015624040001", "method": "tesseract"}])
    serial = next(f for f in fields if f["name"] == "serial_number")
    assert serial["value"] == "FM 14015624040001"
    assert serial["source_text"] == "Ser No.:FM 14015624040001"


def test_phone_scan_queues_same_saved_original(case):
    setup(case)
    data = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(data, "PNG")
    response = case.client.post(
        case.url + "/evidence",
        files={"file": ("phone.png", data.getvalue(), "image/png")},
        data={
            "kind": "site_image",
            "source": "Synthetic phone pipeline test",
            "captured_at": datetime.now(UTC).isoformat(),
            "reason": "Preserve phone original",
        },
    )
    assert response.status_code == 201, response.text
    evidence = response.json()
    scanned = case.client.post(
        case.url + "/evidence/" + evidence["id"] + "/scan-label",
        json={"asset_id": case.asset["id"], "reason": "Deliberate phone scan"},
    )
    assert scanned.status_code == 200, scanned.text
    intake_id = scanned.json()["intake_id"]
    status = case.client.get("/api/evidence/" + intake_id + "/processing-status").json()
    assert status["intake"]["evidence_id"] == evidence["id"]
    assert status["intake"]["processing_status"] == "queued"
    assert status["evidence"]["confirmed"] is False
    assert case.client.get("/api/evidence/" + intake_id + "/original").content == data.getvalue()
