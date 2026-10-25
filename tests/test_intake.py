import hashlib
import io
import subprocess
from datetime import UTC, datetime

from PIL import Image

from app.intake import resolve
from app.models import Asset
from scripts.seed_motors import import_motors


def test_import_nullable_audited_and_idempotent(client):
    result = import_motors(client)
    assert result["assets"] == 40 and result["claims"] == 240
    assert result["missing_serials"] == 14 and result["supported"] == 0
    assert import_motors(client) == result
    url = f"/api/v1/inspections/{result['inspection_id']}"
    report = client.get(url + "/export").json()
    assert not any(c["confirmed"] for c in report["claims"])
    a = report["assets"][0]
    changed = {k: v for k, v in a.items() if k not in {"id", "inspection_id", "created_at"}}
    changed.update(manufacturer="Reviewed manufacturer", reason="Checked source label")
    response = client.patch(url + "/assets/" + a["id"], json=changed)
    assert response.status_code == 200, response.text
    assert client.patch(url + "/assets/" + a["id"], json=changed).status_code == 409
    events = client.get(url + "/review-events").json()
    event = next(e for e in reversed(events) if e["action"] == "asset.corrected")
    assert event["before"]["manufacturer"] != event["after"]["manufacturer"]
    assert event["after"]["serial"] is None


