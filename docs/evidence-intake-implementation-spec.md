# Capital Deployment Integrity — Intelligent Evidence Intake AI

**Implementation and Training Specification | Version 2.0 | 25 October 2026**

**Project:** Capital Deployment Integrity / Evidence Copilot  
**Existing repository:** https://github.com/Rishikakaps/japan-day-capital-deployment-integrity

## 1. Mission

Develop and integrate an Intelligent Evidence Intake subsystem into the existing Capital Deployment Integrity application.

The subsystem must automatically receive unstructured evidence, recognize its contents, extract relevant information, identify the machinery or investment project it relates to, organize the evidence, and make the extracted facts available to the existing claim-to-evidence reconciliation engine.

It should work with:

- Scanned commissioning certificates
- Machinery specification sheets and technical manuals
- Purchase orders, invoices, and procurement records
- Machine nameplate and serial-number photographs
- Factory inspection photographs
- Smartphone videos showing equipment or documents
- Inspection reports, maintenance logs, and corrective-action records
- Acoustic recordings, using the existing/proposed Machine Acoustic Memory module

The objective is to turn a poorly named file such as `IMG_0028.jpg` into structured, searchable, traceable evidence associated with the correct physical asset.

The system must not merely rename documents. It must preserve evidence provenance and enable financial/deployment claim reconciliation.

**Target outcome:** A working, demonstrable minimum viable subsystem, using pretrained document-reading tools and a trained lightweight document classifier where feasible.

## 2. Existing System — Mandatory Integration Constraints

The project already has an operational prototype reportedly using:

- FastAPI and Pydantic
- SQLite/PostgreSQL-compatible persistence
- Existing OCR and document-processing capabilities
- SHA-256 evidence integrity checks
- Asset and inspection records
- Six-claim deterministic reconciliation
- Follow-up requests and analyst decisions
- Audit events and report generation
- Docker and automated tests
- Existing web frontend

These components must be inspected and reused, not independently rebuilt.

Before modifying anything:

1. Inspect repository structure and existing data models.
2. Identify evidence-upload and storage functions.
3. Identify existing OCR functions.
4. Identify machine/asset identification and inspection relationships.
5. Locate claim reconciliation and follow-up creation.
6. Run the existing test suite and record the baseline.
7. Create an isolated feature branch.

Do not assume the file structure in this specification already exists.

Preserve all existing routes, authentication, workflows, dashboards, reconciliation logic, and audit records.

**The existing six-claim engine remains authoritative.** AI classification and extraction are advisory inputs, never independent proof of asset commissioning, installation, ownership, operational status, or investment completion.

## 3. Conceptual Architecture

The system consists of seven connected stages.

**Stage A — Acquisition**

Receive evidence from an inspector, browser upload, camera capture, mobile upload, or authorized synchronized folder.

**Stage B — Immutable Evidence Storage**

Save the original file, record the upload context, calculate a SHA-256 content hash, and create an evidence-ingestion record.

**Stage C — Perception**

Identify media type and extract information:

- PDFs: text extraction and OCR
- Photographs: OCR, QR/barcode reading, visible equipment descriptors
- Videos: selected frames, text recognition, QR/barcode detection
- Audio: attach to acoustic pipeline without requiring text OCR

**Stage D — Document Understanding**

Classify the evidence and extract fields such as document type, machine model, manufacturer, serial number, asset ID, dates, technical specifications, and certificate references.

**Stage E — Asset Resolution**

Match extracted identifiers against the existing Asset Registry. Detect ambiguity and contradictions.

**Stage F — Evidence Indexing**

Create a descriptive title, structured metadata, searchable text, asset relationship, review status, and audit event.

**Stage G — Reconciliation Integration**

Make the evidence available to the existing Evidence Copilot. Generate proposed claim/evidence links or corrective-action suggestions, subject to existing verification rules and human review.

**Architecture flow:**

Capture or Upload → Immutable Storage → OCR/Video Processing → Structured Field Extraction → Asset Matching → Evidence Index → Existing Reconciliation Engine

If a machine cannot be identified safely, place its file in the Unassigned Evidence Inbox rather than silently associating it with the wrong asset.

