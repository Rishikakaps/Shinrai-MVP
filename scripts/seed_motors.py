"""Idempotent public-label import through the operational API. No photo/claim acceptance."""

import argparse
import csv
from pathlib import Path

import httpx
from dotenv import dotenv_values

NAME = "Plant C — 40 Motor Nameplates (PUBLIC DATASET / UNVERIFIED)"
SITE = "Plant C — synthetic registry association"


def import_motors(client, source=Path("fixtures/motor-nameplates/assets_40.csv")):
    def request(method, path, **kwargs):
        result = client.request(method, "/api/v1" + path, **kwargs)
        result.raise_for_status()
        return result.json()

    inspections = request("GET", "/inspections")
    inspection = next((i for i in inspections if i["name"] == NAME), None)
    if not inspection:
        inspection = request(
            "POST",
            "/inspections",
            json={
                "name": NAME,
                "site": SITE,
                "reason": "Import unverified public labels with synthetic site associations",
            },
        )
    iid = inspection["id"]
    cases = request("GET", "/cases")
    enrolled = False
    for case in cases:
        if any(i["id"] == iid for i in request("GET", f"/cases/{case['id']}/inspections")):
            enrolled = True
            break
    if not enrolled:
        request(
            "POST",
            "/cases",
            headers={"Idempotency-Key": "motor-nameplate-registry-case"},
            json={
                "inspection_id": iid,
                "company": "Public motor dataset demonstration (ownership unknown)",
                "site": SITE,
                "timezone": "Asia/Kolkata",
                "reason": "Public labels only; no verified ownership, site or deployment",
            },
        )
    report = request("GET", f"/inspections/{iid}/export")
    tags = {a["tag"] for a in report["assets"]}
    imported_rows = {
        a.get("provenance", {}).get("viewer_row_index")
        for a in report["assets"]
        if a.get("provenance", {}).get("source_url")
        == "https://huggingface.co/datasets/sergiudanstan/motor-nameplate"
    }
    rows = list(csv.DictReader(source.open(newline="", encoding="utf-8-sig")))
    if len(rows) != 40 or len({r["asset_id"] for r in rows}) != 40:
        raise ValueError("Expected exactly 40 distinct source records")
    for row in rows:
        if row["asset_id"] in tags or int(row["source_preview_row_index"]) in imported_rows:
            continue
        body = {
            "tag": row["asset_id"],
            "serial": row["serial_label"] or None,
            "model": row["model"],
            "site": SITE,
            "manufacturer": row["manufacturer"] or None,
            "rated_power_kw": row["kilowatts"] or None,
            "horse_power": row["horse_power"] or None,
            "rated_voltage_v": row["voltage_label"] or None,
            "rated_speed_rpm": row["speed_rpm"] or None,
            "provenance": {
                "source_url": row["source_url"],
                "viewer_row_index": int(row["source_preview_row_index"]),
                "source_image_filename": row["source_image_filename"] or None,
                "label_status": "publisher_auto_generated_unverified",
                "original_available": False,
                "ocr_run": False,
                "site_association": "synthetic",
                "ownership": None,
            },
            "reason": "Import publisher labels as unverified declarations; all six claims unconfirmed",
        }
        request("POST", f"/inspections/{iid}/assets", json=body)
    report = request("GET", f"/inspections/{iid}/export")
    return {
        "inspection_id": iid,
        "assets": len(report["assets"]),
        "claims": len(report["claims"]),
        "missing_serials": sum(a["serial"] is None for a in report["assets"]),
        "supported": sum(f["computed_status"] == "supported" for f in report["findings"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8003")
    parser.add_argument("--env", type=Path, required=True)
    args = parser.parse_args()
    # Token stays in memory and is sent only to the explicitly selected local service.
    from urllib.parse import urlparse

    if urlparse(args.url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("This import runner is restricted to localhost")
    token = dotenv_values(args.env).get("CDI_ANALYST_TOKEN")
    if not token:
        parser.error("Private analyst configuration unavailable")
    with httpx.Client(base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=90) as client:
        print(import_motors(client))
