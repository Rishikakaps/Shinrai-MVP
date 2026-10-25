# Shinrai

### Capital deployment integrity, backed by evidence.

Shinrai helps analysts verify whether capital intended for machinery has reached its intended purpose: the right asset was purchased, paid for, physically present, installed and commissioned. It connects financial documents, machine labels, site observations and interviews to an auditable review of each machine.

Built as a working proof of concept for the **Japan Day hackathon**, Shinrai brings the inspection workflow into one browser application: capture a source, review what it says, connect it to a claim, and explain the conclusion with its evidence.

[Open the live demo](https://rinse-creature-critter.ngrok-free.dev/app) · [Try the motor registry](https://rinse-creature-critter.ngrok-free.dev/app?inspection=7777ba4d-8556-4c24-891a-ab99a93f8048&asset=MTR-031#/overview) · [Evidence Inbox](https://rinse-creature-critter.ngrok-free.dev/evidence-inbox)

## The problem

An invoice, a payment entry and a photograph answer different questions. An invoice can describe a purchase; a photograph can show a machine; neither, by itself, establishes that the intended machine has been installed and commissioned at the declared site.

For lenders, finance teams and field reviewers, the challenge is connecting these fragments across documents, machines and repeat visits. Missing identifiers, conflicting records and unresolved requests make it difficult to explain what has actually been verified and what still needs work.

Shinrai organizes that review around specific claims and their supporting sources. For example, an analyst can record that a machine is present and packaged while leaving installation and commissioning unresolved. When a certificate arrives later, the analyst can review it, link it and reconcile the findings while retaining the earlier conclusion.

## What Shinrai verifies

Each declared machine has six separate claims:

| Claim | Question the analyst must answer |
|---|---|
| **Identity** | Does accepted evidence match the declared serial, model and site? |
| **Purchase** | Do the reviewed purchasing records support this machine and transaction? |
| **Payment** | Do the reviewed payment and invoice records agree on the relevant references and amounts? |
| **Presence** | Has the machine been observed at the declared site? |
| **Installation** | Is there accepted evidence that the machine is installed? |
| **Commissioning** | Is there accepted commissioning evidence tied to this machine? |

The rules engine computes findings from accepted, relevant evidence. The analyst records a separate reviewed conclusion, including any explained override. Missing information remains visible; conflicting sources remain part of the review. Completing a review can leave unresolved claims and open follow-ups.

**A matching label is an identity candidate. Evidence acceptance, physical identity confirmation and claim support are separate decisions.**

## The product workflow

1. **Overview:** inspect the machine table, six claim statuses and source-file links.
2. **Registry:** edit machine declarations, manufacturer, model, serial and electrical ratings. Corrections preserve provenance and invalidate affected reviews.
3. **Evidence:** upload an original, review its extracted details, then link it as support, contradiction or context. Each step has its own screen.
4. **Site inspection:** move through separate Capture, Identity, Interview and Observations screens. Successful matching scans open evidence review; confirmed physical identity enables machine-linked recording.
5. **Assessment:** reconcile accepted sources, review findings and complete the review with its remaining gaps visible.
6. **Follow-ups and repeat visits:** track requests, due dates and evidence requirements while retaining machine history and earlier findings.

The **Evidence Inbox** provides a shared processing queue for documents, photos, short videos and audio. It shows processing status, source previews, extracted candidates and reviewed proposals to create or update registry records. File filters follow the selected machine; **Show all files** reveals the complete inspection. Scrolling stays within the current page.

### Beyond the initial inspection

- **Investment context:** record replacement, repair, upgrade, expansion and new-purchase proposals, with reported costs, targets and baselines. Forecasts and measured outcomes have separate reviews.
- **Interview assistance:** use configured Gemini services for transcription, Japanese-to-English translation, source-linked questions and contextual Q&A. Analysts review suggestions and confirm proposed changes.
- **Audio comparison:** compare descriptive signal features across recordings, with quality warnings and capture context. These comparisons do not diagnose equipment faults or establish commissioning.
- **Review and closure:** retain before/after audit events, source locators, earlier findings and explicit closure requirements. JSON, text and PDF exports carry the assessment and its provenance.

## Why it matters

Shinrai is designed for equipment-finance and capital-expenditure reviews involving lending teams, company finance teams, inspectors and auditors. It gives them a shared record of the machine, the evidence considered and the next action needed.

The intended business value is less manual evidence chasing, more consistent inspections and clearer handoffs between field and desk reviewers. Pilot evaluation should measure review time, repeat visits, request-resolution time and evidence traceability; no measured commercial ROI is claimed by this prototype.

A possible commercial model is an organization subscription with usage-based inspection capacity and integrations into existing lending or enterprise workflows. Pricing, paying customers and production-scale performance remain to be validated. Shinrai's current output supports analyst review; it does not make lending, funding or fraud decisions.

## The technology that works today

| Layer | Technology | Role in the current implementation |
|---|---|---|
| Browser application | HTML, CSS, vanilla JavaScript, Jinja2 | Guided pages, editable registry, source review, camera/microphone controls and analyst/judge views |
| Backend and contracts | Python 3.12+, FastAPI, Uvicorn, Pydantic | Authenticated APIs, validated records, workflow rules and generated OpenAPI contract |
| Database | SQLite; PostgreSQL through psycopg | Transactional records, sessions, versions and audit history; the current laptop demo uses SQLite |
| Hosted database option | Supabase PostgreSQL | Supported through the PostgreSQL adapter and private `DATABASE_URL`; separate from the active SQLite demo |
| Original evidence | SHA-256-addressed filesystem storage | Retains source bytes and checks integrity; database and file storage must both persist |
| Documents and images | pypdf, Poppler, Tesseract through pytesseract, Pillow | PDF text/rendering, OCR, image previews and reviewed crop/rotation/contrast adjustments |
| Machine identifiers | ZXing-C++ and exact identifier comparisons | QR/barcode decoding and conservative serial/model matching, with conflicts retained |
| Video | FFmpeg, ffprobe, Pillow | Validates short clips, extracts timestamped frames and shortlists frames using a sharpness heuristic |
| Classification and association | Explicit keyword/category rules and deterministic matching | Proposes evidence categories and machine candidates; no custom trained classifier is deployed |
| Speech and contextual AI | Optional Google Gemini API through httpx | Transcription, translation, interview analysis and case-context assistance when privately configured |
| Audio processing | FFmpeg and local signal calculations | Validates recordings and computes descriptive features such as signal level and selected frequency-band energy |
| Reports and reminders | ReportLab; persisted reminder outbox and Mailpit test inbox | PDF exports and controlled reminder testing; real recipient delivery is not enabled in the demo |
| Hosting and packaging | Laptop server, ngrok HTTPS; Docker/Compose configurations | Current demo runs natively on the laptop through an HTTPS tunnel; container packaging is available |
| Verification | pytest, Ruff, Node test runner, jsdom, Playwright/Edge; GitHub Actions | Backend checks, UI state tests, browser workflows and repository CI |

Dependency versions are pinned in [requirements.lock](requirements.lock) and [package-lock.json](package-lock.json). The application uses the same authenticated backend for the polished workspace and the field capture client.

### How video and photo intake actually work

The current video path is:

```text
Original MP4/MOV
  → FFmpeg/ffprobe validation
  → Up to 6 uniformly sampled, timestamped frames
  → Up to 3 distinct frames shortlisted by a sharpness heuristic
  → Tesseract OCR + ZXing QR/barcode decoding
  → Rule-based category and identifier candidates
  → Analyst review → accepted evidence → claim reconciliation
```

Video intake is bounded to **30 seconds**, with a configurable file limit of up to **100 MiB**. Sampling can miss brief events; the sharpness score is a heuristic rather than a calibrated image-quality model. The Inbox supports selecting and adjusting a derived source frame while preserving the original.

A still photograph goes directly through OCR/barcode decoding and candidate matching. A unique, exact observed serial can attach a **context-only** link to a registry row. A different intended machine, conflicting identifiers or an unclear reading requires review. Live camera preview is ephemeral; deliberate captures become saved evidence. Uploaded short videos use the sampled-frame pipeline above. Camera preview and file capture do not run a live object detector.

**There is no CNN layer in the current capture or video-processing pipeline.** There is also no deployed custom-trained visual classifier, machinery tracker or automated visual diagnosis. These are distinct from the working frame-extraction, OCR and review features.

### How speech and AI fit

Audio originals are preserved and processed as bounded clips. With a configured Gemini key and an available model, the backend can transcribe speech, translate Japanese source text and suggest contextual questions or structured proposals. Original text, translations, source quotes and analyst decisions remain distinguishable.

Provider failures are explicit, and any enabled rules fallback is labelled. The AI adapter cannot accept evidence, overwrite a machine declaration or turn a forecast into a supported outcome on its own. Speech capture is clip-based rather than continuous live speech streaming.

## Try the demo

| Entry point | Purpose |
|---|---|
| [Shinrai workspace](https://rinse-creature-critter.ngrok-free.dev/app) | Main guided application |
| [40-motor overview / MTR-031](https://rinse-creature-critter.ngrok-free.dev/app?inspection=7777ba4d-8556-4c24-891a-ab99a93f8048&asset=MTR-031#/overview) | Seeded registry and selected scan sample |
| [Evidence Inbox](https://rinse-creature-critter.ngrok-free.dev/evidence-inbox) | Upload, process and review media |
| [Field capture client](https://rinse-creature-critter.ngrok-free.dev/field-test) | Engineering camera/microphone capture and review client |

Sign in with the **analyst team access key**: the value of `CDI_ANALYST_TOKEN` from the host's private `.env`. Analyst access permits edits, uploads and review. `CDI_JUDGE_TOKEN` provides read-only judge access. The host shares these privately; credentials are excluded from the public README, Git and browser URLs.

The demo is served by the laptop on **port 8004** through ngrok HTTPS. Keep the laptop, backend and tunnel running. Android Chrome should use the HTTPS link for camera access; the tablet's `localhost` refers to the tablet. The host can use [http://127.0.0.1:8004/app](http://127.0.0.1:8004/app). This is a temporary demonstration endpoint, not an always-on production service.

### A quick scan walkthrough

1. Open the seeded overview and select **MTR-031 — General Electric**, model **121123**, serial **134678**.
2. Open **Open scan sample** on the laptop. On the tablet, open Site Inspection, select MTR-031 and capture the displayed label, or upload the unchanged sample image.
3. A readable matching scan attaches as context and opens its Evidence review screen. Check the original, review proposed fields and record any missing information before accepting evidence or registry changes.
4. Continue through the guided workflow. An empty identity selector explicitly explains that accepted evidence matching serial, model and site is required.
5. For a complete financial-document-to-finding demonstration, use the separate synthetic [Plant A walkthrough](docs/frontend-handoff.md#first-trial), including the missing-certificate resolution path.

The seeded motor registry contains **40 machines and 240 claims**, with **37 source photos** uniquely matched against publisher metadata. Three records remain metadata-only; fourteen have no published serial. The public dataset's labels are machine-generated and **unverified**. MTR tags and the plant association are synthetic. These images establish no ownership, site, purchase, payment, installation or commissioning; imported originals start unaccepted. See [dataset provenance and the resumable import](fixtures/motor-nameplates/README.md).

## Trust, persistence and verification

- **Originals remain unchanged:** extracted text, proposed fields and adjusted frames are separate from the source bytes.
- **Review stays explicit:** source acceptance, machine association, physical identity, claim relationships and reconciled findings have separate steps.
- **Changes stay traceable:** version checks reject stale edits; corrections, reviewed conclusions and earlier findings retain audit history. Duplicate upload handling reuses processing where applicable while retaining upload history.
- **Access is controlled:** analyst/judge roles, browser sessions, CSRF protection, protected originals and server-side provider credentials are implemented.
- **Failures remain visible:** unreadable sources, uncertain identifiers, processing failures and provider errors require retry, correction or clarification rather than invented facts.

Recorded verification on this build includes **178 backend tests passed / 17 skipped**, **23 frontend DOM tests passed**, Ruff and JavaScript syntax checks. The skipped external-service checks were not verified in that local run. A later targeted run of the real video-frame/OCR test passed, and the guided-page changes passed 12 backend browser-UI tests.

Real Edge browser checks covered the 40-machine table, machine-scoped files, sample scanning, save-to-next-screen transitions, the empty identity state and retention of unsaved edits when navigation is cancelled. The public HTTPS API was also checked. These results are functional checks, not an independent industrial OCR-accuracy benchmark, a large-video stress test or physical Android camera/microphone acceptance.

## Run locally

Use **Python 3.12+**. Native media processing also needs **Tesseract**, **Poppler**, **FFmpeg** and **ffprobe** on `PATH` or in the supported local tool directories.

Create a virtual environment:

```sh
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m scripts.configure
.\.venv\Scripts\python.exe -m scripts.serve
```

macOS/Linux:

```sh
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m scripts.configure
.venv/bin/python -m scripts.serve
```

Open **http://127.0.0.1:8000/app** for a fresh local installation. `scripts.configure` generates private analyst/judge keys once and preserves an existing `.env`. Set `PORT=8004` to match the current demonstration port. A fresh clone does not include the host's runtime registry, source photos or credentials; **Prepare fresh Plant A trial** creates a separate synthetic starting case.

Optional private settings include `GEMINI_API_KEY` and an available `GEMINI_MODEL`, `DATABASE_URL` for PostgreSQL/Supabase, and `NGROK_AUTHTOKEN` for tunnelling. The running server can use `CDI_ENV_FILE` and an absolute `CDI_DATA_DIR` to retain existing configuration and data across checkouts. Restart or reload the appropriate provider configuration after changes. Back up both the database and original-file directory.

Docker/Compose setup, PostgreSQL persistence and controlled deployment are documented in the [deployment guide](docs/backend-deployment.md) and [V2 setup guide](docs/v2-backend.md). Container configurations are provided; the current laptop demo uses native startup.

### Developer checks

```sh
python -m pytest -q
python -m ruff check app scripts tests
python -m ruff format --check app scripts tests
npm ci --ignore-scripts
npm run test:ui
```

The Python commands assume the project environment is activated. Some integration checks require PostgreSQL and the test mail inbox. See [CONTRIBUTING.md](CONTRIBUTING.md) for the repository workflow.

## Documentation

- [OpenAPI contract](docs/openapi.json) and [API workflow](docs/api.md)
- [Field capture, device contracts and tablet setup](docs/v2-field-bench.md)
- [Integrated registry, intake and source-frame implementation](docs/multimodal-continuation.md)
- [Investment projects, repeat visits, reports and closure rules](docs/v2-backend.md)
- [Synthetic Plant A walkthrough](docs/frontend-handoff.md)
- [Motor dataset provenance and import](fixtures/motor-nameplates/README.md)
- [Model implementation status](models/README.md)

Some linked implementation documents preserve earlier checkpoint notes; the capabilities and limits described above reflect the current integrated build.

## Future scope

- **CNN-based visual intake layer:** explore detection of machinery/nameplate regions, image-quality assessment and better frame selection before OCR. This layer is **not implemented**. It needs licensed, reviewed data and evaluation across manufacturers, sites, lighting and devices before accuracy or reliability claims.
- **Stronger field validation:** complete physical Android testing and independent industrial OCR evaluation; investigate perspective correction, tracking and on-device inference.
- **Production and integrations:** validate multi-team deployment, scalable storage and enterprise workflow integrations; pilot the business model and measure review efficiency and traceability.
