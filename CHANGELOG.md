# Changelog

## 0.1.0 — 24 October 2026

Initial backend-first Japan Day hackathon build for Capital Deployment Integrity Working Model V1.

### Implemented

- Typed FastAPI/Pydantic inspection, asset, atomic claim, evidence/link, finding, review-event and follow-up APIs.
- Persistent SQLite storage, original evidence files, SHA-256 verification and audited revisions.
- Real PDF text extraction and local image/scanned-PDF OCR with explicit manual correction and analyst acceptance.
- Deterministic claim-level identity, purchase, payment, presence, installation and commissioning rules.
- Mission checklists, observations, contextual statements, next actions and reporting/export.
- Separate computed/reviewed conclusions, stale-review invalidation and immutable audit events.
- Controlled analyst/judge access, bounded uploads, explicit CORS and persistent deployment configuration.
- Three-machine synthetic Plant A seed, backup/restore utility, automated tests and actual HTTP/restart verification.
- A subsequent live synthetic CNC-002 certificate exercise: unresolved before acceptance, supported after acceptance/reconciliation, history preserved. Live example: 16 supported / 2 unresolved claims.
- GitHub automated checks and the owner's ongoing commit/push workflow.

### Validation

52 automated tests passed locally, with static checks and formatting checks passing. Native Uvicorn startup and process restart preserved original files and audit history. The saved certificate-flow results record the subsequent live acceptance exercise.

### Known limitations

No frontend, phone/webcam capture simulation, AI image-condition inference, underwriting or remote shared deployment. Arbitrary document/table layouts require analyst correction. Docker execution was not verified because the local daemon was unavailable. The source product PDF was not mounted, and the referenced chat's assistant specification was exposed only as opaque content references; exact PDF/specification compliance remains unchecked.
