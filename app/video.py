"""Bounded local MP4/MOV decoding. No remote protocols or model downloads."""

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from threading import BoundedSemaphore

from fastapi import HTTPException

SLOTS = BoundedSemaphore(1)


def video_frames(path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise HTTPException(503, "Install FFmpeg/ffprobe to process video; original retained")
    if not SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Video processing is busy; retry the saved original")
    try:
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
            check=True,
            timeout=10,
        )
        metadata = json.loads(probe.stdout)
        streams = [s for s in metadata["streams"] if s["codec_type"] == "video"]
        if len(streams) != 1:
            raise ValueError("One video stream required")
        stream = streams[0]
        duration = float(metadata["format"]["duration"])
        if not math.isfinite(duration) or not 0 < duration <= 30:
            raise ValueError("Video must be at most 30 seconds")
        if (
            stream["codec_name"] not in {"h264", "hevc", "mpeg4"}
            or not 0 < int(stream["width"]) * int(stream["height"]) <= 8294400
        ):
            raise ValueError("Use H264/HEVC/MPEG4 video up to 4K")
        # Small deterministic sample with real source timestamps; analyst chooses usable crops.
        timestamps = [round(duration * n / 6, 3) for n in range(6)]
        frames = []
        with tempfile.TemporaryDirectory(prefix="cdi-video-") as tmp:
            for n, timestamp in enumerate(timestamps):
                output = Path(tmp) / f"{n}.jpg"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-nostdin",
                        "-threads",
                        "1",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-ss",
                        str(timestamp),
                        "-i",
                        str(path),
                        "-an",
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=w='min(1920,iw)':h='min(1920,ih)':force_original_aspect_ratio=decrease",
                        "-threads",
                        "1",
                        "-q:v",
                        "3",
                        "-y",
                        str(output),
                    ],
                    capture_output=True,
                    check=True,
                    timeout=12,
                )
                data = output.read_bytes()
                if len(data) > 4 * 1024 * 1024:
                    raise ValueError("Decoded frame too large")
                frames.append((timestamp, data))
        return {
            "duration_seconds": duration,
            "codec": stream["codec_name"],
            "width": stream["width"],
            "height": stream["height"],
            "sampling": "six evenly spaced source timestamps",
        }, frames
    except (subprocess.SubprocessError, ValueError, KeyError, OSError) as exc:
        raise HTTPException(
            422, "Video could not be decoded within limits (12 MiB, 30 seconds, up to 4K); original retained"
        ) from exc
    finally:
        SLOTS.release()
