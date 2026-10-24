"""Bounded label decoding. Suggestions never confirm asset identity or accept evidence."""

import io
import json
import subprocess
import sys
from pathlib import Path
from threading import BoundedSemaphore
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

from app import engine
from app.identifiers import compare_scan, parse_fields
from app.models import Asset, Evidence, Inspection, Reason


class ScanRequest(Reason):
    asset_id: str | None = None


SCAN_SLOTS = BoundedSemaphore(2)


def inspect_image(path):
    import pytesseract
    import zxingcpp
    from PIL import Image, ImageFilter, ImageOps, ImageStat

    from app.limits import apply_limits

    apply_limits(25, 768 * 1024 * 1024)
    Image.MAX_IMAGE_PIXELS = 20_000_000
    with Image.open(path) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError("Image exceeds pixel limit")
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size
        image.thumbnail((2200, 2200))
        codes = [
            {"text": code.text, "format": str(code.format)}
            for code in zxingcpp.read_barcodes(image)
            if code.valid
        ]
        gray = image.convert("L")
        contrast = ImageStat.Stat(gray).stddev[0]
        edge = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
        flags = []
        if min(width, height) < 160:
            flags.append("image_too_small")
        if contrast < 8:
            flags.append("low_contrast")
        if edge < 2 and not codes:
            flags.append("blur_or_low_detail")
        try:
            text = pytesseract.image_to_string(image, config="--psm 6", timeout=15)[:4000].strip()
            ocr_available = True
        except (RuntimeError, pytesseract.TesseractNotFoundError):
            text, ocr_available = "", False
        fields = parse_fields(text)
        serials = fields["serial"]
        serials = list(dict.fromkeys(serials + [c["text"] for c in codes]))[:20]
        if not codes:
            flags.append("barcode_not_decoded")
        if not serials:
            flags.append("serial_not_read")
        return {
            "codes": codes[:20],
            "serial_suggestions": serials,
            "ocr_text": text,
            "ocr_fields": fields,
            "ocr_available": ocr_available,
            "quality_flags": flags,
            "width": width,
            "height": height,
        }


def scan_file(path):
    if not SCAN_SLOTS.acquire(blocking=False):
        raise HTTPException(
            429, "Scanner is busy; the saved source can be processed again", headers={"Retry-After": "2"}
        )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.label_scan", str(path)], capture_output=True, timeout=28, check=True
        )
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise HTTPException(
            422,
            "Label could not be decoded safely. The original is saved; rescan or use reviewed manual correction.",
        ) from exc
    finally:
        SCAN_SLOTS.release()


def install_label_scan(app, store, authenticate):
    Actor = Annotated[str, Depends(authenticate)]

    @app.get("/api/v1/inspections/{iid}/demo-label/{aid}", dependencies=[Depends(authenticate)])
    def demo_label(iid: str, aid: str):
        import zxingcpp
        from PIL import Image, ImageDraw, ImageFont

        with store.transaction(write=False) as db:
            inspection = store.get(db, Inspection, iid, iid)
            asset = store.get(db, Asset, aid, iid)
        if not inspection.name.startswith("Plant A trial ·"):
            raise HTTPException(403, "Synthetic label fixtures are restricted to prepared demo inspections")
        code = zxingcpp.write_barcode_to_image(
            zxingcpp.create_barcode(asset.serial, zxingcpp.BarcodeFormat.QRCode), scale=14
        )
        qr = Image.frombytes("L", (code.shape[1], code.shape[0]), bytes(code)).convert("RGB")
        image = Image.new("RGB", (900, max(900, qr.height + 270)), "white")
        image.paste(qr, ((900 - qr.width) // 2, 110))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=22)
        draw.text((28, 22), "SYNTHETIC CAMERA TEST - NOT INDEPENDENT EVIDENCE", fill="black", font=font)
        for index, line in enumerate(
            ["Serial: " + asset.serial, "Model: " + asset.model, "Site: " + asset.site]
        ):
            draw.text((40, image.height - 145 + 38 * index), line, fill="black", font=font)
        out = io.BytesIO()
        image.save(out, format="PNG")
        return Response(out.getvalue(), media_type="image/png")

    @app.post("/api/v1/inspections/{iid}/evidence/{eid}/scan-label")
    def scan_label(iid: str, eid: str, body: ScanRequest, actor: Actor, request: Request):
        if request.state.principal["role"] != "analyst":
            raise HTTPException(403, "Label analysis requires analyst access")
        with store.transaction(write=False) as db:
            ev = store.get(db, Evidence, eid, iid)
            if ev.media_type not in {"image/png", "image/jpeg"}:
                raise HTTPException(415, "Use a JPEG or PNG photograph of the label")
            if not engine.intact(store, ev):
                raise HTTPException(409, "Original evidence integrity failed")
            asset = store.get(db, Asset, body.asset_id, iid) if body.asset_id else None
        result = scan_file(store.files / ev.sha256)
        comparison = compare_scan(result, {k: getattr(asset, k, None) for k in ("serial", "model", "site")})
        match = {
            "MATCH_CANDIDATE": "matches_declared_serial",
            "IDENTIFIER_MISMATCH": "differs_from_declared_serial",
            "NO_IDENTIFIER_FOUND": "not_read",
            "UNREADABLE_OR_BLURRED": "not_read",
        }.get(comparison["decision"], comparison["decision"].lower())
        result.update(comparison)
        result.update(
            evidence_id=eid,
            identity_result=match,
            identity_confirmed=False,
            evidence_accepted=False,
            next_action="Review against the original and accepted identity evidence before confirming. Rescan if unreadable or mismatched.",
            method="ZXing barcode decoding and local Tesseract OCR; image-quality heuristics are not a calibrated blur classifier",
        )
        return result


if __name__ == "__main__":
    try:
        print(json.dumps(inspect_image(Path(sys.argv[1]))))
    except (OSError, ValueError, RuntimeError, IndexError):
        raise SystemExit(1)
