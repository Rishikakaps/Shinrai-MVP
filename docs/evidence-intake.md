# Intelligent evidence intake — implementation checkpoint

Branch: `codex/intelligent-evidence-intake`, based on the field build `c5b210b`.
This is an incremental draft, not a completed training/deployment claim.

Implemented: durable queued intake, immutable originals and SHA-256, PDF/text/OCR
reuse, separate QR/barcode fields, apparent document classification, deterministic
asset candidates, explicit conflict overrides, separate document acceptance,
existing claim-link/reconciliation integration, duplicate-byte reuse with separate
upload history, protected previews, bounded MP4/MOV sampling and an Evidence Inbox
at `/evidence-inbox`. Legacy upload routes remain available and are indexed without
automatically changing their manual workflow. Audio intake can be handed to the
existing audio module after a current physical binding is confirmed.

Start normally with `python -m scripts.serve`. The single-host persisted queue runs
with the app; `CDI_INTAKE_WORKER=false` disables it for controlled tests. Upload via
`POST /api/evidence/intake` with multipart `file`, JSON `metadata`, authentication
and `Idempotency-Key`. Metadata requires case context, timezone-aware capture time
and a reason. The inbox links into the existing workspace; association does not
accept evidence, and acceptance does not itself compute claim support.

Documents/images/audio retain the existing 12 MiB limit. Video defaults to 100 MiB,
configurable downward with `CDI_INTAKE_VIDEO_MB`, and 30 seconds. Six uniformly
sampled frames are shortlisted to at most three distinct frames using an explicitly
heuristic focus score. Source pages, character spans and video timestamps are
retained; bounding boxes are not fabricated where unavailable. Original files are
never renamed destructively. Local media and the existing SQLite/Postgres typed
store are reused; no new SQL migration is required for these additive entities.

Checks at this checkpoint: baseline **154 passed / 16 PostgreSQL skips**; the new
intake module **12 passed**, including real OCR/QR, real FFmpeg sampling, duplicate
retry, conflict handling, original retrieval after restart and the full human
review-to-existing-reconciliation path. Ruff and JavaScript syntax checks pass.
The full regression after these changes, browser Inbox acceptance, final OpenAPI,
broader security/failure checks, dataset evaluation and documentation remain in
progress. Downloaded research data stays ignored. No trained classifier, measured
industrial accuracy, physical phone capture or complete live-provider workflow is
claimed by this draft. The running tablet deployment has not been replaced.
