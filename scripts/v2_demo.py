"""Explicit, synthetic two-visit fixture through real API calls. Never resets old cases."""

import argparse
import io
import json
import math
import os
import struct
import wave
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from scripts.demo import PREFIX, link, ok

COMPANY = "SYNTHETIC V2 demonstration company"


def post(client, url, body):
    return ok(client.post(url, json=body, headers={"Idempotency-Key": str(uuid4())}))


def synthetic_audio(frequency):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(
            b"".join(
                struct.pack("<h", int(6000 * math.sin(2 * math.pi * frequency * n / 16000)))
                for n in range(16000)
            )
        )
    return stream.getvalue()


def add_audio(client, root, inspection_id, physical_id, frequency, note):
    metadata = {
        "inspection_id": inspection_id,
        "physical_asset_id": physical_id,
        "capture_type": "machine_acoustic",
        "captured_at": datetime.now(UTC).isoformat(),
        "device": "Synthetic fixture generator, not a machine sensor",
        "operating_mode": "unknown",
        "note": note,
        "consent_confirmed": True,
        "consent_note": "Generated sine-wave test audio; contains no person or actual machinery",
        "synthetic": True,
        "share_with_judges": True,
        "reason": "Demonstrate persistent real media storage only",
    }
    return ok(
        client.post(
            root + "/audio",
            data={"metadata": json.dumps(metadata)},
            files={"file": ("synthetic-demo.wav", synthetic_audio(frequency), "audio/wav")},
            headers={"Idempotency-Key": str(uuid4())},
        )
    )