## 4. Supported Document Categories

Use an extensible document-type enum with the initial categories:

1. `commissioning_certificate`
2. `technical_specification`
3. `purchase_invoice`
4. `purchase_order`
5. `machine_nameplate`
6. `inspection_report`
7. `maintenance_record`
8. `installation_evidence`
9. `acoustic_recording`
10. `other`

Do not infer that a document is a genuine certificate merely because it looks like one. The type represents the apparent document category, not authenticity or legal validity.

For classification, use pretrained extraction plus deterministic keywords for the initial MVP. Optionally train a lightweight TF-IDF + Logistic Regression/Linear SVM classifier on labeled examples.

## 5. Dataset Sources and Intended Use

### Dataset A — Motor Nameplates

Source: https://huggingface.co/datasets/sergiudanstan/motor-nameplate

Approximately 286 photographs of electric motor nameplates, with associated structured fields.

Use this dataset for:

- Manufacturer identification
- Model-number extraction
- Serial-number extraction where legible
- Voltage, current, power, and RPM extraction
- OCR robustness testing
- Field-level evaluation

Also evaluate the related auto-labelled dataset:

https://huggingface.co/datasets/sergiudanstan/motor-nameplate-labels

Its automatically generated labels must not be accepted as guaranteed ground truth.

Audit a manageable subset manually.

The original images were reportedly sourced from web searches. Review underlying image rights before commercial training or redistribution, even though the dataset repository displays a permissive license tag.

### Dataset B — ICDAR SmartDoc 2015

Source: https://zenodo.org/records/1230218

Use the 21.2 MB sample archive first.

This dataset contains real smartphone document-capture footage with document-location annotations.

Use it for:

- Video upload and decoding
- Frame sampling
- Document boundary detection
- Perspective correction
- Sharp-frame selection
- OCR over selected frames
- Testing blur and changing illumination

The dataset is not labelled with machine IDs, and its annotations concern document geometry rather than all text fields.

Do not evaluate asset-identification accuracy using these clips unless a separate, manually established ground truth is available.

The original dataset is distributed under CC BY 4.0.

### Dataset C — FUNSD

Source: https://guillaumejaume.github.io/FUNSD/

Contains 199 annotated scanned forms.

Use for testing:

- Key–value extraction
- Header recognition
- Document field relationships
- Multi-field extraction
- Form-processing errors

It does not specifically label industrial commissioning certificates.

### Dataset D — DocLayNet

Source: https://huggingface.co/datasets/docling-project/DocLayNet

Contains 80,863 annotated document pages, including manuals, financial reports, tenders, patents, and other document layouts.

Use existing pretrained document-layout models where possible. Do not download the entire approximately 28 GiB core dataset during the initial three-hour build.

The dataset's role is layout understanding rather than machine identity matching.

### Dataset E — ICDAR Scene Text

Source: https://rrc.cvc.uab.es/?ch=4

Use real-world scene-text images to test recognition of text under oblique camera angles and imperfect lighting.

These images are not machine-nameplate-specific.

### Dataset F — Real Manufacturer Specifications

Source: https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2.html

Use the Haas VF-2 product specification page and available technical documents as examples of authentic machinery documentation.

Test extraction of:

- Manufacturer
- Equipment/model name
- Spindle characteristics
- Power ratings
- Travel dimensions
- Tool capacity
- Electrical requirements

Manufacturer specifications describe a model or configuration. They do not establish a unique physical machine's serial number or prove procurement, delivery, installation, or commissioning.

Use these as reference materials, respecting source-use terms.

### Dataset G — Industrial Video Samples (Optional)

Source: https://huggingface.co/datasets/VerboseTechLabs/manufacturing-unit-egocentric-sample

This resource advertises manufacturing POV clips suitable for testing video ingestion and general scene analysis.

It is optional because the dataset viewer currently reports an access/loading error. Verify downloadable video files before making it part of the build.

No machine serial-number extraction ground truth is guaranteed.

### Dataset H — DocILE (Future)

Source: https://docile.rossum.ai/

Useful for business-document and invoice information extraction, but research access is required.

Do not make successful access to DocILE a dependency of the hackathon MVP.

## 6. Create the Demonstration Dataset

