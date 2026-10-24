"""Synthetic Plant A seed and repeatable HTTP end-to-end exercise. Never uses real financial data."""

import argparse
import io
import json
import os
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

PREFIX = "/api/v1"
CAPTURED = "2026-01-01T10:00:00Z"
REASON = "Prepared synthetic Japan Day demonstration"


def pdf_bytes(text):
    output = io.BytesIO()
    page = canvas.Canvas(output, pagesize=(600, 800))
    page.setFont("Helvetica", 14)
    for index, line in enumerate(text.splitlines()):
        page.drawString(35, 750 - index * 23, line)
    page.save()
    return output.getvalue()


def label_png(text):
    image = Image.new("RGB", (1400, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((40, 40), text, fill="black", font=ImageFont.load_default(size=36), spacing=14)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def ok(response):
    response.raise_for_status()
    return response.json()


def upload(client, iid, kind, text, filename="demo.txt", mime="text/plain", content=None):
    return ok(
        client.post(
            f"{PREFIX}/inspections/{iid}/evidence",
            data={
                "kind": kind,
                "source": "Synthetic Plant A demo",
                "captured_at": CAPTURED,
                "reason": REASON,
            },
            files={"file": (filename, content if content is not None else text.encode(), mime)},
        )
    )


def accept(client, iid, evidence, facts=None, flags=None):
    return ok(
        client.patch(
            f"{PREFIX}/inspections/{iid}/evidence/{evidence['id']}/correction",
            json={
                "version": evidence["version"],
                "text": evidence["text"],
                "facts": evidence["facts"] if facts is None else facts,
                "quality_flags": [] if flags is None else flags,
                "confidence": None,
                "confirmed": True,
                "reason": "Analyst checked synthetic original and corrected extraction",
            },
        )
    )


def link(client, iid, cid, eid, relation="supports"):
    return ok(
        client.post(
            f"{PREFIX}/inspections/{iid}/evidence-links",
            json={
                "claim_id": cid,
                "evidence_id": eid,
                "relation": relation,
                "locator": "page 1 / synthetic record",
                "reason": REASON,
            },
        )
    )


def seed(client, name="Plant A - three CNC machines"):
    existing = ok(client.get(f"{PREFIX}/inspections"))
    for item in existing:
        if item["name"] == name:
            existing_report = ok(client.get(f"{PREFIX}/inspections/{item['id']}/export"))
            if (
                existing_report["reconciliation_current"]
                and existing_report["inspection"]["state"] == "review_complete"
            ):
                return existing_report
            raise RuntimeError(
                "Existing demo is incomplete or changed. Use --name for a fresh demo; history is retained."
            )
    iid = ok(client.post(f"{PREFIX}/inspections", json={"name": name, "site": "Plant A"}))["id"]
    for number in range(1, 4):
        tag = f"CNC-{number:03d}"
        base = {"serial": f"SYN-{number:03d}", "model": "DemoMill X3", "site": "Plant A"}
        asset = ok(
            client.post(
                f"{PREFIX}/inspections/{iid}/assets",
                json={
                    "tag": tag,
                    **base,
                    "invoice_ref": f"INV-{number:03d}",
                    "payment_ref": f"PAY-{number:03d}",
                },
            )
        )
        claims = {
            c["kind"]: c
            for c in ok(client.get(f"{PREFIX}/inspections/{iid}/claims"))
            if c["asset_id"] == asset["id"]
        }
        for claim in claims.values():
            ok(
                client.patch(
                    f"{PREFIX}/inspections/{iid}/claims/{claim['id']}/confirmation",
                    json={
                        "expected": claim["expected"],
                        "confirmed": True,
                        "version": claim["version"],
                        "reason": REASON,
                    },
                )
            )
        financial = {**base, "invoice_ref": f"INV-{number:03d}", "amount": "100000.00", "currency": "INR"}
        for kind, kinds, extra in [
            ("equipment_register", ("identity", "purchase"), {}),
            ("invoice", ("purchase", "payment"), {}),
            ("payment_extract", ("payment",), {"payment_ref": f"PAY-{number:03d}"}),
        ]:
            facts = {**financial, **extra}
            text = "SYNTHETIC DEMO - NOT A REAL FINANCIAL RECORD\n" + "\n".join(
                f"{k}: {v}" for k, v in facts.items()
            )
            if kind == "invoice":
                ev = upload(client, iid, kind, text, f"{tag}-invoice.pdf", "application/pdf", pdf_bytes(text))
            else:
                ev = upload(client, iid, kind, text, f"{tag}-{kind}.txt")
            ev = ok(
                client.post(
                    f"{PREFIX}/inspections/{iid}/evidence/{ev['id']}/extract", json={"reason": REASON}
                )
            )
            ev = accept(client, iid, ev)  # confirm actual parsed facts, not a stubbed extraction
            for claim_kind in kinds:
                link(client, iid, claims[claim_kind]["id"], ev["id"])
        observation_facts = {**base, "present": True, "condition": "operating" if number < 3 else "packaged"}
        if number < 3:
            observation_facts["installed"] = True
        obs = ok(
            client.post(
                f"{PREFIX}/inspections/{iid}/observations",
                json={
                    "asset_id": asset["id"],
                    "text": "Operating at site" if number < 3 else "Packaged; installation unverified",
                    "facts": observation_facts,
                    "source": "analyst",
                    "captured_at": CAPTURED,
                    "reason": REASON,
                },
            )
        )
        for kind in ("presence", "installation", "commissioning"):
            link(client, iid, claims[kind]["id"], obs["evidence_id"])
        if number == 1:
            facts = {**base, "commissioned": True}
            text = "\n".join(f"{k}: {str(v).lower() if isinstance(v, bool) else v}" for k, v in facts.items())
            ev = upload(
                client,
                iid,
                "commissioning_certificate",
                text,
                "CNC-001-certificate.pdf",
                "application/pdf",
                pdf_bytes(text),
            )
            ev = ok(
                client.post(
                    f"{PREFIX}/inspections/{iid}/evidence/{ev['id']}/extract", json={"reason": REASON}
                )
            )
            ev = accept(client, iid, ev)
            link(client, iid, claims["commissioning"]["id"], ev["id"])
            # Real label OCR, then explicit correction (never automatic acceptance).
            label = "serial: SYN-001\nmodel: DemoMill X3\nsite: Plant A"
            ev = upload(client, iid, "site_image", label, "CNC-001-label.png", "image/png", label_png(label))
            ev = ok(
                client.post(
                    f"{PREFIX}/inspections/{iid}/evidence/{ev['id']}/extract", json={"reason": REASON}
                )
            )
            ev = accept(client, iid, ev, facts=base, flags=["manual_correction"])
            link(client, iid, claims["identity"]["id"], ev["id"])
        else:
            ok(
                client.post(
                    f"{PREFIX}/inspections/{iid}/follow-ups",
                    json={
                        "claim_id": claims["commissioning"]["id"],
                        "request": "Provide commissioning certificate",
                        "reason": REASON,
                    },
                )
            )
        if number == 3:
            ok(
                client.post(
                    f"{PREFIX}/inspections/{iid}/follow-ups",
                    json={
                        "claim_id": claims["installation"]["id"],
                        "request": "Clarify installation status of packaged equipment",
                        "reason": REASON,
                    },
                )
            )
    findings = ok(client.post(f"{PREFIX}/inspections/{iid}/reconcile", json={"reason": REASON}))
    for finding in findings:
        ok(
            client.patch(
                f"{PREFIX}/inspections/{iid}/findings/{finding['id']}/review",
                json={"version": finding["version"], "status": finding["computed_status"], "reason": REASON},
            )
        )
    ok(client.post(f"{PREFIX}/inspections/{iid}/review-complete", json={"reason": REASON}))
    return ok(client.get(f"{PREFIX}/inspections/{iid}/export"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--name", default="Plant A - three CNC machines")
    args = parser.parse_args()
    token = os.environ["CDI_ANALYST_TOKEN"]
    with httpx.Client(base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=90) as client:
        result = seed(client, name=args.name)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2))
    print("Inspection:", result["inspection"]["id"], "State:", result["inspection"]["state"])
    assets = {a["id"]: a["tag"] for a in result["assets"]}
    claims = {c["id"]: c for c in result["claims"]}
    for finding in result["findings"]:
        claim = claims[finding["claim_id"]]
        print(assets[claim["asset_id"]], claim["kind"], finding["computed_status"])


if __name__ == "__main__":
    main()
