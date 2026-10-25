"""Source-linked rules and deterministic registry resolution. No authenticity judgments."""

import json
import re
from datetime import date

from app.identifiers import UNCERTAIN, code_fields, normalized

RULES = {
    "commissioning_certificate": (
        "commissioning certificate",
        "commissioning completed",
        "commissioned: true",
    ),
    "technical_specification": (
        "technical specification",
        "specification sheet",
        "rated voltage",
        "rated power",
    ),
    "purchase_invoice": ("purchase invoice", "invoice number", "invoice_ref", "invoice no"),
    "purchase_order": ("purchase order", "order number", "purchase_order_number"),
    "machine_nameplate": ("nameplate", "serial plate", "motor plate"),
    "inspection_report": ("inspection report", "inspection findings"),
    "maintenance_record": ("maintenance log", "maintenance record", "service history", "corrective action"),
    "installation_evidence": ("installation record", "installation evidence", "installed: true"),
}
ALIASES = {
    "asset_id": r"(?:asset(?:\s*id)?|equipment\s*id|machine\s*id)",
    "manufacturer": r"(?:manufacturer|maker|brand)",
    "model_number": r"(?:model(?:\s*(?:number|no\.?))?|type)",
    "serial_number": r"(?:ser(?:ial)?(?:\s*(?:number|no\.?))?|s/n|s\.n\.?)",
    "site": r"(?:site|location)",
    "document_reference": r"(?:document\s*(?:reference|ref)|certificate\s*(?:reference|no\.?|number))",
    "document_date": r"(?:document\s*date|date)",
    "supplier": r"(?:supplier|vendor)",
    "purchase_order_number": r"(?:purchase[ _]order[ _](?:number|no\.?|ref)|po\s*(?:number|no\.?))",
    "invoice_number": r"(?:invoice[ _](?:number|no\.?|ref))",
    "payment_ref": r"payment[ _](?:reference|ref)",
    "rated_power_kw": r"(?:rated\s*)?power(?:\s*\(kw\)|_kw)?",
    "rated_voltage_v": r"(?:rated\s*)?voltage(?:\s*\(v\)|_v)?",
    "rated_speed_rpm": r"(?:rated\s*)?(?:speed|rpm)(?:\s*\(rpm\)|_rpm)?",
    "commissioning_date": r"commissioning[ _]date",
    "inspector_name": r"inspector(?:\s*name)?",
    "amount": r"(?:total\s*)?amount",
    "currency": r"currency",
    "commissioned": r"commissioned",
    "installed": r"installed",
}


def classify(text, media_type):
    if media_type.startswith("audio/"):
        return "acoustic_recording", "media_type; purpose requires review"
    lowered = text.casefold()
    scores = {category: sum(phrase in lowered for phrase in phrases) for category, phrases in RULES.items()}
    best = max(scores, key=scores.get)
    # Explicit headings win over incidental references in the body.
    heading = "\n".join(lowered.splitlines()[:5])
    for category, phrases in RULES.items():
        if phrases[0] in heading:
            return category, "keyword_heading_v1; uncalibrated"
    return (best if scores[best] else "other"), "keyword_rules_v1; uncalibrated"


def extract_fields(pages):
    fields = []
    for page in pages:
        text = page.get("text", "")
        for name, alias in ALIASES.items():
            for match in re.finditer(
                rf"^\s*{alias}\s*[:=#]\s*([^\r\n]{{1,200}})", text, re.IGNORECASE | re.MULTILINE
            ):
                value = match.group(1).strip()
                state = "partial" if UNCERTAIN.search(value) else "machine_read_unconfirmed"
                if name.endswith("_date"):
                    try:
                        date.fromisoformat(value)
                    except ValueError:
                        state = "invalid_format"
                if name in {"rated_power_kw", "rated_voltage_v", "rated_speed_rpm", "amount"}:
                    numeric = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(kW|V|RPM)?", value, re.IGNORECASE)
                    state = state if numeric else "ambiguous_numeric_format"
                fields.append(
                    {
                        "name": name,
                        "value": value,
                        "page": page["page"],
                        "video_timestamp": page.get("timestamp"),
                        "source_text": match.group(0).strip(),
                        "start": match.start(1),
                        "end": match.end(1),
                        "bounding_box": None,
                        "method": page.get("method", "text") + "+key_value_v1",
                        "uncertainty": state,
                        "human_confirmed": False,
                    }
                )
        for code in page.get("codes", []):
            parsed = code_fields(code["text"])
            try:
                payload = json.loads(code["text"])
                if (
                    isinstance(payload, dict)
                    and isinstance(payload.get("asset_id"), str)
                    and 0 < len(payload["asset_id"]) <= 200
                ):
                    parsed["asset_id"] = [payload["asset_id"]]
            except (ValueError, TypeError):
                pass
            # Explicit app asset tags are context only, never physical proof.
            if re.fullmatch(r"CNC-\d{3,8}", code["text"], re.IGNORECASE):
                parsed = {"asset_id": [code["text"]]}
            for key, values in parsed.items():
                name = {"serial": "serial_number", "model": "model_number"}.get(key, key)
                for value in values:
                    fields.append(
                        {
                            "name": name,
                            "value": value,
                            "page": page["page"],
                            "video_timestamp": page.get("timestamp"),
                            "source_text": code["text"],
                            "start": None,
                            "end": None,
                            "bounding_box": code.get("bounding_box"),
                            "method": code["format"],
                            "uncertainty": "partial"
                            if UNCERTAIN.search(value)
                            else "machine_read_unconfirmed",
                            "human_confirmed": False,
                        }
                    )
    return fields[:200]


