"""Bounded local media worker. Originals are never modified; no external AI calls."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from app.extraction import extract
from app.label_scan import scan_file
from app.v2_media import process_audio


def video_frames(path, directory):
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        timeout=12,
        check=True,
    )
    info = json.loads(probe.stdout)
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    duration = float(info["format"].get("duration", 0))
    if (
        not streams
        or not 0 < duration <= 30
        or info["format"].get("format_name", "").split(",")[0] not in {"mov", "mp4"}
    ):
        raise ValueError("Use MP4/MOV with a video stream and duration up to 30 seconds")
    if streams[0].get("width", 0) * streams[0].get("height", 0) > 20_000_000:
        raise ValueError("Video dimensions exceed 20 megapixels")
    frames = []
    for index in range(6):
        timestamp = round(max(0, duration - 0.15) * index / 5, 3)
        target = directory / f"frame-{index + 1}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                "file,pipe",
                "-ss",
                str(timestamp),
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=1600:1600:force_original_aspect_ratio=decrease",
                "-an",
                "-y",
                str(target),
            ],
            capture_output=True,
            timeout=10,
            check=True,
        )
        if not target.is_file():
            continue
        with Image.open(target) as image:
            gray = image.convert("L")
            focus = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).stddev[0]
        frames.append(
            {
                "file": target.name,
                "timestamp": timestamp,
                "focus_heuristic": round(focus, 3),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    # Uniform sampling then a bounded sharpness shortlist. This is not calibrated blur detection.
    selected, hashes = [], set()
    for frame in sorted(frames, key=lambda f: f["focus_heuristic"], reverse=True):
        if frame["sha256"] not in hashes:
            selected.append(frame)
            hashes.add(frame["sha256"])
        if len(selected) == 3:
            break
    return duration, sorted(selected, key=lambda f: f["timestamp"])


def perceive(path, media_type, directory, filename):
    directory.mkdir(parents=True, exist_ok=True)
    if media_type.startswith("audio/"):
        return {
            "pages": [],
            "text": "",
            "method": "existing_ffmpeg_acoustic_pipeline",
            "flags": [],
            "audio": process_audio(path.read_bytes(), filename, media_type),
        }
    if media_type.startswith("video/"):
        duration, frames = video_frames(path, directory)
        pages = []
        for index, frame in enumerate(frames, 1):
            raw = scan_file(directory / frame["file"])
            pages.append(
                {
                    "page": index,
                    "text": raw["ocr_text"][:12000],
                    "method": "tesseract",
                    "codes": raw["codes"],
                    "timestamp": frame["timestamp"],
                    "frame": frame,
                    "quality_flags": raw["quality_flags"],
                }
            )
        if not pages:
            raise ValueError("No video frames could be decoded")
        return {
            "pages": pages,
            "text": "\n\n".join(p["text"] for p in pages),
            "method": "sampled_video+tesseract+zxing",
            "flags": [],
            "duration_seconds": duration,
            "sampled_frame_limit": 6,
            "ocr_frame_limit": 3,
        }
    if media_type.startswith("image/"):
        raw = scan_file(path)
        return {
            "pages": [{"page": 1, "text": raw["ocr_text"], "method": "tesseract", "codes": raw["codes"]}],
            "text": raw["ocr_text"],
            "method": "tesseract+zxing",
            "flags": raw["quality_flags"],
        }
    result = extract(path, media_type)
    if result["method"] == "failed":
        raise ValueError("Document extraction failed; original retained for review")
    return result


if __name__ == "__main__":
    from app.limits import apply_limits

    apply_limits(110, 1024 * 1024 * 1024)
    try:
        print(json.dumps(perceive(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4])))
    except Exception:  # noqa: BLE001 -- isolate decoder failures without exposing untrusted diagnostics
        # No source text, filesystem paths or decoder diagnostics in public errors.
        print(
            json.dumps(
                {
                    "error": "Media could not be processed within the permitted format, duration and resource limits"
                }
            )
        )
        raise SystemExit(1)
