# Capital Deployment Integrity

V2 field engineering build: [startup, API/device contract, frontend handoff and tablet checks](docs/v2-field-bench.md).
Open `/field-test` for the functional capture/review client; `/app` remains the separate polished frontend.

**V2 backend checkpoint:** see [scope, startup and verification status](docs/v2-backend.md). The `codex/v2-backend` branch adds persistent repeat-visit cases, investment projects, audited closure workflows, protected audio, Google Gemini adapters, PDF exports and local test-inbox reminders. `/backend-test` is a verification workspace; the existing four-screen frontend has not yet been redesigned for V2. The V1 documentation below describes the preserved baseline.

Connected Japan Day hackathon POC: a FastAPI/Pydantic backend and a warm, guided four-screen browser app, served by one process. SQLite is the minimal local database; the uploaded backend also adds Postgres/Supabase support. Original evidence is stored persistently by SHA-256. PDF text extraction, Tesseract OCR and manual analyst review work without a vision API. Prepared synthetic Plant A exercises six atomic claims for three CNC machines.

Start with the [connected trial walkthrough](docs/frontend-handoff.md), [deployment guide](docs/backend-deployment.md), and [uploaded backend integration record](docs/imports/2026-10-24-backend-zip.md).

## Requirements and source status

The detailed implementation request dated 24 October 2026 is the available product baseline. The referenced chat was read: its user decisions are available, but assistant specifications appear only as content-reference placeholders. The six-page `/mnt/data/japanday hackathon .pdf` is **not present** in this local workspace, `/mnt/data`, or the mirrored project sources. PDF-specific requirements have not been verified. See [requirements and decisions](docs/requirements.md). Synced `sources/` and `AGENTS.md` remain unchanged.

Implementation runs in this local Work workspace. No model switch was performed or claimed.

## Run locally

Use Python 3.12+. From this repository:

```sh
# macOS (Linux: apt-get install tesseract-ocr poppler-utils)
brew install tesseract poppler
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python scripts/configure.py
.venv/bin/python -m scripts.serve
```

Open **http://127.0.0.1:8000/app** and enter the `CDI_ANALYST_TOKEN` value from the private `.env`. The judge key gives read-only access. The configuration script generates these keys once, retains existing configuration, and never embeds them in browser assets. Browser sign-in uses a persistent opaque session and CSRF protection. API clients can continue using `Authorization: Bearer <token>`.

