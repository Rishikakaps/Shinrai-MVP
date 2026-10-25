# V2 backend checkpoint

Current field build and validation are documented in [v2-field-bench.md](v2-field-bench.md)
and [v2-field-verification.md](v2-field-verification.md). Earlier validation records below are historical.

This is a hackathon build for one team, synthetic records, a Windows laptop backend and phone browser capture through an authenticated HTTPS tunnel. Production multi-company access and an external submission portal are outside this release. Analysts upload and review evidence. This checkpoint was pushed before verification was complete at the user's request.

## Fixed mechanisms

- A case represents one company/site and contains multiple inspection visits. A physical machine has a stable identity across visits. Accepted identity evidence and explicit analyst confirmation are required before machine capture; serial suggestions do not bind machines automatically.
- Replacement, new purchase, repair, upgrade and expansion are investment projects. Downtime, repair costs, output, defects and energy targets remain forecasts until a separately reviewed measurement supports an outcome. Missing baselines remain missing.
- Follow-ups reuse the existing task record with V2 context, due date, contact, purpose, assigned reviewer and evidence requirements. Claim-bound closure requires the underlying current finding to be computed and reviewed as supported, with relevant accepted evidence. Project-only requests require evidence review for their stated purpose. Editing requirements resets review. Saved changes preserve before/after audit records.
- Original audio is content-addressed and persistent. Uploads are limited to 12 MiB and two minutes, decoded with FFmpeg, checked against the confirmed asset and protected by analyst/judge access rules. Acoustic comparisons describe signal differences and capture limitations; they do not diagnose faults.
- Gemini handles actual transcription, Japanese-to-English translation and bounded interview analysis when a private key is configured. Suggestions are proposals with exact source quotes, editable previews and explicit confirmation. No model output establishes a financial or deployment finding. Provider failures are explicit; optional rules fallback is labelled.
- Incremental capture submits complete short recordings in sequence. It is chunk-based, not a continuous speech stream. Pending segments are retained for retry/download if processing fails. Actual phone/browser recording still needs a hardware test.
- Reminders use a persisted outbox, stable message identifiers, bounded retry and a local Mailpit inbox. This build does not send real email. JSON, text and PDF case exports include provenance and forecasts separately from verified findings.
- V1 typed records and reconciliation fingerprints are preserved. V2 typed records use the same transactional store, supplemented by relational indexes and constraints for case membership, bindings and idempotency. SQLite is the free single-host demo default; Postgres is also supported and tested. Originals and database must both survive restarts.

## Start on Windows with Docker Desktop

Install Python 3.12+ and Docker Desktop with Linux containers enabled. From the checkout in PowerShell:

```powershell
git switch codex/v2-backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m scripts.configure
```

Open the generated private `.env`, retain its generated analyst/judge credentials, and add `GEMINI_API_KEY=...` and `GEMINI_MODEL=gemini-3.8-flash`. Do not commit the file or send keys in chat.

```powershell
docker compose -f compose.demo.yaml up -d --build
```

Open `http://127.0.0.1:8002/backend-test` and sign in with `CDI_ANALYST_TOKEN` from `.env`. The local test inbox is `http://127.0.0.1:18025`. The container includes FFmpeg, Tesseract and Poppler. Native startup additionally requires those tools on PATH.

Prepare the separate synthetic two-visit story through real API calls:

```powershell
.\.venv\Scripts\python.exe -m scripts.v2_demo --url http://127.0.0.1:8002
```

Check `python -m scripts.v2_demo --help` if using a different port. The seed retains prior cases; `--fresh` creates another case. Audio fixtures are generated tones, not actual machine recordings. Without a Gemini key the demo explicitly reports rules fallback.

For semi-remote phone access, run ngrok against port 8002 after configuring its account token privately. Use the resulting HTTPS origin on the phone and sign in normally. Camera/microphone permission and browser codec support must be tested on the actual phone. Keep Mailpit on loopback and share only the intended synthetic recordings with judges. Stop the tunnel when the demo ends.

