"""Fetch uniquely matched public source photographs; never score publisher labels as truth."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

SOURCE = "https://huggingface.co/datasets/sergiudanstan/motor-nameplate/resolve/main/"


def hydrate(output):
    output.mkdir(parents=True, exist_ok=True)
    with Path("fixtures/motor-nameplates/assets_40.csv").open(
        encoding="utf-8-sig", newline=""
    ) as source_file:
        rows = list(csv.DictReader(source_file))
    report = []
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        metadata = client.get(SOURCE + "metadata.csv")
        metadata.raise_for_status()
        (output / "publisher-metadata.csv").write_bytes(metadata.content)
        labels = list(csv.DictReader(io.StringIO(metadata.text)))
        for row in rows:
            matches = [
                m
                for m in labels
                if all(
                    m[k].strip().casefold() == row[v].strip().casefold()
                    for k, v in [
                        ("model_or_cat_no", "model"),
                        ("manufacturer_label_canonical", "manufacturer"),
                        ("serial_no", "serial_label"),
                    ]
                )
            ]
            if len(matches) != 1:
                report.append({"tag": row["asset_id"], "state": "ambiguous", "matches": len(matches)})
                continue
            source_name = matches[0]["file_name"]
            url = SOURCE + quote(source_name, safe="/")
            try:
                response = client.get(url)
                response.raise_for_status()
                with Image.open(io.BytesIO(response.content)) as image:
                    suffix = {"JPEG": ".jpg", "PNG": ".png"}.get(image.format)
                    if not suffix:
                        raise ValueError("Source is not a supported JPEG/PNG")
                    image.verify()
                path = output / (row["asset_id"] + suffix)
                path.write_bytes(response.content)
                report.append(
                    {
                        "tag": row["asset_id"],
                        "state": "downloaded",
                        "source_filename": source_name,
                        "local_path": str(path),
                        "source_url": url,
                        "sha256": hashlib.sha256(response.content).hexdigest(),
                        "label_status": "publisher_auto_generated_unverified",
                    }
                )
            except (httpx.HTTPError, ValueError, OSError):
                report.append({"tag": row["asset_id"], "state": "failed", "source_url": url})
    (output / "hydration-report.json").write_text(json.dumps(report, indent=2))
    return {state: sum(r["state"] == state for r in report) for state in {r["state"] for r in report}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("work/motor-source"))
    args = parser.parse_args()
    print(hydrate(args.output))
