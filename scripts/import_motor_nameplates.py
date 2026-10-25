"""Resume-safe import of the public, unverified motor registry through authenticated APIs.

Run with --env-file <private .env> --photos <downloaded photos directory>.
Original photos are local runtime evidence, never source-controlled.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values
from PIL import Image

NAME = "40 Motor Nameplates — PUBLIC DATASET / UNVERIFIED"
SITE = "DEMO Plant Motor Registry (synthetic association)"
REASON = "Import public dataset labels as unverified demo declarations; no ownership or site proof"


def run(client, records, photos):
    def request(method, path, **kwargs):
        response = client.request(method, "/api/v1" + path, **kwargs)
        if response.is_error:
            raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:500]}")
        return response.json()

    visits = request("GET", "/inspections")
    visit = next((v for v in visits if v["name"] == NAME), None)
    if visit is None:
        visit = request("POST", "/inspections", json={"name": NAME, "site": SITE, "reason": REASON})
    iid = visit["id"]
    root = f"/inspections/{iid}"
    report = request("GET", root + "/export")
    assets = {a["tag"]: a for a in report["assets"]}
    for row in records:
        tag = row["asset_id"]
        if tag not in assets:
            metadata = {
                k: row.get(k) or None
                for k in (
                    "manufacturer",
                    "serial_label",
                    "horse_power",
                    "kilowatts",
                    "speed_rpm",
                    "voltage_label",
                    "source_url",
                    "source_image_filename",
                    "dataset_label_status",
                    "asset_tag_origin",
                    "photo_resolution",
                )
            }
            metadata["scan_sample"] = tag == "MTR-031"
            assets[tag] = request(
                "POST",
                root + "/assets",
                json={
                    "tag": tag,
                    "serial": row["serial_label"] or "UNVERIFIED-" + tag,
                    "model": row["model"],
                    "site": SITE,
                    "invoice_ref": "MISSING-INVOICE-" + tag,
                    "payment_ref": "MISSING-PAYMENT-" + tag,
                    "nameplate_metadata": metadata,
                    "reason": REASON,
                },
            )
    report = request("GET", root + "/export")
    evidence = {e["filename"]: e for e in report["evidence"]}
    links = {(l["claim_id"], l["evidence_id"]) for l in report["evidence_links"] if l["active"]}
    for row in records:
        tag = row["asset_id"]
        claim = next(
            c for c in report["claims"] if c["asset_id"] == assets[tag]["id"] and c["kind"] == "identity"
        )
        content = (
            "PUBLIC DATASET — UNVERIFIED LABELS\n"
            + json.dumps(row, indent=2)
            + "\nNo ownership, location, purchase, payment or operational evidence.\n"
        ).encode()
        sources = [(tag + "-source-metadata.txt", content, "text/plain")]
        photo = photos / (row.get("source_image_filename") or "missing")
        if photo.is_file():
            with Image.open(photo) as image:
                extension, media = ("png", "image/png") if image.format == "PNG" else ("jpg", "image/jpeg")
            sources.append((tag + "-nameplate." + extension, photo.read_bytes(), media))
        for filename, data, media in sources:
            ev = evidence.get(filename)
            if ev is None:
                ev = request(
                    "POST",
                    root + "/evidence",
                    files={"file": (filename, data, media)},
                    data={
                        "kind": "equipment_register",
                        "source": row["source_url"],
                        "captured_at": datetime.now(UTC).isoformat(),
                        "reason": REASON,
                    },
                )
                evidence[filename] = ev
            pair = claim["id"], ev["id"]
            if pair not in links:
                request(
                    "POST",
                    root + "/evidence-links",
                    json={
                        "claim_id": claim["id"],
                        "evidence_id": ev["id"],
                        "relation": "context",
                        "locator": "Unverified public source label; not accepted identity proof",
                        "reason": REASON,
                    },
                )
                links.add(pair)
    cases = request("GET", "/cases")
    case = next((c for c in cases if c["company"] == NAME and c["inspection_id"] == iid), None)
    if case is None:
        case = request(
            "POST",
            "/cases",
            headers={"Idempotency-Key": "motor-registry-" + iid},
            json={
                "inspection_id": iid,
                "company": NAME,
                "site": SITE,
                "reason": REASON,
            },
        )
    request("POST", root + "/reconcile", json={"reason": REASON})
    report = request("GET", root + "/export")
    return {
        "inspection_id": iid,
        "case_id": case["id"],
        "assets": len(report["assets"]),
        "claims": len(report["claims"]),
        "evidence": len(report["evidence"]),
        "supported": sum(f["computed_status"] == "supported" for f in report["findings"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--photos", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8004")
    args = parser.parse_args()
    token = dotenv_values(args.env_file).get("CDI_ANALYST_TOKEN")
    if not token:
        raise SystemExit("Private CDI_ANALYST_TOKEN is required")
    records = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures/motor-nameplates/assets.json").read_text(
            encoding="utf-8"
        )
    )
    with httpx.Client(base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=60) as client:
        print(json.dumps(run(client, records, args.photos)))


if __name__ == "__main__":
    main()