Public datasets do not reliably provide a single real industrial asset with all of the following paired together:

- Its manufacturer specification
- Its actual serial-number plate
- Its procurement invoice
- Its commissioning certificate
- Its inspection video
- Its acoustic recordings
- Its maintenance history

Therefore, create a **synthetic linked demonstration case** while using real public examples for independent extraction tests.

Create three fictitious assets:

| Asset ID | Model | Serial | Purpose |
|---|---|---|---|
| CNC-001 | DEMO-VF200 | DEMO-SN-001 | Correct machine case |
| CNC-002 | DEMO-VF500 | DEMO-SN-002 | Primary inspection case |
| CNC-003 | DEMO-VF500 | DEMO-SN-003 | Same-model identification conflict |

The serial numbers and models above are synthetic test identifiers, not real Haas or other manufacturer serials.

Generate the following fictional supporting documents:

- CNC-002 commissioning certificate
- CNC-002 technical specification
- CNC-002 purchase invoice
- CNC-002 inspection report
- CNC-003 commissioning certificate
- CNC-003 serial/nameplate label
- Incorrectly labelled CNC-002 file that actually refers to CNC-003
- Document containing only a model number
- Document with an unreadable serial number
- Duplicate version of an already uploaded document
- File that has no recognizable asset identifier
- File that refers to multiple machines

Mark each generated artifact internally as `synthetic_demo`.

Create actual smartphone capture videos:

**Video 1:** Printed CNC-002 demonstration certificate, recorded while moving a phone camera over it.

**Video 2:** Printed CNC-002 nameplate and QR code, captured from different angles.

**Video 3:** An intentionally conflicting CNC-003 serial number shown while the upload is associated with CNC-002.

These are staged video captures, but they produce real video inputs under blur, lighting, focus, and motion variations.

Keep synthetic demonstration material clearly distinguishable from genuine industrial evidence.

## 7. Training Dataset Format

Create a data directory with:

- `datasets/raw/`
- `datasets/annotations/`
- `datasets/splits/`
- `datasets/evaluation/`
- `models/`

Use a JSON Lines or CSV manifest linking files to their labels.

Each annotation should include:

- Sample ID
- File path
- Source dataset
- Dataset license/provenance
- Real or synthetic indicator
- Media type
- Document category
- Ground-truth manufacturer
- Ground-truth model
- Ground-truth serial number, if available
- Ground-truth asset association, if independently known
- Visible text transcription, when manually verified
- Field-level page/region references
- Whether the sample contains a conflict
- Whether automatic association should be permitted

Use null for unknown values. Never fill missing serial numbers with invented identifiers.

For an initial lightweight document classifier, curate approximately 50–100 labeled examples if available. Split training and evaluation by original document/template family to avoid near-duplicate leakage.

For industrial field extraction, manually inspect at least a modest held-out selection of nameplate images before scoring. Auto-generated metadata is insufficient as independent evaluation truth.

## 8. Model Design

Do not train a large OCR or video foundation model from scratch.

Use the following hybrid architecture.

### Model A — Document Text Extraction

Default:

- PyMuPDF for selectable PDF text
- Existing OCR pipeline, if functional
- Tesseract or pretrained PaddleOCR for raster documents and photographs

Procedure:

1. Inspect the file type.
2. Try native text extraction for PDFs.
3. OCR pages or regions without usable selectable text.
4. Preserve page numbers and image coordinates.
5. Save extracted text once so it can be reused.

### Model B — Document Type Classification

Begin with predefined rules and a pretrained language model where configured.

Optional lightweight trainable classifier:

- Input: cleaned OCR/document text
- Features: TF-IDF word and character n-grams
- Classifier: Logistic Regression or Linear SVM
- Output: document-category prediction and a confidence estimate where properly calibrated

Train only on labeled examples with clear categories.

If a trained classifier is unavailable, the rule/pretrained-model pipeline must still function.

### Model C — Structured Entity Extraction

Extract:

- `asset_id`
- `manufacturer`
- `model_number`
- `serial_number`
- `document_reference`
- `document_date`
- `supplier`
- `purchase_order_number`
- `invoice_number`
- `rated_power_kw`
- `rated_voltage_v`
- `rated_speed_rpm`
- `commissioning_date`
- `inspector_name`
- `document_type`

