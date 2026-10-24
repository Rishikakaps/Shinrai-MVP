# V2 field engineering client

Implementation branch: `codex/v2-field-bench`, based on V2 `13b5c79`.
The separate V1 PR #1 was merged into main during inspection. This change targets
`codex/v2-backend` and preserves its seven-screen `/app` frontend.

## Run on the laptop

Requires Python 3.12+, Tesseract with English data, FFmpeg/ffprobe, and the pinned
Python dependencies. Docker is optional. SQLite is the single-laptop default;
Supabase/Postgres remains supported through `DATABASE_URL`. Keep originals and the
database together when backing up. A hosted database alone does not back up local media.

From this checkout in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m scripts.configure
# On subsequent starts, reuse .env; do not regenerate credentials unnecessarily.
$env:PORT='8004'
.venv\Scripts\python.exe -m scripts.serve
```

Open `http://127.0.0.1:8004/field-test`. Sign in with the analyst token from the
private `.env`. The existing `/app`, `/backend-test`, `/docs`, `/openapi.json`,
`/health`, `/ready` and `/api/v1/capabilities` remain available. Capability flags
mean installed/configured, not proven on a physical device or with a live provider.
The runner also recognizes ignored Windows `.tools/tesseract` and `.tools/ffmpeg`.

Do not replace an existing server or point integration tests at a live Supabase
database. For a separate server, choose an unused port and its own checkout/data.
New field entities reuse the existing typed JSON store, case indexes, audit and
transactions; no destructive schema migration or parallel database is introduced.

Private settings: `DATABASE_URL`, `CDI_DATA_DIR`, generated `CDI_TOKENS` and session
configuration, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `GEMINI_MODEL`,
`CDI_CORS_ORIGINS`, `PORT`, optional `NGROK_AUTHTOKEN`/`NGROK_URL`.
For reminders: `CDI_ENABLE_REMINDERS`, `CDI_EMAIL_MODE=test`, `CDI_SMTP_HOST=127.0.0.1`,
`CDI_SMTP_PORT=11025`, `CDI_REMINDER_RECIPIENT`. No production email is required.

## Field workflow

1. Choose an existing case, visit and optional task/project. The prepare button
   creates a separate, labeled synthetic trial without clearing existing records.
2. Start an identifier session. An intended machine is optional and is never a
   confirmed identity. Start the camera, grant permission, and inspect connection
   receipts. A deliberate still leaves the same camera session running.
3. The server saves original image bytes and a capture record before scanning.
   Review the protected original, individual processor sources and comparison.
   Choose rescan, reject, correction or acceptance with a reason. Acceptance
   requires explicit original review and matching analyst-entered serial/model/site.
   Conflicting sources require a separate acknowledgement. No candidate auto-binds.
4. Close that session and start an interview or machine-acoustic session. Speech
   can belong to company/project context without a fabricated physical asset.
   Acoustic recording always requires a current, accepted physical identity binding.
5. Confirm authorization and speaker attribution before interview recording. Save
   and play the original, then request Gemini transcription/translation. If the
   provider fails, the saved source remains playable and retryable. The manual
   transcript route is explicitly human-authored; it does not claim Gemini ran.
6. Correct the working transcript, retaining original provider text separately.
   Review questions and editable proposals individually. Source corrections stale
   pending proposals and flag accepted statement dependencies for review.
7. Use existing projects, targets, measurements and follow-ups. The documentary
   form records the proposition, verification strategy, source versions, quantity
   and locator. Reviewing 400 units on paper does not create 400 physical identities.
8. Inspect saved records and activity; download JSON, text or Japanese-capable PDF.
   A machine acoustic comparison describes signal differences, never fault diagnosis.

## API and device contract

All domain routes are under `/api/v1`; see regenerated `docs/openapi.json` for full
typed bodies. Cookie clients send `X-CSRF-Token` on mutations; API clients use
`Authorization: Bearer ...`. Never put credentials in a media URL. Judges cannot
mutate. Non-synthetic audio and its dependent transcripts are analyst-only.
Mutations require a reason, optimistic `version` where applicable, and an
`Idempotency-Key` on create/review operations. Reuse the same key only with the
same payload. A changed payload is a 409, not a second source.