Choose **Prepare fresh Plant A trial** to begin directly in the browser. Uploading/extracting a certificate does not establish support: confirm, link and reconcile before reviewing the result. The [step-by-step trial](docs/frontend-handoff.md#first-trial) ends with CNC-002 supported and its earlier unresolved finding visible in History.

`/health`, `/ready`, sign-in and static assets are public; inspection data and `/openapi.json` require a valid analyst/judge session or bearer key. All writes require analyst access.
In another terminal, from this repository:

```sh
set -a
. ./.env
set +a
.venv/bin/python -m scripts.demo --output output/plant-a-export.json
```

The script creates and confirms declarations, imports actual synthetic PDF invoices, extracts text, runs image OCR, confirms/corrects extracts, links evidence, records observations, creates follow-ups, reconciles, and reviews each finding. It completes the review while preserving unresolved claims. Re-running a completed seed reuses it; `--name` can create a separate demo.

Use `CDI_ANALYST_TOKEN` or `CDI_JUDGE_TOKEN` from `.env` in an API client. To fetch the contract:

```sh
curl -H "Authorization: Bearer $CDI_JUDGE_TOKEN" http://127.0.0.1:8000/openapi.json
```

A generated [OpenAPI contract](docs/openapi.json) is also checked into the working files. The browser app is at `/app`; interactive Swagger is disabled. Never put an analyst key in a public bundle or URL.

## Expected Plant A result

| Asset | Condition | Purchase/payment | Installation | Commissioning |
|---|---|---|---|---|
| CNC-001 | Operating | Supported | Supported | Supported; certificate reviewed |
| CNC-002 | Operating | Supported | Supported | Unresolved; certificate missing |
| CNC-003 | Packaged | Supported | Unresolved; clarification requested | Unresolved; certificate missing |

Identity and presence are supported for all three prepared machines. There are 18 atomic claims: 15 supported and 3 unresolved. Blurry, unreadable, duplicate and conflicting identifiers are exercised separately in failure tests; they are not hidden in the successful seed.

## API workflow

All paths below are under `/api/v1`. UUIDs are returned by creation operations. See [the integration guide](docs/api.md) for body examples and version handling.

| Method | Path | Purpose |
|---|---|---|
| POST / GET | `/inspections` | Set up / list inspections |
| GET | `/inspections/{iid}` | Current review state |
| POST | `/inspections/{iid}/assets` | Declare machine and six atomic claims |
| PATCH | `/inspections/{iid}/assets/{aid}` | Audited declaration correction; resets claim confirmation |
| GET | `/inspections/{iid}/claims` | Declarations and confirmation versions |
| PATCH | `/inspections/{iid}/claims/{cid}/confirmation` | Confirm or revoke a declaration |
| POST / GET | `/inspections/{iid}/evidence` | Multipart import / list evidence |
| GET | `/inspections/{iid}/evidence/{eid}` | Extracted text, OCR result, facts, quality and provenance |
| GET | `/inspections/{iid}/evidence/{eid}/original` | Integrity-checked original download |
| POST | `/inspections/{iid}/evidence/{eid}/extract` | Real text extraction / OCR; acceptance resets |
| PATCH | `/inspections/{iid}/evidence/{eid}/correction` | Analyst correction, flags and acceptance |
| POST | `/inspections/{iid}/evidence-links` | Supports / contradicts / context, with locator |
| POST | `/inspections/{iid}/evidence-links/{lid}/retract` | Retract without deleting history |
| GET | `/inspections/{iid}/mission` | Deterministic asset checklist and next actions |
| POST | `/inspections/{iid}/observations` | Timestamped analyst or management statement |
| POST | `/inspections/{iid}/reconcile` | Deterministic current findings; unchanged basis reuses findings |
| PATCH | `/inspections/{iid}/findings/{fid}/review` | Reviewed conclusion/override, separate from computed result |
| POST | `/inspections/{iid}/review-complete` | Requires all declarations confirmed and current findings reviewed |
| POST / GET | `/inspections/{iid}/follow-ups` | Open / list requests |
| PATCH | `/inspections/{iid}/follow-ups/{aid}` | Resolve or reopen with explanation |
| GET | `/inspections/{iid}/review-events` | Immutable before/after audit history |
| GET | `/inspections/{iid}/export` | Complete typed JSON report and historical findings |
| GET | `/inspections/{iid}/report` | Plain-text assessment with actions and contextual observations |

## Storage, extraction and rules

`CDI_DATA_DIR` defaults to `data/`. With SQLite it contains `integrity.sqlite3` (plus WAL/SHM while running) and `files/<sha256>`. With `DATABASE_URL`, typed rows and sessions are in Postgres while original files remain in that same persistent directory. Both must survive deployment restarts. One host, one service worker, local persistent disk; do not place a WAL database on shared network storage. Related changes and audit events commit in one database transaction. Audit mutation triggers protect the event table in both database adapters. File writes are flushed before DB references commit; a crash may leave an unreferenced file, never an intentionally overwritten original.

PDF, JPEG, PNG and UTF-8 TXT imports are supported. Limits: 12 MiB per original, 12 PDF pages, 20 megapixels per image. MIME/extension/signature checks reject malformed files; encrypted PDFs are rejected. PDF parsing and OCR run in bounded subprocesses with timeouts, CPU limits, and a Linux memory ceiling. Scanned PDF pages use Poppler then Tesseract. Forced OCR handles PDFs with a text header over a scanned body. PDF previews are rendered in bounded workers so they also work in browsers without an inline PDF viewer. Original bytes are retained even when extraction fails. OCR failure is explicit (`failed`, `incomplete`) and allows analyst correction; it is never fabricated success.

The deterministic extraction adapter reads simple `field: value` lines for serial, model, site, invoice/payment references, amount/currency and condition fields. Arbitrary invoice layouts, tables, multiple machines per page, and handwriting need manual structuring/correction. Page text and method are retained. Machine-condition judgments come from the analyst, not OCR. Confidence is optional analyst metadata, not a probability of truth. Low quality flags require analyst clarification; flag changes are audited.

Core rules:

- A declaration's `confirmed` means the analyst checked what is being claimed; it does not mean the claim is supported.
- Only accepted, integrity-checked, linked evidence contributes to computation. Contextual statements never establish core claims.
- Identity needs exact normalized serial (case/outer whitespace only) plus matching model and site. Duplicate or unreadable identifiers cannot establish identity. Accepted conflicting identifiers trigger clarification.
- Purchase compares invoice and equipment register/declared-asset identifier, reference, amount and currency. Payment requires matching payment reference and an invoice pair with matching invoice reference, amount and currency. V1 handles one full equipment payment, not installment aggregation, taxes, FX or bank-ledger verification.
- A sighting supports presence only. It cannot establish purchase, payment, installation or commissioning. No sighting is not proof of absence. Explicit accepted negative observations can create a potential inconsistency.
- Installation needs an explicit analyst observation or installation record. Packaged equipment with no explicit installation assessment remains unresolved and prompts clarification.
- Commissioning requires an accepted certificate tied to the machine; operating condition is insufficient.
- Every accepted relevant linked item is considered. Conflicts are retained, rather than selecting only favorable evidence. Findings retain a fingerprint of their evidence/declaration/link basis and rule version.
- Evidence, declarations or link changes invalidate current findings/reviews. Reconciliation retains prior findings; all corrections and overrides retain before/after audit records. Follow-up lifecycle edits do not change evidentiary support.
- Review completion can coexist with unresolved findings and open follow-ups. Every current finding must be reviewed first. Reports keep computed and reviewed conclusions visibly separate.

## Controlled team/judge deployment

```sh
.venv/bin/python scripts/configure.py   # once, if .env does not exist
# Add a private DATABASE_URL for this Postgres Compose setup; see deployment guide.
docker compose up -d --build
# Stop/recreate safely; named volume remains:
docker compose down
docker compose up -d
```

Compose uses a non-root service, read-only application filesystem, bounded temporary storage, one named persistent volume and restart policy. It binds only to host loopback. For the three laptops/judges, put the host behind your team's VPN or an HTTPS reverse proxy with an explicit access allowlist; preserve bearer authentication. The bundled UI uses the same origin and needs no CORS allowlist. If using a separate client, set `CDI_CORS_ORIGINS` to its exact origins, separated by commas, then restart. CORS does not provide authentication. Never enable wildcard origins or open an unencrypted public demo port. The demo is for synthetic evidence only.

No external host was provided, so no remote service was deployed. Docker configuration is supplied, but the local Docker daemon was unavailable and the container build/run was not verified. Actual native Uvicorn startup and restart were verified separately.

Back up consistently from the same host (destination must be new and outside the data directory):

```sh
set -a
. ./.env
set +a
.venv/bin/python -m scripts.backup /absolute/path/to/new-backup-directory
```

To restore, stop the server, point `CDI_DATA_DIR` to that backup directory, and restart. Retain `.env` separately and protect it. For Docker, stop the service and restore the backup into the named volume with UID/GID 10001. Do not use `docker compose down -v` unless intentionally deleting all demo data. Back up both the database and files, not just one.

## Verification

```sh
.venv/bin/pytest -q
.venv/bin/ruff check app scripts tests
# Real TCP startup + full seed + process restart (stops its test server afterward):
set -a
. ./.env
set +a
.venv/bin/python -m scripts.verify_live
```

See [test and live verification evidence](docs/verification.md), [actual HTTP result](output/verification.json), [sample assessment](output/plant-a-report.txt), and [complete synthetic export](output/plant-a-export.json).

Limits: single-team demo tokens, no multi-tenant permission model; no vision inference, smart-glasses stream, full financial underwriting, autonomous fraud detection, malware scanner, forensic audit ledger, or verified remote hosting. A DB/file administrator can alter storage; digest checks and API audit immutability are not a substitute for externally anchored records. The current test stack emits one non-failing Starlette warning about its future HTTP client migration.

## Latest live demo change

The subsequent user-requested certificate acceptance test resolved CNC-002 commissioning using a clearly labeled synthetic PDF. Upload/extraction alone left it unresolved; analyst acceptance and reconciliation changed it to supported while preserving the previous finding. The live Plant A inspection now has **16 supported / 2 unresolved** claims. See [test results](output/certificate-flow/result.json) and [updated assessment](output/certificate-flow/assessment-after.txt). The earlier 15/3 export is retained as the original baseline.

The [connected frontend guide](docs/frontend-handoff.md) describes the implemented four-screen browser app. It combines the earlier functional plan into Overview, Evidence, Site inspection and Assessment, with shared Requests/Activity/History trays. The actual browser trial and exports are saved in [output/ui-trial](output/ui-trial/).

## Source control and future updates

This project is maintained in a private GitHub repository. See [the changelog](CHANGELOG.md) for the build's actual scope and limitations, and [the contribution workflow](CONTRIBUTING.md) for the owner's instruction to commit and push future tested codebase changes. GitHub Actions checks tests, formatting and static analysis on each push. Credentials, runtime databases/storage and synced ChatGPT project references are excluded from source control.

## Frontend layout concepts

[Compare 20 generated layout mockups](docs/design-exploration/README.md): five density/style directions for each of the four proposed trial pages. These are concept images, not implemented frontend screens or approved scope changes. Prompts are included with the gallery.

[Labelled Theme A guide](docs/design-exploration/labelled-theme-a/README.md): the four simple screens annotated with each section's role, scan-derived data, analyst edits and judge access.

## Proposed next product direction

[Japan wearables and a focused business/feature direction](docs/product-direction-2026-10-24.md) records checked hardware capabilities and proposed voice-linked capture, an end-of-visit evidence check and idle-equipment blocker follow-ups. These are research proposals, not implemented features or changes to the locked claim rules.
