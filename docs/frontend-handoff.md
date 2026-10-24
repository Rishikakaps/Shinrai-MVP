# Connected frontend V1

Implementation: FastAPI routes in `app/web.py`, Jinja templates in `app/templates/`, and local JavaScript/CSS in `app/static/`. The backend remains the source of every claim result. The same process serves both app and API; no external assets or frontend toolchain are required.

## Four screens

| Screen | Working operations |
|---|---|
| Overview | Inspection selector, separate fresh Plant A trials, three-machine/six-claim matrix, declared machine additions/corrections, declaration confirmation |
| Evidence | Original upload and integrity-checked preview/download, PDF text/OCR and forced PDF OCR, manual correction, quality flags, explicit acceptance or clarification, supports/contradicts/context linking and audited retraction |
| Site inspection | Machine selection, saved-photo upload, analyst or management observations, human-assessed condition, presence/installation including unknown, capture time and explicit claim links |
| Assessment | Reconciliation, separate computed/reviewed results, reasoned overrides, explicit re-review of unchanged conclusions, review completion, text/JSON download |

The shared bottom tray opens Activity, Requests or History one at a time. Follow-ups can be created, resolved and reopened. Both sidebars collapse; claim tables scroll horizontally with sticky machine identifiers and bounded vertical height. The warm paper/sage design follows the user's softened D direction. Required sections open in order, while saved sections remain revisitable. Unknown/not assessed and clarification remain valid outcomes.

## Data sources and editing

PDF text and OCR suggest identifiers, model/site, references and amounts only where the deterministic parser recognizes them. All such fields remain editable working extracts until an analyst confirms them. Analyst observations supply physical condition, presence and installation; OCR does not judge condition. Management statements and financial statements remain contextual.

Original bytes, source/capture/receipt metadata, SHA-256, computed results and server audit authors/times are read-only. Analysts can correct working extracts and declarations, confirm claims/evidence, manage links and requests, record observations and reviewed results. Changes require reasons and version numbers. Judges can read originals, findings, history and reports; backend authorization rejects writes even if a UI control is manipulated.

## Browser authentication

The login accepts the existing analyst/judge access key once. It exchanges that key for an opaque HttpOnly SameSite=Strict session cookie. Only a hash of the session identifier and credential digest are stored server-side. The key is never written into HTML, JavaScript or browser local storage. Cookie writes require a CSRF token and reject a mismatched Origin. Bearer clients remain compatible without browser CSRF. HTTPS deployments must use secure cookies and correct proxy forwarding.

## First trial

1. Sign in and choose **Fresh trial** (or **Prepare fresh Plant A trial** on an empty installation). It creates separate synthetic data and preserves all existing inspections.
2. Select CNC-002 / Commissioning, then open Evidence.
3. Download that machine's synthetic certificate and upload it as a commissioning certificate. Supply source, capture time and reason; save the original.
4. Run **Extract text / OCR**. Compare the rendered original with serial `SYN-002`, model `DemoMill X3`, site `Plant A` and commissioned `Yes`. Upload/extraction is still unaccepted.
5. To demonstrate the safeguard, reconcile now and open Details: commissioning remains unresolved.
6. Check that you compared the fields to the original, enter a reason and **Save and confirm**. Link it to the commissioning claim as **supports**, with page and reason.
7. Open Assessment and reconcile. CNC-002 commissioning becomes supported. Save the analyst review, resolve its follow-up with a response, and explicitly re-review the 17 unchanged conclusions.
8. Complete the review, inspect History, then download report/JSON. There should be 16 supported and 2 unresolved claims. CNC-003 remains unresolved for installation and commissioning; its requests stay open.

The end-to-end browser trial artifacts are in `output/ui-trial/`. The JSON/report were downloaded through the actual UI; screenshots show saved states. API tests independently verify the unaccepted evidence safeguard and retained history. No browser automation library is required to run the app.

## Remaining limits

Prepared Plant A is the V1 entry path. Generic inspection creation is available through the typed API, not a dedicated UI setup wizard. Photo upload is implemented; live camera/webcam/smart-glasses streaming is deferred. Extraction of arbitrary tables, handwriting and multiple machine rows still needs manual mapping. There is no vision API inference, multi-tenant user administration or autonomous underwriting. The original six-page product PDF is still unavailable for a final source comparison. Shared HTTPS access must be verified on the chosen host.
