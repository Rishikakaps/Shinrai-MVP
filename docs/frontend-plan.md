# Frontend V1 proposal — built around the tested backend

Historical functional plan. The connected four-screen implementation now combines these views, following the user’s later softened D design instructions. See [the implemented frontend and first trial](frontend-handoff.md). The six-view table below records the original capability grouping, not six required pages.

## Verified demonstration to make visible

CNC-002 commissioning went from unresolved to supported through actual HTTP operations: upload a synthetic certificate PDF, extract its text, link it to the commissioning claim, verify it remains unresolved before acceptance, analyst-confirm the extract, rerun reconciliation, review current findings, and resolve the certificate request. The earlier unresolved finding and audit events remain intact. Current Plant A has 16 supported and 2 unresolved claims; CNC-003 installation/commissioning still need evidence.

## Shared application shell

Select an inspection, identify the active analyst/judge role, show saving/loading/error state and last refresh time. Analyst controls permit changes; judge mode presents read-only evidence and results. Use controlled session credentials; do not bake shared analyst keys into a public bundle. Read APIs already exist. No new reconciliation rules belong in the browser.

## Six views

| View | User action and content | Existing backend |
|---|---|---|
| Inspection overview/setup | Choose/create inspection; see asset list, claim counts, review state and outstanding requests; add/correct machine declarations | Inspection and asset routes, complete export |
| Evidence review | Upload document/image; view authenticated original beside extracted fields; correct identifiers/amounts; confirm/reject; record quality flags; link to individual claims | Evidence import/extract/correction/original, claim confirmation, evidence links |
| Inspection mission | Pick a machine; read checklist; upload saved photo; record observed presence, condition and installation; distinguish management statement from analyst observation | Mission, media/evidence and observation routes |
| Reconciliation and review | Three machine rows × six claim columns; click a cell for evidence, explanation and next action; reconcile; review/override with reason | Reconcile, findings review, complete review, export |
| Follow-ups | List open/resolved requests, associate them with a machine/claim, create requests and record responses/resolutions | Follow-up routes |
| Assessment/report | Show computed and reviewed conclusions, scope, outstanding gaps, contextual statements and original evidence; download text/JSON | Report/export/original routes |

Audit history can be a reusable drawer opened from evidence, claims and findings; it does not need a seventh full screen. Asset setup can be a form within the inspection view.

## Critical interaction rules

- Upload → extract → analyst confirm → link → reconcile → review. Clearly show the current stage.
- Claim confirmation means the declared assertion was checked; evidence acceptance and evidentiary support are separate.
- Display five backend finding states: supported, partly supported, unresolved, potentially inconsistent, not assessed. Use clarification language; do not label potential inconsistencies as fraud.
- Show computed and analyst-reviewed conclusions separately, including override reason.
- Mark stale findings as needing reconciliation; never keep presenting an earlier assessment as current after evidence changes.
- Label review completion separately from claim support; unresolved findings may coexist with complete review.
- Do not mark a claim supported when a follow-up is closed. Show support only from backend reconciliation.
- Show extraction errors, quality issues and manual correction paths explicitly. OCR does not determine machine condition.
- Financial statements are reference context, not proof of payment/purchase or underwriting inputs.
- Preserve and expose earlier evidence edits and finding snapshots.

## Build order

1. First clickable end-to-end slice: open Plant A → select CNC-002 → inspect an unresolved commissioning finding → upload/review a certificate → confirm/link → reconcile → view supported result and previous finding. Use a fresh prepared inspection for repeat demonstrations because the live CNC-002 has now been resolved.
2. Complete inspection setup, declaration confirmation, machine mission, observations, follow-ups and full report.
3. Add read-only judge presentation, audit drawer, responsive capture layout, loading/error/stale-update handling, and final demo polish.
4. Deploy the frontend and API to one controlled persistent host with HTTPS/team access. Validate from the other laptops. Add camera/webcam simulation after the core browser workflow is reliable.

## How the frontend connects

Use a small API client generated or typed from `docs/openapi.json`. Fetch the current inspection report for the overview/matrix. Each UI action calls the existing specific endpoint, then refreshes the relevant state. Keep returned version numbers on edits; a 409 means reload and ask the analyst to reconcile the newer state. Fetch original files with authentication into a temporary browser object URL for preview; do not put tokens in URLs. Keep calculations and support decisions entirely on the backend.

The backend uses a global inspection evidence fingerprint, so adding evidence makes all prior current findings/reviews stale. The UI should offer a clear re-review flow for unchanged conclusions after recomputation rather than hiding this requirement.

## Frontend acceptance checks

- A new inspection can finish the complete flow without terminal commands.
- Upload alone never marks commissioning supported.
- Correcting evidence makes previous findings stale; reconciliation and review restore current status.
- The certificate flow changes only the intended claim and preserves previous history.
- Packaged CNC-003 displays clarification requests rather than an accusation.
- Refresh/restart preserves work; judge credentials cannot write even if a control is manually invoked.
- Reports and summaries match backend computed/reviewed fields exactly.

Product-PDF comparison remains pending because the source PDF is unavailable. Visual structure and styling can be adjusted without changing these backend interaction rules.
