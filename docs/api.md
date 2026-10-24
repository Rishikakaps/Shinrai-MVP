# Backend integration contract

Start with `docs/openapi.json` or authenticated `GET /openapi.json`. The contract contains every strict Pydantic request and response schema. Requests with unknown fields are rejected. `POST` creates inspection, assets, evidence, links, observations and requests; `PATCH` records versioned updates. All paths below are prefixed `/api/v1`.

The frontend has not been designed or built. These are API examples only.

## Typical sequence

1. `POST /inspections` with `{"name":"Plant A","site":"Plant A"}`. Store returned UUID as `iid`.
2. `POST /inspections/{iid}/assets`:

```json
{"tag":"CNC-001","serial":"SYN-001","model":"DemoMill X3","site":"Plant A","invoice_ref":"INV-001","payment_ref":"PAY-001","reason":"Reviewed asset register declaration"}
```

3. Read `/inspections/{iid}/claims`. Six claims are created, initially unconfirmed. For each, `PATCH .../claims/{cid}/confirmation`:

```json
{"version":1,"expected":"SYN-001","confirmed":true,"reason":"Checked declared identity against submitted register"}
```

Use that claim's actual `expected`, not the identity example for every claim. To correct declared identifiers, use `PATCH .../assets/{aid}` with all original asset fields plus `version` and `reason`; this updates linked declarations and resets their confirmation.

4. Multipart `POST .../evidence`: `file`, `kind`, `source`, `captured_at` (ISO 8601 with timezone), `reason`. Capture times cannot be in the future. Financial kinds: `equipment_register`, `declared_asset`, `invoice`, `payment_extract`. Other kinds: `site_image`, `site_observation`, `installation_record`, `commissioning_certificate`, `financial_statement`, `management_statement`.
5. `POST .../evidence/{eid}/extract` with `{"reason":"Extract imported source"}`. Results expose `text`, `facts`, page-level text/method, flags, `extraction_method`, `confirmed:false`, and new `version`. Download the original to review it. Extraction is synchronous and bounded; use a client timeout of 90 seconds.
6. `PATCH .../evidence/{eid}/correction` to accept/reject or correct the text/facts:

```json
{
  "version":2,
  "text":"serial: SYN-001\ninvoice_ref: INV-001\namount: 100000.00\ncurrency: INR",
  "facts":{"serial":"SYN-001","model":"DemoMill X3","site":"Plant A","invoice_ref":"INV-001","amount":"100000.00","currency":"INR"},
  "quality_flags":["manual_correction"],
  "confidence":null,
  "confirmed":true,
  "reason":"Analyst compared extracted fields to original page 1"
}
```

Fact booleans `present`, `installed`, `commissioned` accept true/false/null; `condition` is operating/packaged/idle/unknown. Do not convert packaged into `installed:false` without explicit observation. `amount` uses decimal strings. Quality flags: unreadable, blurry, duplicate_serial, incomplete, manual_correction. Unreadable/blurry/incomplete evidence is excluded from proof. Duplicate serial evidence cannot establish identity.

7. Link each relevant original to each atomic claim it addresses with `POST .../evidence-links`:

```json
{"claim_id":"<claim UUID>","evidence_id":"<evidence UUID>","relation":"supports","locator":"page 1, equipment row 2","reason":"This invoice records the declared machine purchase"}
```

Links are explicit analyst decisions. The engine considers **all** active links for each claim. For a payment claim, link both invoice and payment extract; for purchase, both invoice and register/declared asset. Financial statements/management statements accept only context links. Use `contradicts` for explicit relevant contrary evidence. Retract an incorrect link via `/evidence-links/{lid}/retract` with version/reason; history remains.

8. `GET .../mission` returns asset checklists. `POST .../observations` records analyst-confirmed conditions, or management context:

```json
{"asset_id":"<asset UUID>","text":"Machine packaged; installation unverified","facts":{"serial":"SYN-003","model":"DemoMill X3","site":"Plant A","present":true,"condition":"packaged"},"source":"analyst","captured_at":"2026-01-01T10:00:00Z","reason":"On-site inspection"}
```

The response includes an `evidence_id`; link it to the relevant claims. Analyst observations are accepted records. Management observations remain context even if recorded/confirmed by an analyst. Media uploads use the same evidence route; there is no video stream or vision inference.

9. `POST .../reconcile` with a reason returns the current findings. Persisted `basis_hash` ties them to declarations, accepted evidence state, all links, integrity state and rule version. Each includes explanation, accepted evidence IDs and deterministic next action.
10. `PATCH .../findings/{fid}/review` with `{"version":1,"status":"unresolved","reason":"Missing certificate confirmed with analyst"}`. The reviewed status may differ from computed status; the reason is required. A stale finding returns 409. `POST .../review-complete` requires a reason and every claim confirmed/current finding reviewed. Completion is a workflow status, not support for every claim.
11. `POST .../follow-ups` with claim_id/request/reason. Resolve/reopen through `PATCH .../follow-ups/{aid}` with version/state/resolution/reason. This never proves a claim.
12. `GET .../export` returns the complete typed report, current findings, finding history, original metadata, links, observations, follow-ups and immutable review events. `reconciliation_current:false` means the client must request fresh reconciliation before showing a current assessment. `integrity_issues` lists damaged/missing originals. `GET .../report` is a downloadable plain-text assessment. Statements and original media are accessible through `/evidence/{eid}/original`.

## Versions, history and errors

Use the latest returned `version` for all versioned updates. An outdated version returns 409; reload and show the new state before retrying. Do not silently overwrite a colleague's edit. Source, capture timestamp, receipt timestamp and original digest remain unchanged by extraction corrections. Review events contain server-authored actor, UTC time, reason, and full before/after snapshots.

- 401: missing/incorrect bearer token.
- 403: read-only judge attempted a change.
- 404: unknown UUID or referenced record belongs to a different inspection.
- 409: stale version/finding, duplicate active link/tag, integrity failure or review prerequisites unmet.
- 413: empty/oversized original or request.
- 415: unsupported extension/MIME pairing.
- 422: malformed input/file, invalid timestamp, encrypted/too-many-page PDF, forbidden statement proof link.

Every token belongs to this one demo team and can read its inspections. Inspection-scoped routes prevent accidentally linking one inspection's evidence into another; this is not a multi-tenant isolation system. Keep access controlled. Protect original downloads with the same bearer authentication; never put credentials in query strings.
