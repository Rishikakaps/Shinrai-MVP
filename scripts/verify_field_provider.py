"""Explicit live Google checks. Never substitutes mock output for a failed request.

Run with --audio PATH to exercise actual transcription of an authorized speech clip.
Output is private under .run by default, including a byte-identical original copy.
This probes the provider adapter; persisted API workflows have separate integration tests.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException

from app.models import now
from app.v2_media import process_audio
from app.v2_providers import GeminiProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, help="Authorized Japanese speech; WAV, WebM/Opus or M4A/AAC")
    parser.add_argument("--output", type=Path, default=Path(".run/live-provider/result.json"))
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if not GeminiProvider.configured():
        raise SystemExit("LIVE PROVIDER VALIDATION PENDING: set private GEMINI_API_KEY and GEMINI_MODEL")
    provider = GeminiProvider()
    report = {
        "checked_at": now(),
        "provider": "gemini",
        "model": provider.model,
        "mocked": False,
        "hardware_verified": False,
        "checks": {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sample = "修理費は約800万円です。停止時間はまだ減っていません。交換は検討中です。"
    exit_code = 0
    try:
        translation = provider.translate(sample)
        report["checks"]["translation"] = {
            "passed": True,
            "source": sample,
            "output": translation,
            "human_review_required": "Check negation, tentative replacement, approximate JPY 8,000,000",
        }
        proposal = provider.analyse(sample, {"unresolved_claims": [], "asked_topics": []})
        report["checks"]["structured_proposals"] = {
            "passed": True,
            "output": proposal.model_dump(mode="json"),
            "meaning": "Schema and exact source quote validation only; no proposal accepted",
        }
        if args.audio:
            source = args.audio.resolve(strict=True)
            content = source.read_bytes()
            mime = {".wav": "audio/wav", ".webm": "audio/webm", ".mp4": "audio/mp4", ".m4a": "audio/mp4"}.get(
                source.suffix.lower(), ""
            )
            decoded = process_audio(content, source.name, mime)
            digest = hashlib.sha256(content).hexdigest()
            original = args.output.parent / ("original-" + digest + source.suffix.lower())
            if source != original.resolve():
                shutil.copyfile(source, original)
            assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
            text, english = provider.transcribe(original, source.name, mime, "ja")
            report["checks"]["audio"] = {
                "passed": True,
                "sha256": digest,
                "duration_seconds": decoded["duration_seconds"],
                "text": text,
                "english_translation": english,
                "human_review_required": True,
            }
        else:
            report["checks"]["audio"] = {
                "passed": False,
                "status": "PENDING: rerun with an authorized Japanese speech clip via --audio",
            }
    except HTTPException as exc:
        report["failure"] = {"status": exc.status_code, "detail": exc.detail}
        exit_code = 1
    finally:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Live provider check report saved privately to", args.output)
    if not args.audio:
        print("Speech transcription remains pending; no audio was fabricated.")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