Use regex, table/key–value extraction, and optional pretrained LLM-based schema extraction.

Any language-model output must be validated against the source text, numeric formats, and known identifiers.

Each field must carry:

- Value
- Source document
- Page or video timestamp
- Source text span or bounding box, if available
- Extraction method/model version
- Confidence or uncertainty state
- Human confirmation state

Do not treat uncalibrated LLM confidence estimates as probabilities of correctness.

### Model D — Asset Resolution

Asset identity matching must be mostly deterministic.

Matching sequence:

1. Check authenticated inspection/asset context.
2. Decode visible QR/barcode, if any.
3. Extract serial number and explicit asset ID.
4. Match these to the existing registry.
5. Check for contradictory identifiers.
6. Use manufacturer/model details only to narrow candidates.
7. Create a candidate link or verified automatic link.
8. Route unresolved/conflicting evidence to review.

A model number alone must never establish a unique asset match.

A QR code that resolves to CNC-002 establishes the app's asset context, but is not independent proof that the sticker is physically attached to the financed machine.

For high-consequence evidence, corroborate asset identity using serial details and inspector review.

### Model E — Video Evidence Processing

Accept limited-duration MP4/MOV video files for the MVP.

Processing sequence:

1. Verify video size, type, duration, and encoding.
2. Store and hash the original video.
3. Extract a small number of representative frames with FFmpeg/OpenCV.
4. Use blur/focus measures to shortlist useful frames.
5. Run barcode detection and OCR on selected frames.
6. Detect repeated strings across frames.
7. Preserve the best frame and its timestamp.
8. Return extracted identifiers with evidence references.
9. Route results through the same Asset Resolver as PDF/photo evidence.

Frame sampling can begin at one frame per second, capped to a small number of frames for demonstration.

Do not analyze every video frame with a costly vision model.

Do not conclude a machine was commissioned simply because a video shows it running.

### Model F — Existing Acoustic Memory Integration

For audio files, reuse the asset-linking and storage infrastructure.

Store:

- Asset ID
- Inspection ID
- Original audio
- Duration/codec
- Capture conditions
- Timestamp
- SHA-256 hash
- Acoustic analysis result
- Review status

The Evidence Intake subsystem organizes this data but does not replace the Machine Acoustic Memory anomaly-analysis implementation.

## 9. Storage Design

Use object storage for media and SQL for metadata.

The hackathon MVP can use existing local file storage, provided the originals are persistent across application restarts.

Production may use a private S3-compatible bucket.

Original files must not be overwritten, renamed destructively, or modified.

Suggested object-key pattern:

`tenant_id/raw/evidence_uuid`

Suggested derived-file pattern:

`tenant_id/derived/evidence_uuid/artifact_type`

A human-readable name is generated separately, for example:

`CNC-002_Commissioning_Certificate_2026-10-25.pdf`

Store original filename, display filename, media type, byte size, hash, and object key independently.

Support duplicates by content hash and repeated references, without losing separate upload audit events.

### Proposed database extensions

Adapt these concepts to existing tables rather than creating redundant entities.

**EvidenceIngestion**

- id
- tenant_id
- case_id
- inspection_id
- uploader_id
- source_type
- original_filename
- media_type
- size_bytes
- content_sha256
- storage_key
- processing_status
- created_at

**EvidenceExtraction**

- id
- evidence_id
- field_name
- extracted_value
- confidence
- page_number
- video_timestamp
- bounding_box
- source_text
- extractor_version
- review_status

**AssetMatchCandidate**

- id
- evidence_id
- asset_id
- match_method
- matching_identifiers
- conflicting_identifiers
- decision
- reviewed_by
- reviewed_at

**EvidenceProcessingJob**

- id
- evidence_id
- pipeline_version
- status
- attempts
- last_error
- started_at
- completed_at

Reuse the existing audit-event and claim/evidence linking tables.

## 10. File Synchronization

All file sources must use one ingestion service.

### Browser/Mobile Upload

User uploads a file through the existing app.

The upload API returns an evidence identifier immediately after durable storage.

