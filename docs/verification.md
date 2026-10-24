# Verification evidence — 24 October 2026

## Connected browser / uploaded backend update

The combined suite passed **87 tests**, including a real isolated Postgres 16 server, with one non-failing Starlette dependency warning. Static Python checks and JavaScript syntax validation passed. Without `CDI_TEST_DATABASE_URL`, the seven Postgres tests skip explicitly; the SQLite/browser tests still run.

The actual in-app browser completed a fresh synthetic inspection: PDF download/upload, real extraction, rendered original comparison, analyst acceptance, support link, reconciliation, reviewed conclusion, follow-up resolution, explicit re-review of unchanged findings, review completion and text/JSON downloads. Commissioning stayed unresolved before acceptance. The final export has 16 supported / 2 unresolved claims, 18 current findings reviewed, two earlier unresolved CNC-002 findings retained, 164 audit events and two open CNC-003 follow-ups. See [browser result](../output/ui-trial/result.json), [downloaded report](../output/ui-trial/browser-report.txt) and [downloaded export](../output/ui-trial/browser-export.json).

The native app was restarted on port 8002 with the same credentials and saved session. A verified SQLite/files backup moved the trial into persistent project runtime storage; credentials remain in ignored local configuration. An isolated local Postgres database tested JSONB, audit immutability, transaction rollback, concurrent edits, independent readers, browser CSRF/session workflow and synthetic trial creation. A hosted Supabase account, ngrok/HTTPS, the other laptops and Windows execution were not exercised. Docker runtime was unavailable locally; GitHub Actions performs an image build.

Earlier backend-only verification is retained below as historical evidence.

## Automated acceptance/failure tests

Final run: **52 passed**, one non-failing dependency deprecation warning, in 10.39 seconds on Python 3.12.14/macOS. `ruff check app scripts tests` and `ruff format --check app scripts tests` passed.

Coverage includes:

- Full Plant A API setup, actual PDF text extraction, actual Tesseract label OCR, analyst confirmation, links, observations, reconciliation, reviews, completion and reporting.
- Expected CNC-001 reviewed certificate; CNC-002 operating without certificate; CNC-003 packaged with unverified installation.
- Missing evidence never treated as absence; sightings do not establish purchase/payment/installation/commissioning.
- Blurry/unreadable/incomplete/duplicate IDs; duplicate declared serials; exact punctuation-sensitive identifiers; missing model/site corroboration; conflicting accepted identifiers.
- Unconfirmed declarations/evidence, management context and financial statements, explicit contradictory evidence, negative conditions and all-evidence reconciliation.
- Invoice/register discrepancies; decimal payment comparisons; invoice, amount and currency conflicts; conflicting second payments; incomplete financial fields.
- Analyst override retained alongside computed result; stale reviews rejected; historical findings and immutable before/after events preserved.
- Completion with unresolved claims, mutation invalidation, and follow-up resolution never proving a missing certificate.
- Original digest failures, missing/malformed file checks, MIME/extension mismatch, encrypted PDFs, page/byte limits and chunked requests.
- Real scanned-PDF OCR, blank OCR, unavailable OCR binary, parser timeout and conflicting extracted fields.
- Judge read-only authorization, protected schema and reports, forbidden author injection, cross-inspection references, version conflicts and concurrent update races.
- Explicit CORS configuration and fail-closed startup.
- Audited asset corrections and declaration resets.
- Consistent database/files backup restored into a fresh application with identical findings, originals and audit history.
- Naive/future capture timestamps and blank import provenance rejected.

## Real network/process verification

`scripts.verify_live` launched Uvicorn, used actual loopback HTTP, exercised analyst/judge permissions and follow-up resolution/reopening, exported OpenAPI and reports, terminated the process gracefully, restarted it on the same data directory, then checked all records and original digests again.

Final verified result at 12:20 IST:

| Check | Result |
|---|---|
| Server startup | Passed |
| Actual process restart | Passed |
| Synthetic assets / atomic claims | 3 / 18 |
| Computed supported / unresolved | 15 / 3 |
| Original evidence downloads and SHA-256 after restart | 14 / 14 passed |
| Immutable audit events preserved exactly across restart | 152 |
| Analyst writes / judge reads / judge writes denied | Passed |
| Review workflow | Complete with unresolved claims retained |
| Docker Compose static configuration | Passed |

Machine-readable evidence: [`output/verification.json`](../output/verification.json). Startup/shutdown logs: [`output/live-startup.log`](../output/live-startup.log). Actual assessment: [`output/plant-a-report.txt`](../output/plant-a-report.txt). Complete synthetic snapshot: [`output/plant-a-export.json`](../output/plant-a-export.json).

The verifier stops its temporary server. `scripts/run.sh` starts the normal listener on 127.0.0.1:8000 using the same seeded persistent data directory.

## Explicit limits

The six-page source product PDF was not available; PDF-specific product compliance cannot be verified. The referenced chat's assistant specifications were opaque placeholders. The implementation follows the user's detailed request and available user decisions.

The Docker CLI exists, but its daemon socket was unavailable. Compose configuration was validated; image build/container execution and remote hosting were not tested. No remote destination was provided or deployed.

There is no frontend, camera/video capture, AI condition inference, underwriting, live bank integration or general-purpose table extraction. The original files, typed APIs and manual correction workflow are ready for later frontend integration. One Starlette warning notes a future HTTP client migration; it does not affect the passing tests.

## Additional live certificate acceptance test

At the user's request, `scripts.test_certificate_flow` exercised CNC-002 against the running service on 24 October 2026:

- Before: commissioning computed/reviewed unresolved.
- Uploaded a clearly labeled synthetic certificate PDF; real text extraction correctly read machine identity and commissioned=true.
- Linked the still-unconfirmed extract and reconciled: commissioning remained unresolved.
- Analyst accepted it; prior findings became stale and inspection returned to active.
- Reconciled: only CNC-002 commissioning changed, to supported.
- Resolved its certificate request, re-reviewed current findings and completed the review.
- Verified the earlier unresolved finding, earlier audit events and original SHA-256 download were preserved.

**Current live demo now has 16 supported and 2 unresolved claims**, both remaining gaps on CNC-003. The original three-machine baseline above is historical. Evidence: `output/certificate-flow/result.json`, `before.json`, `after.json` and `assessment-after.txt`. The test deliberately retains this change; it does not reset or erase history. Re-running against the already-resolved machine refuses to add duplicate certificates.
