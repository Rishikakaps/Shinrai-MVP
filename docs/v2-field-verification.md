# Current Windows field build — 25 October 2026

Baseline: V2 `13b5c79`, not main. Existing V1 PR #1 is merged; its separate branch
was inspected, not merged as an implementation shortcut. Tests use synthetic data
and isolated storage. No real company evidence or private configuration is committed.

| Area | Code / local evidence | Live / hardware status |
|---|---|---|
| Field sessions and sustained transport | Real HTTP, capped payloads, sequence retries/backpressure, reconnect/close, ephemeral preview, persisted capture | Physical tablet pending |
| OCR/QR/barcode | Real Tesseract and ZXing fixtures; separate raw sources; partial/conflict/mismatch/URL handling | Real plate lighting/camera pending |
| Identity | Explicit original review, acceptance, binding, stale versions, duplicate retry, original digest after restart | Physical identity accuracy requires analyst review |
| Interview | Real browser MediaRecorder and FFmpeg, protected source playback, company-level context, explicit authorization | Actual tablet mic and live Gemini pending |
| Gemini adapter | Mocked REST/schema/failure tests; missing-provider browser recovery; executable live harness | LIVE PROVIDER VALIDATION PENDING |
| Transcript/proposals | Human Japanese transcript/correction; provider originals immutable; dependency invalidation and review | Language/provider accuracy not inferred from mocks |
| Acoustic memory | Existing real FFmpeg/signal comparison integration; binding required; purpose separation | Real machine, load and repeat recording pending |
| Documentary quantity | 400-unit accepted-document route, verification plan/locator, stale source detection, no fake identities | Actual documentary quality requires analyst review |
| Repeat visits, investments, tasks | Existing regression tests retained; project interview/follow-up can omit physical asset | Actual field revisit pending |
| SQLite/restart | Original bytes/digest, persisted session/capture/binding, history and existing migration tests | Local real database, synthetic evidence |
| PostgreSQL | Existing adapter preserved; three additional field flows included in service tests | Isolated local Postgres not configured; CI provisions it |
| Mailpit | Loopback SMTP outbox integration exercised separately; no production email | Local test inbox only |
| Reports | Real JSON/text/PDF; rendered PDF visually checked, Japanese readable; original URLs protected | Browser fixture sources are synthetic |
| Access | Analyst/judge, protected audio, case scope, cookie/CSRF/origin regression, idempotency/version tests | HTTPS tablet trial pending |
| Existing frontend | Existing 15 DOM tests; `/app` preserved | Polished frontend integration belongs to its developer |

The initial pre-setup run failed six audio checks because FFmpeg was missing.
Installing verified FFmpeg/ffprobe fixed that dependency. A subsequent full run
passed 139 tests with 14 service skips; further hardening adds cases afterward.
The browser harness caught mobile horizontal overflow; the fix passed the rerun.
Final verification:

- Full Python run: **144 passed, 16 skipped**, 161.77 seconds. All skips require
  isolated PostgreSQL; the actual local Mailpit SMTP test passed. One existing
  Starlette/httpx deprecation warning remains.
- After adding two further acceptance cases, the complete field module passed
  **14 tests** in 21.32 seconds, including actual Code128 plus OCR and an unbound
  project follow-up. Twelve of those cases also ran in the full suite; these
  counts overlap and should not be added together.
- Existing frontend: **15 passed**. The separate real-browser field harness passed
  against its isolated real backend, actual OCR/ZXing/FFmpeg and explicitly
  synthetic camera/microphone. It includes recovery after closing the audio
  session, preserved speaker metadata, provider failure, manual Japanese text,
  correction, labeled rules fallback, PDF and mobile-width checks.
- Ruff lint/format, JavaScript syntax and Git whitespace checks passed. Current
  OpenAPI was regenerated. Rendered Japanese PDF was visually inspected.
- The separate running laptop server on port **8004** returned readiness 200 and
  authenticated capabilities confirming SQLite, OCR, decoder and audio tools.
  Its Gemini configuration is blank. The existing server on port 8000 was retained.

Gemini was explicitly deferred by the user. The physical target is **Android
tablet / Chrome**; its acceptance checklist is in the runbook. The current local
server uses SQLite; this new checkout is not connected to the user's Supabase.

The initial local record above did not verify a live provider response, physical
tablet, external HTTPS route, Docker execution or post-push CI. Subsequent checks
are recorded separately below and in the PR checks.

## Subsequent tablet HTTPS check — 25 October

The user's ngrok credentials were saved privately. An initial launch exposed a
real compatibility failure: pyngrok 9.0.3 translated legacy `bind_tls` into a
`schemes` property rejected by ngrok 3.39.13's v3 endpoint API. The launcher now
uses explicit v3 `upstream`/`bindings`/optional HTTPS `url` configuration.
Eight focused launcher contract/failure tests passed. Live public readiness,
authentication, Secure/HttpOnly cookies, field-page retrieval and a CSRF-protected
same-origin write all passed through the HTTPS endpoint. Its QR code was decoded
and checked against the exact URL. The actual Android tablet camera/microphone
test remains pending; the endpoint stays available only while its agent and laptop
backend are running. No credential or runtime configuration is committed.

The user's Gemini key was also loaded privately. Model metadata and a basic real
generation request succeeded, but full translation/audio verification encountered
timeouts/provider errors. A synthetic English audio original remained retrievable
with its SHA-256 intact after failure. End-to-end live Gemini and real Japanese
speech validation remain pending.
