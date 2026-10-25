"""Source-separated identifier candidates and conservative deterministic comparison."""

import json
import re

FIELDS = ("manufacturer", "model", "serial", "site")
UNCERTAIN = re.compile(r"[?*\ufffd]|\[unclear\]", re.IGNORECASE)


def normalized(value):
    # Punctuation is meaningful; never substitute characters or remove separators.
    return " ".join(str(value or "").split()).casefold()


def parse_fields(text):
    patterns = {
        "serial": r"(?:serial(?:\s*(?:no\.?|number))?|s/n)",
        "model": r"model(?:\s*(?:no\.?|number))?",
        "manufacturer": r"(?:manufacturer|maker)",
        "site": r"(?:site|location)",
    }
    fields = {
        key: list(
            dict.fromkeys(
                m.group(1).strip()
                for m in re.finditer(
                    rf"^\s*{pattern}\s*[:#=]\s*([^\r\n]{{1,200}})", text, re.IGNORECASE | re.MULTILINE
                )
            )
        )[:20]
        for key, pattern in patterns.items()
    }
    # Nameplate tables often print Model No. and Serial No. on one line,
    # without a colon. Read only a single explicit label-following token.
    for key in ("model", "serial"):
        inline = re.findall(
            rf"\b{key}\s+(?:no\.?|number)\s+([A-Za-z0-9][A-Za-z0-9_./-]{{1,79}})(?=\s|$)",
            text,
            re.IGNORECASE,
        )
        fields[key] = list(dict.fromkeys(fields[key] + inline))[:20]
    return fields


def code_fields(payload):
    """A structured payload or an unambiguous plain identifier; URLs stay raw."""
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        value = None
    if isinstance(value, dict):
        return {
            k: [v.strip()]
            for k, v in value.items()
            if k in FIELDS and isinstance(v, str) and 0 < len(v.strip()) <= 200
        }
    if re.fullmatch(r"[A-Za-z0-9?*][A-Za-z0-9?*\ufffd_./-]{2,80}", payload or ""):
        return {"serial": [payload]}
    return {}


def compare_scan(scan, expected):
    sources = [{"source": "ocr", "fields": scan.get("ocr_fields") or parse_fields(scan.get("ocr_text", ""))}]
    for index, code in enumerate(scan.get("codes", [])):
        sources.append(
            {
                "source": "qr" if "qr" in code["format"].casefold() else "barcode",
                "index": index,
                "raw": code["text"],
                "fields": code_fields(code["text"]),
            }
        )
    comparisons, observed = {}, {}
    for field in FIELDS:
        candidates = [
            {"source": s["source"], "value": v} for s in sources for v in s["fields"].get(field, [])
        ]
        unique = {normalized(c["value"]) for c in candidates}
        observed[field] = candidates[0]["value"] if len(unique) == 1 else None
        values = [c["value"] for c in candidates]
        if len(unique) > 1:
            result = "CONFLICTING_SOURCES"
        elif any(UNCERTAIN.search(v) for v in values):
            result = "PARTIAL"
        elif not values:
            result = "MISSING"
        elif not expected.get(field):
            result = "NOT_APPLICABLE"
        elif values[0] == expected[field]:
            result = "EXACT_MATCH"
        elif normalized(values[0]) == normalized(expected[field]):
            result = "NORMALIZED_MATCH"
        else:
            result = "MISMATCH"
        comparisons[field] = {"expected": expected.get(field), "observed": candidates, "state": result}
    states = {c["state"] for c in comparisons.values()}
    flags = set(scan.get("quality_flags", []))
    if "CONFLICTING_SOURCES" in states:
        decision, guidance = (
            "CONFLICTING_SOURCES",
            "OCR and code values disagree. Review every source; do not select only the expected-looking value.",
        )
    elif "PARTIAL" in states:
        decision, guidance = (
            "PARTIAL_IDENTIFIER",
            "An identifier contains uncertain characters. Rescan or correct it against the original.",
        )
    elif "MISMATCH" in states:
        decision, guidance = (
            "IDENTIFIER_MISMATCH",
            "Observed identifiers differ from the selected asset. Check the machine or rescan.",
        )
    elif flags.intersection({"image_too_small", "blur_or_low_detail", "low_contrast"}):
        decision, guidance = (
            "UNREADABLE_OR_BLURRED",
            "Move closer, hold steady and improve lighting. Readability warnings are heuristic.",
        )
    elif not any(s["fields"].get("serial") for s in sources):
        decision, guidance = (
            "NO_IDENTIFIER_FOUND",
            "No usable serial was read. Capture the serial plate or enter a reviewed correction.",
        )
    elif comparisons["serial"]["state"] in {"EXACT_MATCH", "NORMALIZED_MATCH"}:
        decision, guidance = (
            "MATCH_CANDIDATE",
            "Candidate match only. Review the original, missing fields and sources before confirming identity.",
        )
    else:
        decision, guidance = (
            "NEEDS_REVIEW",
            "Select the intended asset and review the identifiers against the original.",
        )
    return {
        "sources": sources,
        "comparison": comparisons,
        "observed_fields": observed,
        "decision": decision,
        "guidance": guidance,
    }