def intake(client, url, content, name="source.txt", media="text/plain", key="upload-1"):
    response = client.post(
        url + "/intake",
        headers={"Idempotency-Key": key},
        files={"file": (name, content, media)},
        data={
            "source": "Synthetic test",
            "captured_at": datetime.now(UTC).isoformat(),
            "reason": "Test source",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_intake_ocr_proposal_and_reconciliation(case):
    c, url = case.client, case.url
    text = b"SYNTHETIC commissioning certificate\nSerial: SYN-001\nModel: DemoMill X3\nSite: Plant A\nCommissioned: true"
    item = intake(c, url, text)
    item = c.post(url + f"/intake/{item['id']}/process", json={"reason": "Extract source"}).json()
    assert item["decision"] == "CANDIDATE_NEEDS_REVIEW"
    assert item["raw_extraction"]["fields"]["serial"] == ["SYN-001"]
    body = {
        "version": item["version"],
        "action": "update",
        "target_id": case.asset["id"],
        "target_version": case.asset["version"],
        "fields": {
            "tag": "CNC-001",
            "serial": "SYN-001",
            "model": "DemoMill X3",
            "site": "Plant A",
            "manufacturer": "Demo Maker",
            "reason": "Read source",
        },
        "reason": "Reviewed source",
        "checked_original": True,
    }
    response = c.post(url + f"/intake/{item['id']}/review", json=body)
    assert response.status_code == 200, response.text
    assert c.post(url + f"/intake/{item['id']}/review", json=body).status_code == 409
    report = c.get(url + "/export").json()
    assert report["assets"][0]["manufacturer"] == "Demo Maker"
    assert not report["reconciliation_current"]
    assert report["evidence_links"][-1]["relation"] == "context"
    assert report["evidence"][0]["confirmed"] is False
    assert not any(cl["confirmed"] for cl in report["claims"])
    assert c.get(url + f"/evidence/{item['evidence_id']}/original").content == text
    assert report["evidence"][0]["sha256"] == hashlib.sha256(text).hexdigest()


def test_unknown_new_record_conflict_and_scope(case):
    c, url = case.client, case.url
    item = intake(c, url, b"Serial: UNKNOWN-44\nModel: NEW-MODEL\nManufacturer: Maker")
    item = c.post(url + f"/intake/{item['id']}/process", json={"reason": "Extract"}).json()
    assert item["decision"] == "UNKNOWN_IDENTIFIER"
    body = {
        "version": item["version"],
        "action": "create",
        "fields": {
            "tag": "NEW-44",
            "serial": "UNKNOWN-44",
            "model": "NEW-MODEL",
            "site": "Plant A",
            "reason": "New source record",
        },
        "checked_original": True,
        "reason": "Source reviewed; new machine declaration",
    }
    assert c.post(url + f"/intake/{item['id']}/review", json=body).status_code == 422
    body["acknowledge_conflicts"] = True
    assert c.post(url + f"/intake/{item['id']}/review", json=body).status_code == 200
    assert len(c.get(url + "/claims").json()) == 12
    iid = c.post("/api/v1/inspections", json={"name": "Other", "site": "B"}).json()["id"]
    assert (
        c.post(
            f"/api/v1/inspections/{iid}/intake/{item['id']}/process", json={"reason": "Scope test"}
        ).status_code
        == 404
    )


def test_matcher_same_model_conflicts_and_missing():
    assets = [
        Asset(inspection_id="i", tag="A", model="Same", serial="S-1", site="X"),
        Asset(inspection_id="i", tag="B", model="Same", serial="S-2", site="X"),
        Asset(inspection_id="i", tag="C", model="Same", site="X"),
    ]
    assert resolve(assets, {"model": ["Same"]})[0] == "MODEL_ONLY_REVIEW"
    assert resolve(assets, {"serial": ["S-1"], "asset_id": ["B"]})[0] == "CONFLICT"
    assert resolve(assets, {"serial": ["S-1", "S-2"]})[0] == "CONFLICTING_OR_PARTIAL"
    assert resolve(assets, {"serial": ["S-?"]})[0] == "CONFLICTING_OR_PARTIAL"
    assert resolve(assets, {"serial": ["UNKNOWN"]})[0] == "UNKNOWN_IDENTIFIER"
    assert resolve(assets, {}) == ("UNASSIGNED", [])


def test_transform_original_and_bounds(case):
    output = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(output, "PNG")
    item = intake(case.client, case.url, output.getvalue(), "source.png", "image/png")
    url = case.url + f"/intake/{item['id']}/transform"
    body = {
        "version": item["version"],
        "crop": [20, 20, 200, 100],
        "rotate": 90,
        "autocontrast": True,
        "reason": "Improve plate view",
    }
    response = case.client.post(url, json=body)
    assert response.status_code == 201, response.text
    child = response.json()
    assert child["parent_id"] == item["id"] and child["transform"]["crop"] == body["crop"]
    original = case.client.get(case.url + f"/evidence/{item['evidence_id']}/original").content
    assert original == output.getvalue()
    content = case.client.get(case.url + f"/evidence/{child['evidence_id']}/original").content
    assert Image.open(io.BytesIO(content)).size == (80, 180)
    body["crop"] = [0, 0, 999, 500]
    assert case.client.post(url, json=body).status_code == 422


def test_real_video_decode_ocr_and_idempotent_process(case, tmp_path):
    image = tmp_path / "plate.png"
    from PIL import ImageDraw, ImageFont

    im = Image.new("RGB", (1280, 720), "white")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 48)
    d.multiline_text(
        (60, 80),
        "SYNTHETIC DEMO\nSerial: SYN-001\nModel: DemoMill X3\nSite: Plant A",
        fill="black",
        font=font,
        spacing=25,
    )
    im.save(image)
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(image),
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
    item = intake(case.client, case.url, video.read_bytes(), "clip.mp4", "video/mp4")
    response = case.client.post(
        case.url + f"/intake/{item['id']}/process", json={"reason": "Decode real fixture"}
    )
    assert response.status_code == 200, response.text
    parent = response.json()
    children = [i for i in case.client.get(case.url + "/intake").json() if i["parent_id"] == item["id"]]
    assert len(children) == 6
    assert any("SYN-001" in i["raw_extraction"]["text"] for i in children)
    assert all(i["timestamp_seconds"] is not None for i in children)
    assert (
        case.client.post(case.url + f"/intake/{item['id']}/process", json={"reason": "Retry"}).json()
        == parent
    )
    assert len(case.client.get(case.url + "/intake").json()) == 7


def test_empty_serial_never_supports_claim(case):
    c, url = case.client, case.url
    a = case.asset
    response = c.patch(
        url + "/assets/" + a["id"],
        json={
            "tag": a["tag"],
            "serial": None,
            "model": a["model"],
            "site": a["site"],
            "version": a["version"],
            "reason": "Serial unknown",
        },
    )
    assert response.status_code == 200
    claims = c.get(url + "/claims").json()
    for cl in claims:
        c.patch(
            url + f"/claims/{cl['id']}/confirmation",
            json={
                "version": cl["version"],
                "confirmed": True,
                "expected": cl["expected"],
                "reason": "Review declaration scope",
            },
        )
    case.add("site_image", {"model": a["model"], "site": a["site"], "present": True}, "presence")
    findings = c.post(url + "/reconcile", json={"reason": "No identity"}).json()
    assert not any(f["computed_status"] == "supported" for f in findings)
