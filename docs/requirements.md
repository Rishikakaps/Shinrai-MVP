# Working Model V1 — implementation baseline

## Source availability

- Authoritative available baseline: the user's detailed backend-first implementation request on 24 October 2026, including explicit financial/vision/access choices.
- Referenced chat `6adc3738-2d04-83ee-8377-3564d5bcd673` was read. It contains the selection of focused core with contextual insights, financial verification A, vision API A, controlled deployment A, team/time constraints, and backend-first instruction. Its assistant answers are only opaque content references; their frozen specification cannot be recovered from the read tool.
- The uploaded six-page `/mnt/data/japanday hackathon .pdf` is not mounted in this workspace; the project's `sources/` directory is empty. No claims of PDF compliance are made. Once it is available, compare it to this baseline and record any required changes before expanding V1.
- The initial backend baseline did not assume a frontend. The user subsequently specified four guided screens, a softer D theme, collapsible panels, scrollable tables and sequential entry. These are implemented in the connected browser app. No model switch was performed.

## Minimal architecture and rationale

FastAPI with strict Pydantic request/response models exposes an OpenAPI contract. A transactional SQLite object store holds typed domain entities; JSON payloads keep the hackathon schema small while services validate every scoped reference. SQLite indexes inspection/type, supports concurrent readers, serializes writes, and records optimistic versions. There is no external DB/service setup. SHA-256 addressed files hold original documents, images and observation payloads. Every mutation appends server-authored before/after audit records in the same transaction. Local pypdf, Poppler and Tesseract provide extraction without any model API.

This is intended for a small team on one persistent host, using a single service worker. It favors a complete, explainable demonstration over ingestion generality or scale. Docker packaging is optional; native startup is verified.

## Requirement coverage

| Requirement | Implementation |
|---|---|
| Inspection, Asset, atomic Claim | Typed entities; six claims per machine, audited corrections |
| Original evidence and provenance | Content-addressed files, source/capture/receipt times, digest/size/MIME, quality/confidence and accepted state |
| Real PDF text and image/scanned OCR | Isolated workers; manual correction and before/after events |
| Supports/contradicts/context links | Scoped references, required locator, audited retraction |
| Deterministic claim reconciliation | All active accepted evidence; exact IDs; financial reference/amount/currency rules |
| Computed vs reviewed assessment | Separate fields and review reason/actor/time; immutable event history |
| Historical revisions | Full before/after events plus past finding snapshots |
| Mission/checklist and media | Per-asset checklist, image upload, extraction result and analyst correction endpoints |
| Contextual explanations | Observations and management/financial context, included in reports |
| Follow-up requests | Open/resolved/reopened actions, resolution and audit events |
| Persistent reports/export | Typed full JSON, text assessment, original retrieval |
| Controlled access | Strong random bearer tokens, analyst/judge roles, private listener, explicit CORS |
| Restart persistence | SQLite + files on shared persistent directory/volume; tested process restart |
| Prepared Plant A | Three synthetic machines, expected 15 supported / 3 unresolved atomic claims |
| Failure cases | 52 automated tests at initial delivery, including blurry/duplicate IDs, conflicting payments and missing certificates |

## States

Inspection: `draft → active → review_complete`. An asset/evidence/claim/link change returns it to `active`. Every declaration must be confirmed and every current finding reviewed before review completion. Unresolved conclusions and open requests do not prevent review completion.

Evidence: uploaded/unconfirmed → extracted/unconfirmed → analyst corrected/accepted. Re-extraction revokes acceptance. Analyst can revoke acceptance or retain explicit quality flags. Original bytes are never replaced by corrected text. Failed extraction retains evidence and requires manual work.

Finding: not computed → deterministic result (`supported`, `partly_supported`, `unresolved`, `potentially_inconsistent`, `not_assessed`) → reviewed result with author/time/reason. Any basis change requires a new reconciliation and review. Prior computed snapshots and review events remain available. Overrides never replace the computed conclusion.

Follow-up: `open ↔ resolved`. Neither state proves a claim. Resolution does not remove missing-document findings.

## Deferred items

The connected frontend follows the user’s subsequent structure and visual instructions; see `frontend-handoff.md`. Phone/webcam smart-glasses simulation and optional AI condition inference are deliberately deferred. Financial statements remain contextual reference; no underwriting. Product-PDF comparison remains pending source availability. Remote deployment requires a user-controlled destination; none was supplied.

## Connected V1 scope update

The backend ZIP and browser UI are integrated, with SQLite native operation and an optional Postgres adapter. See [deployment](backend-deployment.md) and [frontend behavior](frontend-handoff.md). V1 includes saved-photo inspection, document review, claim reconciliation, follow-ups, audit and report export. Live camera/glasses capture, optional model inference, generic ingestion automation and shared hosted deployment remain later work; no V2 feature commitment is implied.
