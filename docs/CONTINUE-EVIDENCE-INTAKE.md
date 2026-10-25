# Capital Deployment Integrity — continuation prompt after the 6:10 AM IST checkpoint

Paste this file into the next chat, or ask that chat to read it in full. This is a
continuation of implementation, not a request to redesign the product.

## The owner's instructions

Continue implementing the Intelligent Evidence Intake subsystem in the existing
application. The owner supplied a full implementation/training specification dated
25 October 2026, asked us to conserve tokens and reuse existing code, then required
an immediate PR using their account. They subsequently said to work only until
**6:10 AM IST on 25 October 2026**, save what was built in a PR, and create a large
handoff prompt explaining what was being done, what was interrupted and the plan.
That deadline ends THIS execution; a new chat must continue explicitly from this
checkpoint. Do not silently keep working in the old chat after the cutoff.

Read `docs/evidence-intake-implementation-spec.md` for the complete original brief.
It is a verbatim copy of the user's attachment, not a newly inferred specification.
The original attachment also remains at:
`C:/Users/adity/.codex/attachments/71824a77-8f2b-4980-ae67-3f7b9d1321a4/Pasted text.txt`.

## Exact repository and branch

- Upstream: https://github.com/Rishikakaps/japan-day-capital-deployment-integrity
- Authenticated GitHub account used: **pixeleskadi**.
- User fork: https://github.com/pixeleskadi/japan-day-capital-deployment-integrity
- Current feature branch: **codex/intelligent-evidence-intake**.
- Draft PR: https://github.com/Rishikakaps/japan-day-capital-deployment-integrity/pull/4
- PR base: **codex/v2-backend**, not main.
- Initial intake checkpoint commit: `05ef1ece4a7e33f650401948e01c48b616027dee`.
  More work was done afterward; the commit containing THIS handoff is the later
  checkpoint. Resolve `git rev-parse HEAD` and verify the PR head before continuing.
- Intake was branched from field build `c5b210b`, whose PR is:
  https://github.com/Rishikakaps/japan-day-capital-deployment-integrity/pull/3
  At intake PR creation, #3 was still unmerged. PR #4 therefore includes that
  dependency until #3 is merged into the V2 base. Inspect its current status.
- Older V2 source baseline was `13b5c79`; PR #1 contains separate V1 fixes and
  was already merged into main. Do not replace V2 with main or blindly merge it.

Actual implementation checkout:
`C:/Users/adity/Documents/Codex/2026-10-24/https-github-com-rishikakaps-japan-day/work/evidence-intake`

The chat's default root directory is its parent project folder and is NOT itself a
Git repository. Use the actual checkout explicitly on commands. Git on this host
may require a command-local `-c safe.directory=<absolute checkout>`. Do not set a
global wildcard or discard other worktrees.

Read CONTRIBUTING.md. The owner requires tested code updates to be committed and
pushed. Preserve unrelated work, never force-push, and keep private/runtime files
out of commits. Use the existing draft PR rather than opening duplicates. Attach
any newly created PR with the app's attach_artifact tool.

## Preserve the live tablet deployment

The feature checkout has **NOT** replaced the running application. It is tested in
isolation. Do not describe `/evidence-inbox` as already deployed publicly.

The existing running server is the older field checkout:
`.../work/v2-field`, on **127.0.0.1:8004**, with persistent SQLite data in that
checkout's `data/`. The existing V1 server on port 8000 is separate; do not stop it.

The user's ngrok tunnel currently points to port 8004:
https://rinse-creature-critter.ngrok-free.dev

Relevant existing paths:

- `.../work/v2-field/.env`: private analyst/judge credentials, Gemini settings and
  ngrok settings. The user saved these themselves. Never print/copy secrets into
  chat, source, screenshots, PR bodies, URLs or handoff documents.
- `.../work/v2-field/.run/field-server.pid`: launcher process tracking.
- `.../work/v2-field/.run/tablet-tunnel.pid`: tunnel launcher tracking.
- `.../work/v2-field/.run/tablet-endpoint.json`: verified public route metadata.
- `.../work/v2-field/.tools`: local Tesseract, FFmpeg, Mailpit and ngrok binaries.
- `.../work/v2-field/.run`: private live-provider diagnostics and field tests.

The ngrok v3 launch bug was already fixed in `scripts/tunnel.py`: use explicit
config_version 3, upstream/bindings and optional HTTPS url; do not restore legacy
bind_tls/schemes. Public readiness, login, Secure/HttpOnly cookies and CSRF writes
were tested through that endpoint. The target physical device is Android Chrome.
Actual tablet camera/mic acceptance is not proved by desktop synthetic media.

