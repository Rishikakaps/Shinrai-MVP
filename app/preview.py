"""Bounded PDF page rendering for browsers without an inline PDF viewer."""

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException


def render_page(path, page):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.preview", str(path), str(page)],
            capture_output=True,
            timeout=20,
            check=True,
        )
        data = json.loads(result.stdout)
        return base64.b64decode(data["png"], validate=True), data["pages"]
    except (subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise HTTPException(
            422, "This PDF page could not be displayed. Download the original to inspect it."
        ) from exc


def worker(path, page):
    from pypdf import PdfReader

    from app.limits import apply_limits

    apply_limits(15, 768 * 1024 * 1024)
    pages = len(PdfReader(path, strict=True).pages)
    if not 1 <= page <= min(pages, 12):
        raise ValueError("Page outside document")
    with tempfile.TemporaryDirectory() as folder:
        prefix = str(Path(folder) / "preview")
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page),
                "-l",
                str(page),
                "-singlefile",
                "-scale-to",
                "1600",
                "-png",
                str(path),
                prefix,
            ],
            capture_output=True,
            check=True,
            timeout=12,
        )
        png = Path(prefix + ".png").read_bytes()
        if len(png) > 12 * 1024 * 1024:
            raise ValueError("Rendered page exceeds limit")
    return {"png": base64.b64encode(png).decode("ascii"), "pages": pages}


if __name__ == "__main__":
    print(json.dumps(worker(Path(sys.argv[1]), int(sys.argv[2]))))