The frontend polls processing status.

Possible states:

`uploaded → queued → processing → linked`

or:

`uploaded → queued → processing → needs_review`

or:

`uploaded → queued → failed`

### Local Folder Sync

Add an optional Python folder watcher for explicitly authorized folders.

When a new file appears:

1. Wait until writing has completed.
2. Calculate its hash.
3. Submit it through the ingestion API.
4. Record the source file identifier.
5. Avoid duplicate processing.
6. Preserve the original.

### Cloud Storage Sync

Treat Google Drive, SharePoint, and similar integrations as later development unless an authorized connector already exists.

Use provider APIs/webhooks or polling rather than attempting to access users' files without authorization.

Production requirements include retry queues, resumable uploads, access control, credential management, and idempotency.

## 11. API Requirements

Inspect existing endpoints first. Add compatible routes only where needed.

Suggested interfaces:

**POST `/api/evidence/intake`**

Multipart file upload with case ID, optional inspection ID, optional asset hint and source metadata.

Return evidence ID, upload status, hash, and processing status.

**GET `/api/evidence/{id}/processing-status`**

Return current processing stage, extraction status, classification, and errors.

**GET `/api/evidence/{id}/extraction`**

Return structured extracted fields and source references.

**GET `/api/evidence/{id}/asset-candidates`**

Return candidate assets with matching and conflicting identifiers.

**POST `/api/evidence/{id}/confirm-asset`**

Authorized analyst confirms or rejects the proposed asset relationship.

**GET `/api/assets/{asset_id}/evidence`**

Return the asset's related evidence and its review/verification status.

Suggested demo limits, configurable:

- PDFs/images: 25 MB
- Videos: 100 MB and 30 seconds
- Restrict uploads to permitted formats
- Apply page and frame processing limits
- Use private storage and authenticated access

Validate actual file content, not only filename extensions.

## 12. Frontend Integration

Add an **Evidence Inbox** to the existing app.

Do not redesign the existing four-screen application unless necessary.

Each evidence item should show:

- Original filename
- Suggested human-readable title
- Document type
- Extracted asset/model/serial
- Confidence/review state
- Upload time and source
- File preview
- Processing status
- Proposed asset association
- Confirm/reject controls
- Link to claim or corrective-action workflow

The analyst must be able to view the actual source region supporting a field.

Example:

**File:** `scan_019.pdf`  
**Classified as:** Commissioning certificate  
**Asset candidate:** CNC-002  
**Model:** DEMO-VF500  
**Serial:** DEMO-SN-002  
**Status:** Awaiting document verification

For conflicting identifiers, prominently display why automatic association was refused.

## 13. Three-Hour MVP Execution Plan

This is an aggressive implementation target, assuming existing app dependencies work and baseline OCR/storage components can be reused.

**0–20 minutes: Existing system inspection**

- Check repository and branch.
- Run baseline automated tests.
- Find OCR, upload, storage, and asset relationships.
- Avoid modifying existing reconciliation logic.

**20–50 minutes: Unified ingestion**

- Implement/reuse upload endpoint.
- Store original and SHA-256.
- Save ingestion record.
- Add simple processing states.

**50–85 minutes: OCR and structured extraction**

- Reuse existing OCR.
- Add nameplate field extraction.
- Add commissioning/specification/invoice classification rules.
- Store extracted fields.

**85–115 minutes: Asset matching**

- Match serial/asset identifiers to registry.
- Add conflict rejection.
- Add searchable titles and metadata.
- Add analyst confirmation.

**115–145 minutes: Video processing or classifier**

- Prioritize basic frame extraction and OCR on one SmartDoc clip.
- If video infrastructure is blocked, complete a small document-classifier training run instead.
- Do not attempt full video-model training.

**145–180 minutes: Integration testing**

- Connect Evidence Inbox.
- Test upload-to-asset workflow.
- Test a contradictory serial number.
- Test duplicate upload.
- Run existing tests.
- Document the working and incomplete features.

After the MVP, implement both the complete video workflow and lightweight classifier as follow-on tasks if one was deferred.

Do not claim either was completed unless executable tests demonstrate it.

## 14. Evaluation Plan

