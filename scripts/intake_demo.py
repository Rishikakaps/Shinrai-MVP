"""Generate linked, explicitly fictional intake fixtures; no real manufacturer identifiers."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

ASSETS = [
    ("CNC-001", "DEMO-VF200", "DEMO-SN-001"),
    ("CNC-002", "DEMO-VF500", "DEMO-SN-002"),
    ("CNC-003", "DEMO-VF500", "DEMO-SN-003"),
]


def generate(root):
    import shutil

    import zxingcpp

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = []
    base = "Manufacturer: Demo Works (fictional)\nAsset ID: CNC-002\nModel: DEMO-VF500\nSerial: DEMO-SN-002\nSite: Plant A\n"
    documents = [
        (
            "commissioning-002",
            "commissioning_certificate",
            "Commissioning certificate\n"
            + base
            + "Commissioned: true\nCommissioning date: 2026-10-25\nCertificate number: DEMO-CERT-002",
            "CNC-002",
        ),
        (
            "specification-002",
            "technical_specification",
            "Technical specification\n"
            + base
            + "Rated power: 15 kW\nRated voltage: 400 V\nRated speed: 12000 RPM",
            "CNC-002",
        ),
        (
            "invoice-002",
            "purchase_invoice",
            "Purchase invoice\n"
            + base
            + "Invoice number: DEMO-INV-002\nAmount: 12000000\nCurrency: JPY\nSupplier: Demo Works",
            "CNC-002",
        ),
        (
            "inspection-002",
            "inspection_report",
            "Inspection report\n" + base + "Inspector name: Fictional inspector\nDocument date: 2026-10-25",
            "CNC-002",
        ),
        (
            "commissioning-003",
            "commissioning_certificate",
            "Commissioning certificate\n"
            + base.replace("CNC-002", "CNC-003").replace("DEMO-SN-002", "DEMO-SN-003")
            + "Commissioned: true",
            "CNC-003",
        ),
        (
            "CNC-002-misnamed-actually-003",
            "commissioning_certificate",
            "Commissioning certificate\n"
            + base.replace("CNC-002", "CNC-003").replace("DEMO-SN-002", "DEMO-SN-003")
            + "Commissioned: true",
            "CNC-003",
        ),
        (
            "model-only",
            "technical_specification",
            "Technical specification\nManufacturer: Demo Works\nModel: DEMO-VF500\nRated power: 15 kW",
            None,
        ),
        (
            "partial-serial",
            "machine_nameplate",
            "Machine nameplate\nModel: DEMO-VF500\nSerial: DEMO-SN-00?",
            None,
        ),
        ("unknown", "other", "Meeting notes\nNo machine identifiers or evidence assertions supplied.", None),
        (
            "multiple-machines",
            "inspection_report",
            "Inspection report\nAsset ID: CNC-002\nSerial: DEMO-SN-002\nAsset ID: CNC-003\nSerial: DEMO-SN-003\nModel: DEMO-VF500",
            None,
        ),
        (
            "contradictory-id-serial",
            "commissioning_certificate",
            "Commissioning certificate\n" + base.replace("DEMO-SN-002", "DEMO-SN-003") + "Commissioned: true",
            None,
        ),
    ]
    for sample, category, text, asset in documents:
        target = root / (sample + ".pdf")
        pdf = canvas.Canvas(str(target), pagesize=(600, 800), invariant=1)
        pdf.setTitle("synthetic_demo - " + sample)
        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawString(32, 760, "synthetic_demo - FICTIONAL TEST EVIDENCE")
        pdf.setFont("Helvetica", 12)
        for index, line in enumerate(text.splitlines()):
            pdf.drawString(32, 715 - index * 24, line)
        pdf.save()
        manifest.append(entry(target, sample, category, asset, text, sample))
    duplicate = root / "duplicate-commissioning-002.pdf"
    shutil.copyfile(root / "commissioning-002.pdf", duplicate)
    manifest.append(
        entry(
            duplicate,
            "duplicate-commissioning-002",
            "commissioning_certificate",
            "CNC-002",
            documents[0][2],
            "commissioning-002",
        )
    )
    for tag, model, serial in ASSETS[1:]:
        target = root / ("nameplate-" + tag + ".png")
        image = Image.new("RGB", (1200, 900), "white")
        draw, font = ImageDraw.Draw(image), ImageFont.load_default(size=32)
        text = f"Machine nameplate\nAsset ID: {tag}\nModel: {model}\nSerial: {serial}\nSite: Plant A"
        for index, line in enumerate(["synthetic_demo - NOT REAL EQUIPMENT"] + text.splitlines()):
            draw.text((35, 30 + index * 55), line, font=font, fill="black")
        payload = json.dumps({"serial": serial, "model": model, "site": "Plant A"})
        bits = zxingcpp.write_barcode_to_image(
            zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.QRCode), scale=8
        )
        image.paste(
            Image.frombytes("L", (bits.shape[1], bits.shape[0]), bytes(bits)).convert("RGB"), (700, 390)
        )
        image.save(target)
        manifest.append(entry(target, "nameplate-" + tag, "machine_nameplate", tag, text, "nameplate-" + tag))
    (root / "manifest.jsonl").write_text("\n".join(json.dumps(m) for m in manifest) + "\n", encoding="utf-8")
    return manifest


def entry(path, sample, category, asset, text, family):
    return {
        "sample_id": sample,
        "file_path": path.name,
        "source_dataset": "project_synthetic_demo",
        "license_provenance": "Project-authored fictional fixture; no third-party document",
        "synthetic_demo": True,
        "media_type": "image/png" if path.suffix == ".png" else "application/pdf",
        "document_category": category,
        "ground_truth_asset": asset,
        "ground_truth_serial": f"DEMO-SN-{asset[-3:]}" if asset else None,
        "ground_truth_manufacturer": "Demo Works" if "Manufacturer:" in text else None,
        "ground_truth_model": "DEMO-VF500" if "DEMO-VF500" in text else None,
        "visible_text": text,
        "field_references": {"page": 1},
        "contains_conflict": "contradictory" in sample or "multiple" in sample,
        "automatic_association_permitted": False,
        "template_family": family,
        "split": "test",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("datasets/raw/synthetic"))
    args = parser.parse_args()
    print(f"Generated {len(generate(args.output))} synthetic fixtures in {args.output}")


if __name__ == "__main__":
    main()