Stop containers with `docker compose -f compose.demo.yaml down`; named data volumes remain. Do not use `down -v` to stop a demo you intend to retain. Keep `.env` separately protected. Back up the database together with the entire originals directory.

## API contract

### Google AI Studio configuration

The active provider is now Google Gemini; Groq and Whisper credentials are not required. Add `GEMINI_API_KEY` to the private repository-root `.env`; `GOOGLE_API_KEY` is also accepted. Optional `GEMINI_MODEL` defaults to `gemini-3.8-flash`. This model is configurable if the Google project has different model access. The application never automatically falls back to another paid model.

Restart the backend after changing configuration. An authenticated analyst can alternatively call `POST /api/v1/providers/reload` with a reason. Docker users must recreate the backend container after changing its environment: `docker compose -f compose.demo.yaml up -d --force-recreate backend`. No dependency installation changes are needed: the adapter uses the existing HTTP client.

Questions/extraction, Japanese text translation, and short-clip speech transcription/translation all use Google's server-side API. Transcription preserves spoken corrections; the saved original remains available for analyst review. Audio remains chunk-based, not continuous streaming. Quota, permission, blocked-output and invalid-schema failures are explicit and retain saved sources. Previously saved provider attribution remains historical and is not rewritten.

Provider documentation: [audio understanding](https://ai.google.dev/gemini-api/docs/generate-content/audio), [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output), [pricing and free-tier availability](https://ai.google.dev/gemini-api/docs/pricing).

Authenticated `/openapi.json` is generated from the current typed request/response models and includes V2. The checked-in `docs/openapi.json` has been regenerated for the current V2 field build. V2 endpoints are under `/api/v1`:

| Resource | Paths |
|---|---|
| Availability | `/capabilities`, `/providers/reload` |
| Cases and visits | `/cases`, `/cases/{id}/inspections` |
| Machine identity | `/physical-assets`, `/asset-bindings`, `/identity-suggestions` under a case |
| Investment planning | `/investments`, `/targets` and investment reviews under a case |
| Requests | `/follow-ups`, task `/transition`, `/reminders/run`, `/reminders` under a case |
| Capture and interview | `/audio`, `/audio-comparisons`, `/interviews`, `/segments` under a case |
| Analysis | `/analyses`, `/candidates`, candidate `/confirm` under a case |
| Reports and history | case `/export`, `/report`, `/report.pdf`, `/activity`; inspection `/v2-context` |

Use returned UUIDs, expected versions, reasons and `Idempotency-Key` where required by the contract. Judges cannot write; restricted audio and transcript derivatives are filtered from their exports.

## Verification at the checkpoint

The initial WIP push is commit `028ec90`. Before it, V2 database integration runs passed against actual local Postgres and SQLite, with actual local SMTP delivery. A subsequent complete run reported 118 passes and one test assertion failure: Mailpit's `total` field counts the entire inbox. The assertion was corrected to use the filtered count and exact Message-ID; its targeted rerun is recorded separately after completion.

Python lint/format checks and JavaScript syntax checks passed. The HTTP two-visit seed saved original audio, produced a comparison, rejected unsupported closure, closed an evidence-supported installation request, delivered to the test inbox and preserved the first visit's findings. AI fallback was labelled because no key was configured.

Still pending at this checkpoint: live Gemini calls, browser recording/permission recovery, physical Windows/phone tests, visual PDF inspection, and completion of container build/run verification. Provider adapter tests with mocked responses do not substitute for live provider verification. The four-screen frontend adjustments follow the backend acceptance checks.

## Gemini migration verification

The complete post-migration suite passed: **131 tests**, including actual local Postgres, SQLite and Mailpit SMTP integration plus 12 mocked Gemini REST contract/error-handling tests. Python lint/format checks and JavaScript syntax checks passed. One existing Starlette deprecation warning remains. A real Google API call was not performed: the original private `.env` could not be read because local cloud-file access failed. No private key was copied into this verification checkout or committed. The running server must be restarted with readable configuration before live AI verification.