If deploying this checkout later, take a recoverable DB+media backup, coordinate a
brief restart, reuse the old private environment without exposing its values, and
set an ABSOLUTE `CDI_DATA_DIR` pointing at the intended existing data. Merely loading
the old `.env` while changing cwd would resolve its relative `data` to a new empty
directory. Persisted sessions may survive a correct shared-data restart, but camera
transport receipts are ephemeral. Keep ngrok on 8004; do not expose Mailpit or DB
ports. The new EvidenceKind.other is additive for this code, but old code may not
read records of that kind: review rollback compatibility before writing live data.

## What has actually been implemented

New backend modules:

- `app/intake_models.py`: strict upload/review models and IntakeRecord. Stores
  original provenance, source/capture context, processing status/attempts, raw
  extraction, apparent classification, candidates, assignment and reviewer metadata.
- `app/intake_service.py`: shared durable originals using existing persist_original,
  a persisted single-host queue, background worker, interrupted lease recovery,
  duplicate-byte cache reuse, existing Evidence integration and acoustic handoff.
  Historical Evidence is indexed at startup without changing accepted facts or the
  V1 reconciliation basis. Legacy manual uploads are indexed without auto-processing.
- `app/intake_perception.py`: bounded subprocess worker using existing PDF extraction,
  Tesseract/ZXing and FFmpeg. Video samples six uniform positions and OCRs at most
  three distinct frames shortlisted by a heuristic edge/focus score. It preserves
  original video and source timestamps; it does not OCR every frame.
- `app/intake_understanding.py`: apparent-category keyword rules, source-linked
  key/value extraction, separate code observations, conservative identifier checks,
  explicit partial/multiple/conflicting/model-only/unassigned outcomes. It never
  establishes identity from a model alone and never auto-associates evidence.
- `app/intake_routes.py`: authenticated upload, inbox/search/status/extraction,
  source/frame retrieval, retry, analyst asset association, separate document/fact
  acceptance, asset evidence lookup and existing acoustic-module handoff.

Integration changes:

- `app/main.py`: lifespan starts/stops intake worker; existing manual uploads register
  in the index; intake has a larger bounded video body allowance with two concurrent
  upload slots; other routes retain their old limits. Existing six-claim engine is
  unchanged.
- `app/models.py`: adds neutral EvidenceKind.other. No existing enum members removed.
- `app/web.py`, `app/templates/app.html`: authenticated `/evidence-inbox`, allowlisted
  login return path, and a navigation link. Existing `/app` surfaces are preserved.
- `app/templates/intake.html`, `app/static/intake.js`, `app/static/intake.css`: upload,
  state/search cards, source previews, text spans, candidate/conflict display,
  association review, fact/category acceptance, explicit existing claim-link calls,
  links back to reconciliation/follow-ups, video frames and audio handoff controls.

Association is NOT evidence acceptance. Acceptance is NOT computed claim support.
The Inbox creates claim links only after a separate explicit user submission; the
old reconciliation endpoint remains authoritative. Original files are never renamed
or altered. Display filenames are metadata. Corrected facts live in existing
Evidence; raw extracted observations remain in IntakeRecord/audit history.

Audio intake does not become a V1 Evidence object and is analyst-only. Handoff uses
the existing AudioRecording and requires a current accepted physical binding. New
videos are not made team-readable Evidence until a real video stream is validated;
an audio-only or malformed MP4 cannot bypass audio privacy just through its MIME.

## Routes and local behavior

New routes under `/api`:

- POST `/evidence/intake`: multipart `file` + JSON `metadata`, Idempotency-Key.
- GET `/evidence/inbox?inspection_id=...&q=...&state=...&asset_id=...`.
- GET `/evidence/{intake_id}/processing-status`, `/extraction`, `/asset-candidates`.
- GET `/evidence/{intake_id}/original` and `/frames/{number}`.
- POST `/evidence/{intake_id}/retry`, `/confirm-asset`, `/review-document`.
- POST `/evidence/{intake_id}/attach-acoustic?physical_asset_id=...`.
- GET `/assets/{local_asset_id}/evidence`.

The ID in these new evidence paths is an INTAKE record ID; evidence_id separately
refers to the existing V1 Evidence. Do not mix those with physical asset IDs.

Browser mutations use the existing opaque cookie + X-CSRF-Token + same-origin
checks. API clients use existing bearer credentials. Judges cannot mutate. There is
one configured deployment/team authorization model, not a completed multitenant SaaS
principal-to-tenant scheme. Case/visit/asset references are checked within that model.

Limits: documents/images/audio 12 MiB; videos default 100 MiB (can reduce with
CDI_INTAKE_VIDEO_MB), 30 seconds; existing PDFs max 12 pages/20 MP images. One queue
worker per app; parent media subprocess timeout 120 seconds; interrupted processing
leases become eligible after 150 seconds. CDI_INTAKE_WORKER=false disables the
background thread for controlled tests. No external AI document calls are made by
this intake MVP. No SQL migration was needed for additive typed-object records.

