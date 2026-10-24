"""Bounded audio validation and transparent signal features, never fault diagnosis."""

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from array import array
from itertools import pairwise
from pathlib import Path
from statistics import median
from threading import BoundedSemaphore

from fastapi import HTTPException

from app.extraction import MAX_BYTES

SLOTS = BoundedSemaphore(2)
MAX_DURATION = 120
MAX_SAMPLES = 16000 * MAX_DURATION


def process_audio(content, filename, media_type):
    allowed = {
        ".wav": {"audio/wav", "audio/x-wav", "audio/wave"},
        ".webm": {"audio/webm"},
        ".m4a": {"audio/mp4", "audio/x-m4a"},
        ".mp4": {"audio/mp4"},
    }
    suffix = Path(filename).suffix.lower()
    media_type = media_type.split(";", 1)[0].strip().lower()
    if suffix not in allowed or media_type not in allowed[suffix]:
        raise HTTPException(415, "Use PCM WAV, audio WebM/Opus or audio MP4/AAC")
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(413, "Audio must contain 1 byte to 12 MiB")
    signatures = {
        ".wav": content[:4] == b"RIFF" and content[8:12] == b"WAVE",
        ".webm": content[:4] == b"\x1aE\xdf\xa3",
        ".m4a": content[4:8] == b"ftyp",
        ".mp4": content[4:8] == b"ftyp",
    }
    if not signatures[suffix]:
        raise HTTPException(422, "Audio signature does not match the declared container")
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise HTTPException(503, "FFmpeg and ffprobe are required for validated audio capture")
    if not SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Audio processing is busy; retry shortly")
    try:
        with tempfile.TemporaryDirectory(prefix="cdi-audio-") as temporary:
            path = Path(temporary) / ("original" + suffix)
            path.write_bytes(content)
            os.chmod(path, 0o600)
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
                    timeout=10,
                    check=True,
                )
                metadata = json.loads(probe.stdout)
                streams = metadata.get("streams", [])
                if len(streams) != 1 or streams[0].get("codec_type") != "audio":
                    raise ValueError("One audio stream and no video is required")
                stream = streams[0]
                declared_duration = metadata.get("format", {}).get("duration", stream.get("duration"))
                duration = float(declared_duration) if declared_duration not in (None, "N/A") else None
                sample_rate, channels = int(stream["sample_rate"]), int(stream["channels"])
                if duration is not None and (
                    not math.isfinite(duration) or not 0 < duration <= MAX_DURATION + 0.1
                ):
                    raise ValueError("Audio exceeds the 120-second duration limit")
                if not 1 <= channels <= 2 or not 8000 <= sample_rate <= 48000:
                    raise ValueError("Audio supports 1–2 channels and 8–48 kHz sample rates")
                codec = stream.get("codec_name", "")
                if suffix == ".wav" and codec not in {
                    "pcm_s16le",
                    "pcm_s24le",
                    "pcm_s32le",
                    "pcm_f32le",
                    "pcm_u8",
                }:
                    raise ValueError("Only PCM WAV is supported")
                if suffix == ".webm" and codec != "opus":
                    raise ValueError("WebM must contain Opus audio")
                if suffix in {".mp4", ".m4a"} and codec != "aac":
                    raise ValueError("MP4 must contain AAC audio")
                decoded = subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-nostdin",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-i",
                        str(path),
                        "-t",
                        "120.01",
                        "-map",
                        "0:a:0",
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        "-f",
                        "s16le",
                        "pipe:1",
                    ],
                    capture_output=True,
                    timeout=15,
                    check=True,
                ).stdout
                if not decoded or len(decoded) > MAX_SAMPLES * 2:
                    raise ValueError("Decoded audio is empty or exceeds the sample budget")
                decoded_duration = len(decoded) / 32000
                if duration is not None and abs(duration - decoded_duration) > max(0.1, duration * 0.02):
                    raise ValueError("Container duration disagrees with decoded audio")
                duration = decoded_duration
            except (subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
                raise HTTPException(
                    422, "Audio could not be safely decoded within duration/format limits"
                ) from exc
            features, flags = signal_features(decoded)
            return {
                "duration_seconds": round(duration, 3),
                "sample_rate": sample_rate,
                "channels": channels,
                "media_type": "audio/mp4"
                if suffix in {".m4a", ".mp4"}
                else ("audio/wav" if suffix == ".wav" else "audio/webm"),
                "quality_flags": flags,
                "signal_features": features,
            }
    finally:
        SLOTS.release()


def signal_features(pcm):
    samples = array("h")
    samples.frombytes(pcm)
    import sys

    if sys.byteorder != "little":
        samples.byteswap()
    n = len(samples)
    if not n:
        raise HTTPException(422, "No decoded samples")
    energy = sum(float(s) * s for s in samples) / n
    rms = math.sqrt(energy) / 32768
    peak = max(abs(s) for s in samples) / 32768
    clipping = sum(abs(s) >= 32760 for s in samples) / n
    crossings = sum((a < 0) != (b < 0) for a, b in pairwise(samples))
    flags = []
    if rms < 0.001:
        flags.append("silence_or_very_low_signal")
    if clipping > 0.005:
        flags.append("clipping")
    # A few fixed-band Goertzel measurements: actual signal data, not a drawn placeholder.
    window = min(4096, n)
    starts = sorted({0, max(0, n // 2 - window // 2), max(0, n - window)})
    bands = {}
    for frequency in (125, 250, 500, 1000, 2000, 4000):
        powers = []
        coefficient = 2 * math.cos(2 * math.pi * frequency / 16000)
        for start in starts:
            s1 = s2 = 0.0
            for index, sample in enumerate(samples[start : start + window]):
                taper = 0.5 - 0.5 * math.cos(2 * math.pi * index / max(1, window - 1))
                s0 = sample / 32768 * taper + coefficient * s1 - s2
                s2, s1 = s1, s0
            powers.append(max(0.0, (s1 * s1 + s2 * s2 - coefficient * s1 * s2) / window**2))
        bands[str(frequency)] = round(median(powers), 10)
    return {
        "analysis_sample_rate_hz": 16000,
        "rms_full_scale": round(rms, 7),
        "peak_full_scale": round(peak, 7),
        "clipped_sample_fraction": round(clipping, 7),
        "zero_crossing_rate_per_second": round(crossings / (n / 16000), 3),
        "band_probe_power": bands,
        "method": "Mono 16 kHz PCM derivative; RMS and fixed-frequency Goertzel probes over up to three Hann windows. Originals preserved.",
    }, flags


def persist_original(files, content):
    digest = hashlib.sha256(content).hexdigest()
    destination = files / digest
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise HTTPException(409, "Stored original failed integrity check")
        return digest
    descriptor, temporary = tempfile.mkstemp(prefix=".audio-", dir=files)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
            if os.name != "nt":
                directory = os.open(files, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except FileExistsError:
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise HTTPException(409, "Concurrent original integrity conflict")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return digest


def compare_recordings(first, second):
    warnings = []
    if first.id == second.id or first.sha256 == second.sha256:
        warnings.append("The selected recordings contain identical original bytes")
    for key in (
        "operating_mode",
        "load",
        "rpm",
        "microphone_distance_cm",
        "device",
        "background_noise",
        "signal_processing",
        "temperature_c",
        "humidity_percent",
    ):
        a, b = getattr(first, key), getattr(second, key)
        if a is None or b is None or str(a).lower() in {"unknown", ""} or str(b).lower() in {"unknown", ""}:
            warnings.append(f"{key}: conditions were not recorded sufficiently")
        elif a != b:
            warnings.append(f"{key}: capture conditions differ")
    if first.quality_flags or second.quality_flags:
        warnings.append("One or both clips have signal quality warnings")
    if first.capture_type != "machine_acoustic" or second.capture_type != "machine_acoustic":
        warnings.append("Only dedicated machine-acoustic samples are comparable")
    if first.physical_asset_id != second.physical_asset_id:
        raise HTTPException(422, "Acoustic comparison requires the same confirmed physical machine")
    if first.signal_processing != "none_requested":
        warnings.append("Capture processing cannot establish a repeatable raw measurement")
    delta = second.signal_features.get("rms_full_scale", 0) - first.signal_features.get("rms_full_scale", 0)
    conclusion = (
        "Signal feature difference observed; capture conditions prevent attribution to machine deterioration."
        if warnings
        else "Signal features differ under recorded comparable conditions; this is not a fault diagnosis."
    )
    return {
        "comparable": not warnings,
        "warnings": warnings,
        "features": {
            "first": first.signal_features,
            "second": second.signal_features,
            "rms_full_scale_difference": round(delta, 7),
        },
        "conclusion": conclusion + " Sound does not establish repair, commissioning or investment outcome.",
    }