def seed(client, actor, fresh=False):
    existing = [c for c in ok(client.get(PREFIX + "/cases")) if c["company"] == COMPANY]
    if existing and not fresh:
        case = existing[-1]
        root = PREFIX + "/cases/" + case["id"]
        snapshot = ok(client.get(root + "/export"))
        if len(snapshot["v1_inspections"]) < 2 or len(snapshot["audio"]) < 2 or not snapshot["targets"]:
            raise RuntimeError(
                "An earlier partial fixture was retained. Use --fresh to create a new separate demo."
            )
        return {"case_id": case["id"], "reused": True, "root": root}
    visit1 = post(
        client, PREFIX + "/demo/prepare", {"reason": "Create separate V1 synthetic baseline for V2"}
    )
    url1 = PREFIX + "/inspections/" + visit1["id"]
    baseline = ok(client.get(url1 + "/export"))
    original_finding_ids = [f["id"] for f in baseline["findings"]]
    case = post(
        client,
        PREFIX + "/cases",
        {
            "inspection_id": visit1["id"],
            "company": COMPANY,
            "site": "Plant A",
            "timezone": "Asia/Tokyo",
            "reason": "Explicit repeat-inspection case",
        },
    )
    root = PREFIX + "/cases/" + case["id"]

    def selected(snapshot):
        asset = next(a for a in snapshot["assets"] if a["tag"] == "CNC-003")
        evidence = next(
            e
            for e in snapshot["evidence"]
            if e["kind"] == "equipment_register" and e["facts"]["serial"] == asset["serial"]
        )
        return asset, evidence

    old1, proof1 = selected(baseline)
    physical = post(
        client,
        root + "/physical-assets",
        {
            "inspection_id": visit1["id"],
            "local_asset_id": old1["id"],
            "identity_evidence_id": proof1["id"],
            "identity_locator": "Prepared synthetic identity record, row 1",
            "reason": "Analyst confirms the synthetic old machine identity",
        },
    )["physical_asset"]
    session = post(
        client,
        root + "/interviews",
        {
            "inspection_id": visit1["id"],
            "physical_asset_id": physical["id"],
            "speaker_label": "Synthetic plant manager",
            "speaker_confirmed": True,
            "consent_confirmed": True,
            "consent_note": "Scripted synthetic text, no real interview",
            "reason": "Preserve attributed rationale",
        },
    )
    interview_root = root + "/interviews/" + session["id"]
    rationale_text = "The older machine has stopped several times; we are considering a replacement next month. Annual repair costs reached JPY 3 million and the proposed replacement budget is JPY 12 million."
    rationale = post(
        client,
        interview_root + "/segments",
        {
            "text": "古い機械は何度も停止しています。来月、交換を検討しています。年間修理費は300万円で、交換機械の予定予算は1200万円です。",
            "language": "ja",
            "english_translation": rationale_text,
            "translation_origin": "human",
            "mode": "synthetic_transcript",
            "reason": "Known scripted bilingual demonstration, not live speech",
        },
    )
    rationale_source = {
        "kind": "interview",
        "attribution": "Synthetic plant manager",
        "quote": rationale_text,
        "segment_id": rationale["id"],
        "segment_version": rationale["version"],
    }
    project = post(
        client,
        root + "/investments",
        {
            "inspection_id": visit1["id"],
            "title": "Proposed CNC-003 replacement",
            "kind": "replacement",
            "rationale": "Management reports recurring stops and annual repair spend of JPY 3 million; maintenance records are missing.",
            "proposed_amount": "12000000",
            "currency": "JPY",
            "source": rationale_source,
            "asset_links": [{"physical_asset_id": physical["id"], "role": "existing"}],
            "reason": "Store synthetic proposal and rationale, without asserting actual expenditure",
        },
    )
    forecast_text = "We expect downtime to fall by 60% after replacement."
    forecast = post(
        client,
        interview_root + "/segments",
        {
            "text": "交換後は停止時間が60パーセント減ると期待しています。",
            "language": "ja",
            "english_translation": forecast_text,
            "translation_origin": "human",
            "mode": "synthetic_transcript",
            "reason": "Preserve original forecast and reviewed demo translation",
        },
    )
    forecast_source = {
        "kind": "interview",
        "attribution": "Synthetic plant manager",
        "quote": forecast_text,
        "segment_id": forecast["id"],
        "segment_version": forecast["version"],
    }
    target = post(
        client,
        root + "/investments/" + project["id"] + "/targets",
        {
            "inspection_id": visit1["id"],
            "metric": "downtime_hours",
            "unit": "hours/month",
            "target_type": "reduction_percent",
            "target_value": "60",
            "relative_months": 6,
            "anchor": "commissioning",
            "source": forecast_source,
            "reason": "Store unmeasured management forecast; baseline remains unknown",
        },
    )
    installation_claim1 = next(
        c for c in baseline["claims"] if c["asset_id"] == old1["id"] and c["kind"] == "installation"
    )
    installation_task = post(
        client,
        root + "/follow-ups",
        {
            "inspection_id": visit1["id"],
            "physical_asset_id": physical["id"],
            "claim_id": installation_claim1["id"],
            "project_id": project["id"],
            "request": "Verify installation of the packaged old machine",
            "contact": "Synthetic plant manager, reported contact",
            "reviewer": actor,
            "due_date": "2026-10-24",
            "required_evidence": "Accepted direct analyst installation observation, reconciled and reviewed for this machine",
            "verification_method": "site_inspection",
            "source": rationale_source,
            "reason": "Track original unresolved deployment finding",
        },
    )
    maintenance_task = post(
        client,
        root + "/follow-ups",
        {
            "inspection_id": visit1["id"],
            "physical_asset_id": physical["id"],
            "project_id": project["id"],
            "request": "Request records substantiating repeat repairs and JPY 3 million annual repair spend",
            "contact": "Synthetic accounts manager, reported contact",
            "reviewer": actor,
            "due_date": "2026-10-24",
            "required_evidence": "Dated service invoices and maintenance history for the identified old machine",
            "verification_method": "document_review",
            "source": rationale_source,
            "reason": "Keep unsupported investment rationale visible",
        },
    )
    first_audio = add_audio(
        client,
        root,
        visit1["id"],
        physical["id"],
        220,
        "Synthetic prior acoustic fixture; load and distance unknown",
    )

    visit2 = post(
        client,
        PREFIX + "/demo/prepare",
        {"reason": "Second separate synthetic visit; original remains unchanged"},
    )
    url2 = PREFIX + "/inspections/" + visit2["id"]
    second = ok(client.get(url2 + "/export"))
    old2, proof2 = selected(second)
    post(
        client,
        root + "/inspections",
        {"inspection_id": visit2["id"], "reason": "Explicitly add follow-up visit"},
    )
    post(
        client,
        root + "/asset-bindings",
        {
            "inspection_id": visit2["id"],
            "local_asset_id": old2["id"],
            "physical_asset_id": physical["id"],
            "identity_evidence_id": proof2["id"],
            "identity_locator": "Prepared second-visit identity record",
            "reason": "Analyst confirms continuity; matching serial alone did not merge records",
        },
    )
    second_audio = add_audio(
        client,
        root,
        visit2["id"],
        physical["id"],
        260,
        "Synthetic later acoustic fixture; changed signal is not a diagnosis",
    )
    comparison = post(
        client,
        root + "/audio-comparisons",
        {
            "first_id": first_audio["id"],
            "second_id": second_audio["id"],
            "reason": "Show actual feature differences and honest comparability warnings",
        },
    )

    transition = root + "/follow-ups/" + installation_task["task"]["id"] + "/transition"
    task = post(
        client,
        transition,
        {
            "version": installation_task["details"]["version"],
            "status": "submitted_for_review",
            "evidence_ids": [proof2["id"]],
            "review_inspection_id": visit2["id"],
            "reason": "A submitted identity record alone cannot prove installation",
        },
    )
    rejected = client.post(
        transition,
        json={
            "version": task["details"]["version"],
            "status": "closed",
            "verification_supported": True,
            "review_inspection_id": visit2["id"],
            "reason": "Adversarial attempt: close installation without supported installation finding",
        },
    )
    if rejected.status_code != 409:
        raise AssertionError("Unsupported installation closure was not rejected")
    task = post(
        client,
        transition,
        {
            "version": task["details"]["version"],
            "status": "needs_more_evidence",
            "reason": "Reviewer requests a direct, appropriate installation observation",
        },
    )
    observation = post(
        client,
        url2 + "/observations",
        {
            "asset_id": old2["id"],
            "text": "SYNTHETIC follow-up observation: authorized analyst confirms installation; commissioning still unverified.",
            "facts": {
                "serial": old2["serial"],
                "model": old2["model"],
                "site": old2["site"],
                "installed": True,
            },
            "source": "analyst",
            "captured_at": datetime.now(UTC).isoformat(),
            "reason": "Synthetic direct observation for a defined installation purpose",
        },
    )
    installation_claim2 = next(
        c for c in second["claims"] if c["asset_id"] == old2["id"] and c["kind"] == "installation"
    )
    link(client, visit2["id"], installation_claim2["id"], observation["evidence_id"], "supports")
    findings = post(
        client, url2 + "/reconcile", {"reason": "Reconcile new accepted installation observation"}
    )
    finding = next(f for f in findings if f["claim_id"] == installation_claim2["id"])
    if finding["computed_status"] != "supported":
        raise AssertionError("Defined installation evidence did not establish its intended atomic claim")
    ok(
        client.patch(
            url2 + "/findings/" + finding["id"] + "/review",
            json={
                "version": finding["version"],
                "status": "supported",
                "reason": "Review synthetic installation finding, without establishing commissioning",
            },
        )
    )
    task = post(
        client,
        transition,
        {
            "version": task["details"]["version"],
            "status": "submitted_for_review",
            "evidence_ids": [observation["evidence_id"]],
            "review_inspection_id": visit2["id"],
            "reason": "Submit appropriate installation evidence",
        },
    )
    closed = post(
        client,
        transition,
        {
            "version": task["details"]["version"],
            "status": "closed",
            "verification_supported": True,
            "review_inspection_id": visit2["id"],
            "reason": "Underlying installation claim is now supported and reviewed; commissioning remains unresolved",
        },
    )

    second_session = post(
        client,
        root + "/interviews",
        {
            "inspection_id": visit2["id"],
            "physical_asset_id": physical["id"],
            "project_id": project["id"],
            "speaker_label": "Synthetic follow-up manager",
            "speaker_confirmed": True,
            "consent_confirmed": True,
            "consent_note": "Scripted synthetic test source",
            "reason": "Link follow-up interview to existing project",
        },
    )
    new_statement = post(
        client,
        root + "/interviews/" + second_session["id"] + "/segments",
        {
            "text": "We still expect downtime to fall by 60%, but the replacement has not been commissioned and baseline measurements are missing.",
            "language": "en",
            "mode": "synthetic_transcript",
            "reason": "Dynamic new source exercises contextual questions",
        },
    )
    analysis = post(
        client,
        root + "/segments/" + new_statement["id"] + "/analyse",
        {
            "reason": "Run configured AI if available; explicitly label any degraded rules fallback",
            "allow_rule_fallback": True,
        },
    )
    reminders = post(
        client, root + "/reminders/run", {"reason": "Demonstrate due request email to local test inbox only"}
    )
    final_baseline = ok(client.get(url1 + "/export"))
    if [f["id"] for f in final_baseline["findings"]] != original_finding_ids:
        raise AssertionError("V2 contextual changes altered original inspection findings")
    return {
        "case_id": case["id"],
        "root": root,
        "reused": False,
        "first_inspection_id": visit1["id"],
        "second_inspection_id": visit2["id"],
        "physical_asset_id": physical["id"],
        "project_id": project["id"],
        "target_id": target["id"],
        "open_maintenance_task_id": maintenance_task["task"]["id"],
        "closed_installation_task_id": closed["task"]["id"],
        "audio_ids": [first_audio["id"], second_audio["id"]],
        "comparison_id": comparison["id"],
        "analysis_provider": analysis["provider"],
        "analysis_id": analysis["id"],
        "reminder_states": [d["status"] for d in reminders],
        "unsupported_closure_rejected": True,
        "original_findings_preserved": True,
        "new_segment_id": new_statement["id"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8002")
    parser.add_argument(
        "--fresh", action="store_true", help="Create a separate fixture; never delete/reset earlier cases"
    )
    parser.add_argument("--output", type=Path, default=Path(".run/v2-demo-result.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False)
    token = os.environ.get("CDI_ANALYST_TOKEN", "")
    if not token:
        raise SystemExit("Configure the private .env first")
    principal = json.loads(os.environ["CDI_TOKENS"])[token]
    with httpx.Client(base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=90) as client:
        result = seed(client, principal["actor"], args.fresh)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
