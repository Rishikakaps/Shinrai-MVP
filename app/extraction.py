"""Real local extraction. Worker process bounds parsing time and expanded PDF memory.
The deterministic line parser is deliberately narrow; analyst correction is the fallback.
"""

import json
import subprocess
import sys
from pathlib import Path

from app.models import Facts

MAX_BYTES = 12 * 1024 * 1024
MAX_PAGES = 12


def extract(path: Path, media_type: str):
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.extraction", str(path), media_type],
            capture_output=True,
            text=True,
            timeout=55,
            check=False,
        )
        if proc.returncode:
            return {"text": "", "pages": [], "method": "failed", "flags": ["incomplete"]}
        return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return {"text": "", "pages": [], "method": "failed", "flags": ["incomplete"]}


def parse_facts(text):
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        key, value = key.strip().lower().replace(" ", "_"), value.strip()
        if sep and key in Facts.model_fields and value:
            if key in values and values[key] != value:
                # Never choose one of two conflicting fields automatically.
                return Facts(), ["incomplete"]
            values[key] = value
    try:
        return Facts.model_validate(values), []
    except ValueError:
        return Facts(), ["incomplete"]


def ocr(image):
    import pytesseract

    text = pytesseract.image_to_string(image, config="--psm 6", timeout=18)
    return text[:100000]


def worker(path, media_type):
    import resource

    from PIL import Image
    from pypdf import PdfReader

    # Linux enforces a virtual-memory ceiling; macOS enforces CPU/file bounds.
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    pages, flags = [], []
    if media_type == "application/pdf":
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
            raise ValueError("Encrypted or excessive page count")
        for number, page in enumerate(reader.pages, 1):
            content = page.get_contents()
            if content is not None and len(content.get_data()) > 16 * 1024 * 1024:
                raise ValueError("Expanded content exceeds limit")
            text = (page.extract_text() or "").strip()
            method = "pdf_text"
            if not text:
                # Render with Poppler then OCR, rather than pretending PDF text extraction is OCR.
                import tempfile

                with tempfile.TemporaryDirectory() as directory:
                    prefix = str(Path(directory) / "page")
                    subprocess.run(
                        [
                            "pdftoppm",
                            "-f",
                            str(number),
                            "-l",
                            str(number),
                            "-scale-to",
                            "2200",
                            "-singlefile",
                            "-png",
                            str(path),
                            prefix,
                        ],
                        check=True,
                        capture_output=True,
                        timeout=15,
                    )
                    with Image.open(prefix + ".png") as image:
                        text = ocr(image)
                method = "tesseract"
            pages.append({"page": number, "text": text[:100000], "method": method})
    elif media_type.startswith("image/"):
        with Image.open(path) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("Image pixel limit")
            pages.append({"page": 1, "text": ocr(image), "method": "tesseract"})
    else:
        pages.append(
            {"page": 1, "text": Path(path).read_text(encoding="utf-8")[:100001], "method": "structured_text"}
        )
    combined = "\n\n".join(p["text"] for p in pages)
    if len(combined) > 100000:
        flags.append("incomplete")
    text = combined[:100000]
    for page in pages:
        page["text"] = page["text"][:100000]
    if not text.strip():
        flags.append("unreadable")
    methods = sorted({p["method"] for p in pages})
    return {"text": text, "pages": pages, "method": "+".join(methods), "flags": flags}


if __name__ == "__main__":
    print(json.dumps(worker(Path(sys.argv[1]), sys.argv[2])))
