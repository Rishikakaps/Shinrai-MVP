"""Cross-platform local runner. Configuration stays in a private ignored .env."""

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


def main():
    root = Path(__file__).resolve().parents[1]
    configuration = Path(os.environ.get("CDI_ENV_FILE", str(root / ".env")))
    if not configuration.is_absolute():
        configuration = root / configuration
    load_dotenv(configuration, override=False)
    local_ocr = root / ".tools" / "tesseract"
    if (local_ocr / "tesseract.exe").is_file():
        os.environ["PATH"] = str(local_ocr) + os.pathsep + os.environ.get("PATH", "")
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=os.environ.get("CDI_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