| Method and case-relative path | Purpose |
|---|---|
| POST/GET `/cases/{case}/field-sessions` | Create/list persisted device context |
| GET/PATCH `/cases/{case}/field-sessions/{session}` | Status, reconnect, interrupt, close |
| POST `/cases/{case}/field-sessions/{session}/preview?sequence=N` | Ephemeral bounded image sample |
| POST `/cases/{case}/field-sessions/{session}/captures` | Multipart `file` and JSON `metadata` containing `captured_at`, `reason` |
| GET `/cases/{case}/visual-captures` | Original-linked raw processing and review records |
| POST `/cases/{case}/visual-captures/{capture}/process` | Retry saved original processing with version/reason |
| PATCH `/cases/{case}/visual-captures/{capture}/review` | Correct/rescan/reject/explicitly accept |
| POST/GET `/cases/{case}/documentary-reviews` | Analyst documentary review; derived `source_current` on read |
| POST/GET `/cases/{case}/audio` | Existing protected recording pipeline; optional `field_session_id` |
| POST `/cases/{case}/audio/{recording}/transcribe` | Existing saved-source Gemini workflow |
| POST `/cases/{case}/interviews` and `/interviews/{interview}/segments` | Attributed speech and manual fallback |
| PATCH `/cases/{case}/segments/{segment}` | Versioned corrections; preserve provider output |
| POST `/cases/{case}/segments/{segment}/analyse` | Questions/proposals; labeled rules-only fallback if explicitly allowed |
| POST `/cases/{case}/candidates/{candidate}/confirm` | Human acceptance/rejection with source confirmation |
| POST `/cases/{case}/audio-comparisons` | Same confirmed machine, context-aware signal comparison |
| GET `/cases/{case}/export`, `/report`, `/report.pdf`, `/activity` | Source-linked outputs and analyst audit |

Existing investment and enhanced follow-up/reminder routes are unchanged. Use
`/api/v1/cases/{case}/follow-ups` and transition routes documented in OpenAPI.
The engineering client does not replace every project administration screen in `/app`.

### Sustained preview protocol

Authenticated HTTP sampling avoids another media server on the laptop. The client
sends approximately one JPEG per second, long edge <=640, with one awaited request
and no backlog. The server streams at most 256 KiB, verifies JPEG/PNG and at most
307,200 pixels, and returns sequence, receipt time and count. Inter-arrival below
250 ms returns 429 with `Retry-After`. Latest identical retry is acknowledged;
changed/out-of-order sequence returns 409. Resume from server `last_sequence+1`.

No preview bytes are saved, OCRed or added to the V1 evidence basis. The ephemeral
receipt map is capped at 1,024 sessions, with expired receipts reclaimed. More than
eight seconds without a receipt shows `INTERRUPTED`; restart loses transport state
but keeps sessions, deliberate originals, reviews and bindings. Reconnect uses the
same context/version. Explicit close stops tracks; a closed session cannot capture.
Sample/capture timestamps retain device and server receipt times separately.

Separate still uploads use the existing 12 MiB file validator, protected originals,
SHA-256, version checks and transaction receipts. OCR subprocesses are limited to
two concurrent jobs with bounded time/pixels. Audio also uses two bounded processing
slots, 12 MiB/120 seconds and real FFmpeg validation of WAV, WebM/Opus or MP4/M4A AAC.

### Identifier interpretation

OCR text/fields, QR and barcode payloads remain separately identifiable. JSON code
payloads use known field names; an arbitrary URL is retained, not interpreted as a
serial. Multiple different applicable values force `CONFLICTING_SOURCES`, even
when one equals the expected value. `?`, `*` and replacement characters remain
partial. Conservative comparison folds case and whitespace only; punctuation,
leading zeros and O/0 remain distinct. Manufacturer/model/serial/site compare
independently. Image quality flags are heuristics, not calibrated blur/glare scores.
Raw processor results never change when the working correction changes.

## Verification commands

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check app scripts tests
.venv\Scripts\python.exe -m ruff format --check app scripts tests
npm ci --ignore-scripts
npm run test:ui
# Optional isolated browser tools; no runtime dependency on Playwright.
npm install --prefix .run/browser-tools --no-package-lock --ignore-scripts playwright@1.62.1
.run/browser-tools/node_modules/.bin/playwright.cmd install chromium
$env:NODE_PATH=(Resolve-Path .run/browser-tools/node_modules).Path
$env:CDI_BROWSER_TEST_PYTHON=(Resolve-Path .venv/Scripts/python.exe).Path
node scripts/verify_field_browser.cjs
```

Put real Tesseract/FFmpeg on PATH before running checks. Optional
`CDI_BROWSER_EXECUTABLE` selects an installed Edge/Chrome executable. The browser
harness creates isolated SQLite storage and synthetic camera/microphone streams,
exercises actual HTTP/backend/OCR/ZXing/FFmpeg, saves screenshots/PDF under `.run`,
and stops its own server. It does not read private `.env` or call Gemini.

For external service tests, set `CDI_TEST_DATABASE_URL` to an **isolated test**
Postgres database. Set `CDI_TEST_SMTP_PORT=11025` and optionally
`CDI_TEST_MAILPIT_URL=http://127.0.0.1:18025` for a loopback Mailpit instance.
CI provisions Postgres 16 and Mailpit 1.32.0, runs both adapters and the browser
harness. CI results must be checked separately after pushing.