## Test evidence at the checkpoint

- Before modification: **154 passed / 16 PostgreSQL service skips**.
- First focused intake suite: **12 passed**.
- Latest full local suite: **168 passed / 16 skipped**, 160.92 seconds; one existing
  Starlette/httpx deprecation warning. Log `.run/intake-final-regression.txt`.
- The corrected acoustic handoff test passed individually. An earlier full run
  failed only because that new test read the physical creation response incorrectly;
  it must use response['physical_asset'], not response['id']. Do not mistake the old
  `.run/intake-regression.txt` failure for the latest result.
- The real browser harness was extended with the Inbox. It passed after fixing a
  race: review controls were previously displayed while processing was still queued,
  allowing a stale version. Controls are now hidden until processing finishes.
- Latest browser log: `.run/intake-browser-final.txt`; it passed sustained synthetic
  camera, recording/FFmpeg, provider failure recovery, manual Japanese correction,
  mobile layout, Inbox upload/queue/PDF extraction/association/acceptance/claim-link.
- Existing DOM suite: **15 passed**, `.run/intake-dom-final.txt`.
- Ruff lint/format and JavaScript syntax passed before checkpoint packaging.
- Browser screenshots and example report: `.run/browser-proof/`, including
  `evidence-inbox-reviewed.png`. These are local test artifacts, not physical tablet
  proof. Inspect/retain them as needed; they are ignored.

New tests are in `tests/test_intake.py`. They exercise real pypdf/Tesseract/ZXing/
FFmpeg, duplicate retries/cache, corrupt inputs, conflicts, source retrieval and
restart, review-to-reconciliation, acoustic handoff privacy and stale-job recovery.
Dedicated intake PostgreSQL wrappers and more adversarial cases were NOT yet added.
Existing PostgreSQL regressions remain in CI. Check the exact PR head's checks;
do not reuse older field PR CI success as proof of new intake changes.

## Dataset/evaluation work, and its limits

- `scripts/intake_demo.py` generates **14 fictional linked fixtures** for the exact
  requested CNC-001/DEMO-VF200/DEMO-SN-001, CNC-002/DEMO-VF500/DEMO-SN-002 and
  CNC-003/DEMO-VF500/DEMO-SN-003 identities. Includes certificates, specification,
  invoice, report, same-model/partial/multiple/unknown/contradictory cases, wrong
  filename, exact duplicate and QR nameplates. Files are clearly synthetic_demo.
- `scripts/evaluate_intake.py` runs the actual local rules/OCR pipeline against
  these fixtures. Measured: 14/14 category decisions, macro-F1 1.0, exact serial
  9/9 where ground truth exists, zero automatic associations. This is deliberately
  conservative HUMAN-review behavior, not evidence of production accuracy.
- `datasets/evaluation/synthetic-rules.json` records the actual results.
- `datasets/annotations/synthetic-manifest.jsonl`, `datasets/splits/test.txt` and
  READMEs preserve provenance, unknowns, grouping and test-only status. These are
  authored regression fixtures, not an unbiased independently curated benchmark.
- SmartDoc sampleDataset.tar.gz was downloaded from Zenodo. Size 21,203,716 bytes;
  verified MD5 1ee5b7c290d707bd51c59f0b1c1a36f5; SHA-256
  90d1a64f476ffe290ebbddf4337e108d471b9c25420551223f447db972844a9a.
- `datasheet001.avi` was preserved, with an 8-second H.264 MP4 derivative. Perception
  decoded/selected 3 frames and extracted 107 text characters. Manual frame inspection
  showed a small, angled electronics datasheet; text was only partially readable.
  No industrial asset ID accuracy was scored. `datasets/evaluation/smartdoc.json`
  records the limits and CC BY 4.0 attribution.
- Raw public media is ignored under `datasets/raw/`. Other named sources were
  inspected only; see `datasets/sources.md`. Do not download DocLayNet's full corpus.
- No TF-IDF/logistic/SVM classifier was trained. Runtime classification is rules.
  `models/README.md` explicitly says this. No calibrated probability is claimed.
- Actual staged smartphone captures of the three requested paper/label scenarios
  are still missing; synthetic FFmpeg video tests and public SmartDoc are separate.

## What was interrupted / what to do next

The owner stopped feature implementation at the deadline, not because the full
specification was complete. Continue with a careful acceptance/hardening pass:

1. Verify the latest commit/PR/head and read the original specification. Inspect
   `.run` logs before repeating tests; do not burn tokens rereading every file.