Evaluate separately on:

**A. Document classification**

Accuracy, macro-F1, confusion matrix, and unsupported/unknown document handling.

**B. Field extraction**

Exact match or normalized field match for manufacturer, model, serial, dates, and other selected fields.

Missing fields must not count as correct guesses.

**C. Asset association**

- Correctly linked assets
- Incorrect automatic links
- Correctly rejected mismatches
- Cases requiring human review
- Percentage of evidence automatically matched

The principal safety target is **zero incorrect automatic links in the held-out adversarial demo set**. This is a target, not a claim of production reliability.

**D. Video extraction**

- Whether frames were decoded
- Whether a useful document frame was selected
- Whether the relevant text was readable
- Whether an identifier was extracted correctly
- Processing time per video

**E. End-to-end functionality**

- Successful uploads
- SHA-256 integrity verification
- Persistence after restart
- Reprocessing idempotency
- Correct claim/evidence relationship
- Audit record creation
- Manual review and correction

Training and test samples from the same original document or video must remain in the same split. Do not randomly split adjacent video frames across training and test sets.

## 15. Required Test Scenarios

Implement automated or reproducible tests for:

1. Correct CNC-002 certificate uploaded as an unnamed PDF.
2. Correct machine nameplate photograph.
3. Document specifying only a manufacturer/model.
4. Two machines sharing a model.
5. Wrong serial number in an otherwise plausible certificate.
6. Contradictory asset ID and serial number.
7. Duplicate evidence upload.
8. Corrupted PDF.
9. Unreadable/blurred nameplate.
10. Unknown document category.
11. SmartDoc smartphone video.
12. Manually recorded demonstration QR/nameplate video.
13. Upload followed by application restart.
14. Evidence corrected by an authorized reviewer.
15. Existing reconciliation tests still passing.

Every test must have an explicit expected outcome.

## 16. Security and Evidentiary Safeguards

- Never allow AI text in uploaded documents to override system instructions.
- Never execute uploaded documents or scripts.
- Use authenticated uploads, private object storage, and tenant-scoped access.
- Treat OCR text, QR values, and document titles as untrusted data.
- Do not automatically mark commissioning complete from a document type.
- Preserve original files and their hashes.
- Log AI-generated suggestions and analyst overrides.
- Maintain evidence provenance and extraction/model versions.
- Validate permissions before sending documents to external AI services.
- Do not treat synthetic documents or staged videos as genuine industrial proof.
- Avoid automatic learning from customer uploads without review, authorization, and a separate training-data governance process.

## 17. Definition of Done

The MVP is complete only when:

- The current application still runs.
- Existing tests continue passing.
- A PDF/photo can be uploaded.
- Its original is stored and hashed.
- OCR can extract usable text.
- A document category can be assigned or rejected.
- At least one machine identifier can be extracted and checked.
- Matching evidence appears under the correct asset.
- Conflicts trigger manual review.
- Evidence remains available after application restart.
- The analyst can inspect and correct an association.
- The existing reconciliation engine receives evidence through its proper interface.
- At least one public real-world data sample and one synthetic end-to-end scenario have been tested.
- Test results and limitations are recorded.

The video workflow and trained classifier must be separately reported as completed, partially completed, or not implemented.

## 18. Required Deliverables

The coding AI should produce:

1. Working changes in the existing repository.
2. Database migrations where required.
3. Data ingestion and document-processing modules.
4. Asset matching and conflict-review functionality.
5. Evidence Inbox frontend integration.
6. Training and evaluation scripts for the lightweight classifier, if implemented.
7. Dataset manifest and source/license register.
8. Unit and integration tests.
9. README with local setup and restart commands.
10. Demonstration fixtures with synthetic data labels.
11. Actual test metrics rather than hypothetical accuracy figures.
12. A concise technical note on architecture, storage, scalability, and known limitations.

**Final principle:** The subsystem must maximize correct, traceable evidence association and minimize false machine-to-document links. A smaller functioning system with rigorous identity checks is preferable to a visually impressive but unreliable multimodal model.

Do not replace the current application or damage working features. Extend it incrementally, test each change, and preserve the six-claim reconciliation workflow as the central product capability.