def values(fields, name):
    return {
        normalized(f["value"])
        for f in fields
        if f["name"] == name and f.get("uncertainty") != "invalid_format"
    }


def resolve(fields, assets, asset_hint=None):
    manufacturers = values(fields, "manufacturer")
    serials, tags, models = (values(fields, n) for n in ("serial_number", "asset_id", "model_number"))
    partial = any(UNCERTAIN.search(v) for v in serials | tags)
    candidates = []
    for asset in assets:
        matched, conflicts = [], []
        for name, observed, expected in (
            ("serial", serials, asset.serial),
            ("asset_id", tags, asset.tag),
            ("model", models, asset.model),
            ("manufacturer", manufacturers if asset.manufacturer else set(), asset.manufacturer),
        ):
            if observed:
                (matched if normalized(expected) in observed else conflicts).append(name)
        if matched or asset.id == asset_hint:
            candidates.append(
                {
                    "asset_id": asset.id,
                    "tag": asset.tag,
                    "serial": asset.serial,
                    "model": asset.model,
                    "matching_identifiers": matched,
                    "conflicting_identifiers": conflicts,
                    "hint_only": not matched,
                }
            )
    serial_matches = [a for a in assets if normalized(a.serial) in serials]
    tag_matches = [a for a in assets if normalized(a.tag) in tags]
    if len(serials) > 1 or len(tags) > 1:
        decision = "MULTIPLE_OR_CONFLICTING_IDENTIFIERS"
    elif serials and tags and {a.id for a in serial_matches} != {a.id for a in tag_matches}:
        decision = "CONTRADICTORY_IDENTIFIERS"
    elif partial:
        decision = "PARTIAL_IDENTIFIER"
    elif serials and len(serial_matches) == 1:
        a = serial_matches[0]
        decision = "EXACT_SERIAL_CANDIDATE"
        if (models and normalized(a.model) not in models) or (asset_hint and a.id != asset_hint):
            decision = "CONTEXT_CONFLICT"
    elif serials:
        decision = "DUPLICATE_REGISTRY_SERIAL" if len(serial_matches) > 1 else "UNKNOWN_SERIAL"
    elif tags and len(tag_matches) == 1:
        decision = "ASSET_TAG_CONTEXT_ONLY"
    elif models:
        decision = "MODEL_ONLY_NOT_IDENTITY"
    else:
        decision = "UNASSIGNED"
    return {
        "decision": decision,
        "candidates": candidates,
        "automatic_association": False,
        "reason": "Analyst review required. Filenames and model-only matches never establish physical identity.",
    }


def proposed_facts(fields):
    mapping = {
        "serial_number": "serial",
        "model_number": "model",
        "site": "site",
        "invoice_number": "invoice_ref",
        "payment_ref": "payment_ref",
        "amount": "amount",
        "currency": "currency",
        "commissioned": "commissioned",
        "installed": "installed",
    }
    facts = {}
    for source, target in mapping.items():
        found = [f for f in fields if f["name"] == source and f["uncertainty"] == "machine_read_unconfirmed"]
        if len({normalized(f["value"]) for f in found}) == 1:
            value = found[0]["value"]
            if target in {"commissioned", "installed"}:
                if value.casefold() not in {"true", "false"}:
                    continue
                value = value.casefold() == "true"
            facts[target] = value
    return facts