2. Review association versioning: IntakeRecord.version is checked, but candidate
   Asset.version snapshots are not yet carried through confirm-asset. A registry
   edit between processing and association should force re-review. Add a real
   regression for this before calling asset resolution hardened.
3. Finish scope/integrity/race checks: cross-case references, stale Evidence review,
   tampered original/derived frame, rejected/rescan behavior, upload backpressure,
   video duration/codec failures and processing/retry during concurrent review.
4. Dedicated intake PostgreSQL acceptance wrappers should reuse the SQLite flows
   against an ISOLATED test DB. Never point destructive tests at live Supabase.
5. Existing manual Evidence uploads and historical documents are indexed, but field
   camera and direct existing audio uploads do not yet register immediately through
   a shared hook. Add lightweight indexing hooks without duplicating OCR or changing
   acceptance/version ordering. Existing field/audio workflows must keep working.
6. Review the new UI's pending-upload retry and dirty-state behavior. It has a basic
   dirty guard, but needs adversarial navigation/edit tests. Do not redesign /app.
7. Regenerate docs/openapi.json from the new app with isolated temp storage. The
   checked-in snapshot may still reflect the preceding field build; this was not
   regenerated before the cutoff. Update route examples and frontend handoff docs.
8. Package printable demo fixtures and implement/review a convenient separate demo
   case seed using the existing APIs; do not replace the user's current test case.
   Check generated annotation manufacturer strings against visible text before
   using them for future field-level scoring (current measured metrics cover serial).
9. Publish a reproducible SmartDoc fetch command/script from the currently local
   `.run/fetch_smartdoc.py`, preserving bounds/checksums/attribution. Raw media should
   stay ignored. Complete a real upload-path test of the public clip if useful;
   the current public-video result is an offline perception test.
10. Trained lightweight classifier, optional authorized-folder watcher, document
   boundary detection/perspective correction, richer table extraction, issuer
   authenticity checks and production object storage are NOT completed. The first
   two are optional/follow-on; prioritize a defensible working MVP over fake metrics.
11. Only after review/checks: deploy a checkpoint to the laptop server safely and
   verify the unchanged ngrok origin, Inbox login/upload/poll/review/source retrieval
   and restart against preserved storage. The owner currently uses the old live
   field build; do not falsely claim intake is public already.
12. Update the same PR and final handoff/status matrix. Keep the PR draft until
   outstanding acceptance gaps are resolved or clearly agreed as deferred.

Gemini configuration is a separate unfinished issue from the preceding chat: a
private key/model were loaded, model metadata and one minimal real generation
succeeded, but full translation/audio requests timed out or failed. Originals were
retained. Do not claim full live Gemini validation, silently switch paid models, or
repeatedly charge requests while debugging intake (which currently runs locally).

## Reproducible local commands on this machine

Use the already-installed Python environment:
`.../work/backend/.venv/Scripts/python.exe`.

In the intake checkout, prepend sibling paths
`../v2-field/.tools/ffmpeg` and `../v2-field/.tools/tesseract` to PATH. Then:

```text
../backend/.venv/Scripts/python.exe -m pytest -q
../backend/.venv/Scripts/python.exe -m ruff check app scripts tests
../backend/.venv/Scripts/python.exe -m ruff format --check app scripts tests
../backend/.venv/Scripts/python.exe -m scripts.intake_demo
../backend/.venv/Scripts/python.exe -m scripts.evaluate_intake
```

For existing real local Mailpit tests, CDI_TEST_SMTP_PORT=11025; the test inbox is
127.0.0.1:18025. Keep it private. For PostgreSQL, set CDI_TEST_DATABASE_URL only to
an isolated disposable test database. Existing local run had no such DB configured.

Browser harness: node scripts/verify_field_browser.cjs. Set
CDI_BROWSER_TEST_PYTHON to the venv Python above, CDI_BROWSER_EXECUTABLE to
`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`, and NODE_PATH to
`C:/Users/adity/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules`.
For DOM tests, also include the sibling v2-field/node_modules path, or install the
locked frontend dev dependencies. The harness uses isolated storage, synthetic
media and no real Gemini key. It starts/stops its own server; do not kill port 8004.

Git authentication works with the owner's saved Git credential. Use standard Git
push with command-local safe.directory and, if needed, http.sslBackend=openssl /
credential.interactive=never. Git identity can be set command-locally from the
verified pixeleskadi public GitHub identity; do not change global account settings.
Do not print credential-helper output. PR creation used the authenticated GitHub
API; the connector's write permissions had previously been insufficient.

Keep communication short during work, and put detailed evidence in artifacts. The
owner explicitly asked for token conservation. Continue with targeted reads,
meaningful tests and the existing architecture; do not restart the whole project.
