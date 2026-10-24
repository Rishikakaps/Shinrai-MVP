"""Generate local credentials once, without printing secrets or replacing existing configuration."""

import json
import os
import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / ".env"
    analyst, judge = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    tokens = {
        analyst: {"actor": "Demo Analyst", "role": "analyst"},
        judge: {"actor": "Demo Judge", "role": "judge"},
    }
    content = (
        "CDI_TOKENS='"
        + json.dumps(tokens)
        + "'\n"
        + "CDI_ANALYST_TOKEN="
        + analyst
        + "\nCDI_JUDGE_TOKEN="
        + judge
        + "\nCDI_DATA_DIR=data\nCDI_CORS_ORIGINS=\n"
    )
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing .env retained.")
        return
    with os.fdopen(descriptor, "w") as file:
        file.write(content)
    print("Created private .env with separate analyst and judge credentials. Do not commit it.")


if __name__ == "__main__":
    main()
