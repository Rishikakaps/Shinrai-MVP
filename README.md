# Capital Deployment Integrity — Working Model V1

Backend-only Japan Day hackathon implementation. FastAPI/Pydantic, SQLite in WAL mode, SHA-256 addressed original evidence files, local PDF extraction and Tesseract OCR. No vision API or frontend is required. A prepared synthetic Plant A inspection exercises all six claim types for three CNC machines.

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
./scripts/run.sh
```

The API listens on `127.0.0.1:8000`. `GET /health` is the only public route. The configuration script generates separate random analyst and judge credentials in a private, ignored `.env`; it never overwrites an existing file or prints secrets. All `/api/v1` routes and `/openapi.json` require `Authorization: Bearer <token>`. The judge token permits reads only. Credentials identify the audit author; clients cannot supply an author in request bodies.

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

A generated [OpenAPI contract](docs/openapi.json) is also checked into the working files. There is no frontend or browser documentation UI. Do not embed analyst secrets in a public frontend bundle. The later UI should obtain credentials through a controlled session or private demo configuration.

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

`CDI_DATA_DIR` defaults to `data/`. It contains `integrity.sqlite3` (plus WAL/SHM while running) and `files/<sha256>`. Both must survive deployment restarts. One host, one service worker, local persistent disk; do not place a WAL database on shared network storage. Related changes and audit events commit in one SQLite transaction. Audit table UPDATE/DELETE operations are rejected by SQLite triggers. File writes are flushed before DB references commit; a crash may leave an unreferenced file, never an intentionally overwritten original.

PDF, JPEG, PNG and UTF-8 TXT imports are supported. Limits: 12 MiB per original, 12 PDF pages, 20 megapixels per image. MIME/extension/signature checks reject malformed files; encrypted PDFs are rejected. PDF parsing and OCR run in bounded subprocesses with timeouts, CPU limits, and a Linux memory ceiling. Scanned PDF pages use Poppler then Tesseract. Original bytes are retained even when extraction fails. OCR failure is explicit (`failed`, `incomplete`) and allows analyst correction; it is never fabricated success.

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
docker compose up -d --build
# Stop/recreate safely; named volume remains:
docker compose down
docker compose up -d
```

Compose uses a non-root service, read-only application filesystem, bounded temporary storage, one named persistent volume and restart policy. It binds only to host loopback. For the three laptops/judges, put the host behind your team's VPN or an HTTPS reverse proxy with an explicit access allowlist; preserve bearer authentication. Set `CDI_CORS_ORIGINS` to the exact later frontend origins, separated by commas, then restart. CORS does not provide authentication. Never enable wildcard origins or open an unencrypted public demo port. The demo is for synthetic evidence only.

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

Limits: single-team demo tokens, no multi-tenant permission model or login UI; no vision inference, smart-glasses stream, full financial underwriting, autonomous fraud detection, malware scanner, forensic audit ledger, remote hosting, or frontend. A DB/file administrator can alter storage; digest checks and API audit immutability are not a substitute for externally anchored records. The current test stack emits one non-failing Starlette warning about its future HTTP client migration.

## Latest live demo change

The subsequent user-requested certificate acceptance test resolved CNC-002 commissioning using a clearly labeled synthetic PDF. Upload/extraction alone left it unresolved; analyst acceptance and reconciliation changed it to supported while preserving the previous finding. The live Plant A inspection now has **16 supported / 2 unresolved** claims. See [test results](output/certificate-flow/result.json) and [updated assessment](output/certificate-flow/assessment-after.txt). The earlier 15/3 export is retained as the original baseline.

The [frontend functional plan](docs/frontend-plan.md) maps six views to the tested API and defines the first clickable demonstration. No frontend code has been created yet.

## Source control and future updates

This project is maintained in a private GitHub repository. See [the changelog](CHANGELOG.md) for the build's actual scope and limitations, and [the contribution workflow](CONTRIBUTING.md) for the owner's instruction to commit and push future tested codebase changes. GitHub Actions checks tests, formatting and static analysis on each push. Credentials, runtime databases/storage and synced ChatGPT project references are excluded from source control.

## Frontend layout concepts

[Compare 20 generated layout mockups](docs/design-exploration/README.md): five density/style directions for each of the four proposed trial pages. These are concept images, not implemented frontend screens or approved scope changes. Prompts are included with the gallery.