### Live Google check — LIVE PROVIDER VALIDATION PENDING

Save an available `GEMINI_MODEL` and private `GEMINI_API_KEY` in `.env`, then run:

```powershell
.venv\Scripts\python.exe -m scripts.verify_field_provider --audio C:\private\authorized-japanese-speech.wav
```

This performs real translation, source-validated structured proposals and speech
transcription/translation. It retains a byte-identical audio copy and a private
JSON result under `.run/live-provider`. It prints no key/transcript. Without
`--audio`, speech remains pending. Read the report and manually check negation,
tentative replacement and amounts; structural validation alone does not establish
language accuracy. It makes paid/provider calls only when you run it. It never
accepts a proposal or alters case evidence. Test the same clip through `/field-test`
to verify the configured running server; missing/quota/blocked/unavailable model
errors must leave its original source intact. Do not switch models silently.

### Android tablet / Chrome — HARDWARE VALIDATION PENDING

Set ngrok privately and run `PORT=8004` (PowerShell `$env:PORT='8004'`) with
`python -m scripts.tunnel`. The launcher uses the v3 endpoint schema: a loopback
`upstream`, public binding and optional HTTPS `url`. It deliberately avoids legacy
`bind_tls`/`schemes` settings, which fail against the current endpoint API.
Expose only the authenticated application; keep Mailpit and database ports private.
Tablet camera/microphone need a secure HTTPS origin; a laptop localhost exception
does not make plain tablet-to-laptop HTTP secure.

On the actual Android tablet in Chrome: sign in, select a real test visit/task, grant rear-camera and
microphone permission, collect >=10 preview receipts, capture two separate stills
without restarting the camera, review each source/conflict, explicitly bind, then
record an authorized interview and a separate bound-machine acoustic clip. Exercise
disconnect/reconnect, exact upload retry, source correction, follow-up and exports.
Stop/restart the laptop backend without deleting data; retrieve and compare source
digests, bindings, transcript corrections and audit. Repeat visits must reuse the
confirmed physical identity; replacements must have separate identity records.
Record tablet model/browser, origin, codecs, environment and observed outcomes.

On 25 October, the laptop's live ngrok endpoint passed public readiness, protected
login, Secure/HttpOnly session-cookie, authenticated field-page and same-origin
CSRF-protected write checks. A QR code was generated and decoded back to the exact
field-page URL. This verifies the HTTPS route; the physical Android camera and
microphone remain pending. Keep the laptop/backend/tunnel running while using it.

## Recovery and limits

- Camera denied: inspect HTTPS, OS/browser permissions, camera availability and
  `getUserMedia` support before transport/OCR. Upload an existing image as a fallback.
- Interrupted network: stop backlog, reconnect from server sequence. Unsaved media
  stays in this page's memory with exact retry and download; a reload warning is
  provided. There is no durable encrypted offline browser queue; download first.
- OCR missing/unreadable: the original remains saved; retry processing, rescan, or
  use explicit manual correction after examining the original. Never fill from the
  expected record simply to force a match.
- Provider failure: inspect configuration/availability/quota, then retry saved
  source. Manual transcript and rules fallback are explicitly labeled.
- 409: refresh current version/context and review changes; do not blindly overwrite.
- Every response includes a sanitized `X-Request-ID`; logs contain route/status/time,
  not media bodies, tokens or transcript contents. Use it to correlate failures.
- Acoustic output is signal memory conditioned on device/load/distance and recording
  processing. It cannot establish machine health or independent commissioning.
- This is a single-worker laptop POC with bounded synchronous image/audio processing,
  not a high-volume distributed media service or glasses SDK.

See [current verification record](v2-field-verification.md) for exact evidence and
remaining service/device checks. Earlier results in other V2 docs are historical.
