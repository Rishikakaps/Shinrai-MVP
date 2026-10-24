# V2 connected frontend trial

The same FastAPI process serves `/app` and the authenticated API. There is no separate frontend build or browser-side Google key. The seven surfaces are Overview, Evidence, Site inspection, Assessment, Investments, Follow-ups and Wearable preview. Existing V1 evidence acceptance and reconciliation remain authoritative.

## Start and configure

Follow `docs/v2-backend.md` for Windows installation or `compose.demo.yaml` for the bundled tools and local test inbox. Open `/app` rather than `/backend-test` for the V2 frontend. Run `python -m scripts.configure` only for a new configuration; preserve existing credentials and data. Store `GEMINI_API_KEY=your_private_value` in the repository-root `.env`, save the file and restart the backend. Do not put it in a JavaScript file or share it in chat. In Docker, recreate the backend after configuration changes.

`GEMINI_MODEL` selects a Google model available to the project. Provider access, regional eligibility and quotas depend on that Google project. A configured key alone does not prove a successful call. Errors are shown and originals remain saved. The app must never present rules fallback or a mocked response as a live Google response. Wispr Flow is not required: the application captures short audio clips and sends them to its server-side Gemini adapter for transcription and English rendering.

## Android Chrome trial

1. Start the backend and expose its port through an HTTPS tunnel such as ngrok. Keep the laptop awake. On the phone, open that HTTPS URL in Chrome and sign in with the private analyst access token from `.env`. Use synthetic material for this trial.
2. Prepare a fresh Plant A trial if needed. Enrol it in a company/site case, select a machine and explicitly confirm its identity from an accepted matching source. A decoded barcode alone never confirms identity.
3. Open Evidence or Site inspection and download the clearly marked synthetic camera label. Show it on a separate screen or print it. Permit the phone camera, capture the clear label, then try a deliberately blurred or cropped version and an unrelated serial. Check the rescan/mismatch warning, retained original and absence of automatic acceptance. File capture remains available when live camera access is unavailable.
4. Open Site inspection. Confirm recording consent and synthetic trial status, select the correct machine and speaker, then allow microphone access. Speak a short Japanese sentence, stop and wait for saved clips to process. Review the original recording, Japanese source, English rendering and suggested questions. Correct a saved sentence with a reason and inspect Activity for both values. Disconnect the network once and retry; verify originals and unsaved-clip recovery before navigating away.
5. Ask the case chatbot a question about saved evidence. Check source IDs and missing-evidence language. A question must not change findings. If Google rejects the request, the UI must show the error and retain the question.
6. Create a replacement, purchase, repair, upgrade or expansion proposal. Add a forecast target with an unknown baseline; it must remain a forecast. Record measurements and explicitly review a current target version with source evidence. Edit the target and verify the old outcome review no longer appears current.
7. Create a follow-up with an owner, reviewer, date and required evidence. Attempt premature closure, then supply and review the required evidence before closure. Check saved edits and state changes in Activity.
8. Add another visit and explicitly associate the machine with accepted identity evidence. Compare history and recordings. Acoustic differences are descriptive; they do not diagnose failure or establish an investment outcome.
9. Export the assessment PDF and inspect Japanese text, source links, unresolved findings, forecasts and measured outcomes. Sign in as a judge to check read-only access and audio-sharing restrictions.

Wearable mode is a browser presentation preview. It does not connect to or certify compatibility with smart glasses. It shows the active machine, scan status, one suggested question and recent transcript lines; edits return to the source controls.

## Verification and remaining acceptance gates

On 25 October 2026, the full Python suite passed **143 tests**, including SQLite, actual local PostgreSQL and Mailpit, barcode decoding and mocked Gemini contract/error responses. The frontend DOM suite passed **15 tests**. The connected HTTP/DOM harness passed **15 checks**, executing the actual scripts against a running backend, including real form submissions and audited corrections. These are not physical browser or camera tests.

Reproduce: `pytest -q` with the local integration service variables documented in the backend guide; `npm ci --ignore-scripts && npm run test:ui`; and `CDI_ANALYST_TOKEN=... node scripts/verify_v2_ui.cjs` against localhost (default port 8003). Supply credentials privately. The latter creates synthetic trial records, so use a separate trial data directory.

Primary edge cases exercised include: missing consent; denied/absent media API; unconfirmed identity; unreadable/blurred/mismatched label; corrupt original; decoder timeout; duplicate retry; edited retry payload; stale versions; same recording compared to itself; unknown baseline; stale target review; premature task closure; cross-case source access; forged judge writes; CSRF/origin checks; provider timeout/quota/malformed or invented source responses; preserved unsaved inputs; HTML escaping; transcript audit history; and Japanese PDF font embedding.

Still required for release acceptance: actual browser visual/interaction review, Android Chrome camera/microphone and network-interruption trial, live Google chatbot/transcription/translation, Windows startup, and completed Docker build/run verification. Local browser use was disabled in Work settings at the last attempt, and the private `.env` read with empty Google key fields. No numerical claim of 90% total edge coverage is justified while these acceptance gates are pending. Automated test counts are not a coverage percentage.

The full rerun fixed shared-client idempotency headers, missing authenticated actor attribution, foreign-machine scope handling, stale target outcome presentation and reader-dependent Japanese PDF fonts. One Starlette test-client deprecation warning remains.
