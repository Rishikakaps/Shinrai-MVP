"""Live acceptance exercise: CNC-002 missing certificate -> accepted certificate -> supported.
Run against the prepared synthetic Plant A inspection. Saves before/after proof without credentials.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.models import now
from scripts.demo import PREFIX, accept, link, ok, pdf_bytes, upload


def run(client, output):
    output.mkdir(parents=True, exist_ok=True)
    inspections = ok(client.get(PREFIX + "/inspections"))
    inspection = next(i for i in inspections if i["name"] == "Plant A - three CNC machines")
    iid = inspection["id"]
    root = f"{PREFIX}/inspections/{iid}"
    before = ok(client.get(root + "/export"))
    asset = next(a for a in before["assets"] if a["tag"] == "CNC-002")
    claim = next(c for c in before["claims"] if c["asset_id"] == asset["id"] and c["kind"] == "commissioning")
    old = next(f for f in before["findings"] if f["claim_id"] == claim["id"])
    if old["computed_status"] != "unresolved":
        raise RuntimeError("CNC-002 is no longer unresolved; do not add duplicate test certificates")
    (output / "before.json").write_text(json.dumps(before, indent=2))
    reason = "Live acceptance test: analyst reviews synthetic CNC-002 commissioning certificate"
    text = (
        "SYNTHETIC TEST CERTIFICATE - NOT AN OEM DOCUMENT\n"
        f"serial: {asset['serial']}\nmodel: {asset['model']}\nsite: {asset['site']}\n"
        "commissioned: true\n"
    )
    content = pdf_bytes(text)
    ev = upload(
        client,
        iid,
        "commissioning_certificate",
        text,
        "CNC-002-synthetic-certificate.pdf",
        "application/pdf",
        content,
    )
    ev = ok(client.post(root + f"/evidence/{ev['id']}/extract", json={"reason": reason}))
    assert ev["extraction_method"] == "pdf_text"
    assert ev["facts"]["serial"] == asset["serial"]
    assert ev["facts"]["commissioned"] is True
    assert ev["confirmed"] is False
    link(client, iid, claim["id"], ev["id"])
    unaccepted = ok(
        client.post(
            root + "/reconcile", json={"reason": "Verify unaccepted certificate does not prove claim"}
        )
    )
    interim = next(f for f in unaccepted if f["claim_id"] == claim["id"])
    assert interim["computed_status"] == "unresolved"
    ev = accept(client, iid, ev)
    stale = ok(client.get(root + "/export"))
    assert stale["reconciliation_current"] is False and stale["inspection"]["state"] == "active"
    assert stale["findings"] == []
    findings = ok(client.post(root + "/reconcile", json={"reason": reason}))
    current = next(f for f in findings if f["claim_id"] == claim["id"])
    assert current["computed_status"] == "supported"
    assert current["reviewed_status"] is None
    # Confirm the new document changes only the intended atomic conclusion.
    prior = {f["claim_id"]: f["computed_status"] for f in before["findings"]}
    assert all(f["computed_status"] == prior[f["claim_id"]] for f in findings if f["claim_id"] != claim["id"])
    action = next(a for a in before["follow_ups"] if a["claim_id"] == claim["id"] and a["state"] == "open")
    action = ok(
        client.patch(
            root + f"/follow-ups/{action['id']}",
            json={
                "version": action["version"],
                "state": "resolved",
                "resolution": f"Synthetic certificate {ev['id']} received, extracted, accepted and reconciled",
                "reason": reason,
            },
        )
    )
    for finding in findings:
        ok(
            client.patch(
                root + f"/findings/{finding['id']}/review",
                json={
                    "version": finding["version"],
                    "status": finding["computed_status"],
                    "reason": reason
                    if finding["claim_id"] == claim["id"]
                    else "Re-reviewed unchanged claim after new synthetic certificate evidence",
                },
            )
        )
    ok(
        client.post(
            root + "/review-complete",
            json={"reason": "All current findings re-reviewed after certificate test"},
        )
    )
    after = ok(client.get(root + "/export"))
    assert after["reconciliation_current"] and after["inspection"]["state"] == "review_complete"
    preserved = next(f for f in after["finding_history"] if f["id"] == old["id"])
    assert preserved == old
    assert all(e in after["review_events"] for e in before["review_events"])
    downloaded = client.get(root + f"/evidence/{ev['id']}/original")
    downloaded.raise_for_status()
    assert hashlib.sha256(downloaded.content).hexdigest() == ev["sha256"]
    assert not after["integrity_issues"]
    (output / "CNC-002-synthetic-certificate.pdf").write_bytes(downloaded.content)
    (output / "after.json").write_text(json.dumps(after, indent=2))
    (output / "assessment-after.txt").write_text(client.get(root + "/report").text)
    result = {
        "tested_at": now(),
        "transport": "Actual HTTP against local FastAPI service",
        "inspection_id": iid,
        "asset": asset["tag"],
        "claim": "commissioning",
        "before": old["computed_status"],
        "uploaded_but_not_accepted": interim["computed_status"],
        "after_analyst_acceptance_and_reconciliation": current["computed_status"],
        "original_unresolved_finding_preserved": True,
        "earlier_audit_events_preserved": True,
        "stale_reviews_invalidated": True,
        "only_target_claim_changed": True,
        "original_download_digest_verified": True,
        "certificate_follow_up": action["state"],
        "review_state": after["inspection"]["state"],
        "computed_status_counts": {
            s: sum(f["computed_status"] == s for f in after["findings"]) for s in ("supported", "unresolved")
        },
        "evidence_id": ev["id"],
        "evidence_sha256": ev["sha256"],
        "evidence_is_synthetic": True,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return result


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path("output/certificate-flow"))
    args = parser.parse_args()
    with httpx.Client(
        base_url=args.url, headers={"Authorization": "Bearer " + os.environ["CDI_ANALYST_TOKEN"]}, timeout=90
    ) as client:
        run(client, args.output)


if __name__ == "__main__":
    main()
