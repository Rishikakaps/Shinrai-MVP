# Changelog

## 0.2.0 — connected FastAPI app and uploaded backend integration

- Implement the softened D browser workflow: Overview, Evidence, Site inspection and Assessment; collapsed navigation/details, bottom records trays, scrollable tables and sequential sections.
- Connect original upload/preview, extraction/OCR, analyst correction/acceptance, explicit claim links, observations, reconciliation, review, follow-ups, immutable history and report/JSON download. Add non-destructive fresh Plant A trials and matching synthetic certificates.
- Add opaque persistent browser sessions, CSRF/origin protection and read-only judge UI while retaining bearer API clients. Render PDF pages for browsers without a native PDF viewer.
- Integrate the owner’s ZIP: Postgres/Supabase adapter, migration, Windows-friendly runners, readiness/meta, forced OCR, safer backups and deployment regression tests. Fix browser sessions for both database adapters.
- Add real Postgres tests and document deployment limits. Verify the certificate journey in the actual browser: 16 supported / 2 unresolved, 18 reviewed, earlier unresolved history retained, request resolved, report/JSON downloaded.
- No real Supabase/ngrok deployment or camera/vision integration was performed. The ZIP supplied no diagram files; existing design documentation is preserved.

## Unreleased — layout exploration

- Add labelled Theme A versions of all four screens and a backend-checked field-source/edit-permission guide; original concepts retained.

- Add 20 generated frontend mockups: five styles for each of four trial pages, from minimal notebook to dense operations console.
- Include page-by-page galleries, the element checklist, and generation prompts. These are design concepts; no frontend implementation or backend behavior changed.

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
