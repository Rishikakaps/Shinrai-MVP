# Connected multimodal continuation — 25 October 2026

This checkpoint integrates `main` workflow improvements, V2 browser/capture fixes,
merged field PR #3 (`0db393a`) and intake PR #4 (`32ecad8`, now also merged remotely as `dd46e9b`). It preserves the existing
FastAPI app, SQLite/Postgres typed store, immutable originals, audited review and
six deterministic claims. PR #4's persisted queue is the shared ingestion service;
there is no second intake implementation or replacement fixture database.

## Operational records and reviewed proposals

- `AssetCreate`, `AssetUpdate` and `Asset` now retain nullable serial, invoice and
  payment references, manufacturer, technical label values and provenance.
- `app/registry.py` is shared by existing declaration endpoints and scan proposals.
  Each created record gets six unconfirmed claims. Saved edits are audited and
  reset claim confirmations; earlier findings remain in history and become stale.
- Unknown serials never match empty evidence identifiers. Physical identity cannot
  be bound until a reviewed serial exists. Placeholder identities were not inserted.
- Overview has a searchable, editable registry. Manufacturer/model suggestions come
  from actual records; users can correct values. Blank unknowns stay null.
- `/api/evidence/{id}/registry-proposal` applies an explicit create/update proposal
  with current record versions, original integrity checks and conflict acknowledgement.
  It records the source intake and reviewer. It never accepts evidence or supports claims.
- `/api/evidence/{id}/adjust-image` saves a new JPEG from a photo or selected video
  frame, with crop/rotation/contrast metadata, parent/source hashes and timestamps.
  Its original is preserved and the shared queue performs OCR and matching.
- Deliberate phone label scans queue the same stored original for intake and link directly to its create/update review. Accepted sources are not reprocessed by this action.
- Inbox candidate advice is recomputed against the current registry at review time.
  Association, reviewed fact acceptance, explicit claim links and reconciliation
  remain separate steps. Existing conversation, acoustic and follow-up services remain.
- MP3 audio is additionally validated/decoded through the existing bounded FFmpeg
  audio service; WAV/WebM/M4A remain supported. No acoustic model was trained.

## Motor source data

`python -m scripts.seed_motors --env /absolute/path/to/private/.env --url http://127.0.0.1:8003`
imports the supplied CSV through the operational authenticated API. It creates a
separate Plant C case and visit, 40 records and 240 unconfirmed claims, with 14 null
serials and zero supported claims. Reruns retain edited records using source-row
provenance, rather than depending solely on editable tags. Local runner accepts
only loopback destinations; credentials never enter output or URLs.

`python -m scripts.hydrate_motors --output work/motor-source` resolves source
filenames using the downloaded manufacturer/model/serial metadata. It refuses
ambiguous matches and validates actual image formats, including PNG bytes under
published `.jpg` names. Downloads and runtime media stay ignored.

The local running trial imported 37 uniquely matched original photographs into the
Inbox. Three of 40 source lookups remained ambiguous. Originals remain unaccepted
and unassigned; source-to-registry provenance is not physical identity evidence.
Public metadata labels are automatically generated/unverified. Plant C and MTR
internal tags are synthetic associations. Missing purchase/payment/installation/
commissioning evidence was not manufactured.

Initial real OCR run: 37 processed, 37 needing review; publisher serial appears
literally in OCR text for 5 of 23 non-null serial labels, and publisher model for
4 of 37 models. These are raw text agreement counts, **not accuracy measurements**:
labels are unverified, several source images are very small, and narrow key/value
extraction does not cover arbitrary table layouts. A contact sheet of 12 photos
and the MTR-008 source were visually inspected. The WEG capitalization correction
was saved through the real browser; this did not establish identity or any claim.

No source photographs are redistributed in Git. Source/rights register:
[datasets/sources.md](../datasets/sources.md). Public repository licensing does not
independently establish rights to every web-collected source photograph.

## Executed verification

- Baseline after fetching field PR #3: 153 passed, 17 service-dependent skips.
- Combined regression: 175 passed, 17 skipped; one existing Starlette deprecation
  warning. Skips include PostgreSQL/Mailpit service configurations; do not present
  them as passing service integration in this continuation.
- Registry/proposal/adjustment/MP3/phone queue tests: eight passed, including real FFmpeg video
  decoding, real Tesseract OCR of its crop, preserved timestamps/hashes, new/update
  proposal persistence, stale saves, null identifiers and import idempotency.
- Frontend DOM/state tests: 20 passed, including retained fields on rejected/stale saves, nullable registry values, source provenance and judge-write guards. Python lint/format and JavaScript syntax passed.
- Actual in-app browser: Plant C records rendered; WEG capitalization edit saved;
  synthetic MP4 uploaded using the real file chooser; timestamped frames rendered;
  a selected frame was cropped and OCRed; reviewed proposal created CNC-DEMO-041
  with six claims; record and original media survived a backend restart.
- The clip is an authored, encoded synthetic test video, **not a physical phone
  recording**. A separate upstream SmartDoc result is preserved as prior evidence;
  it was not independently rerun on this host.

## Demo walkthrough

1. Open `/app`, select **Plant C — 40 Motor Nameplates (PUBLIC DATASET / UNVERIFIED)**.
   Search `MTR-008`; inspect metadata and provenance. Explain missing identifiers
   and absent financial/deployment proof before editing a field with a reason.
2. Open **Evidence Inbox**. Choose a saved public photo, inspect its original/text
   and candidates. Retain unclear values or correct them explicitly. Do not equate
   a publisher label or site association with verified physical identity.
3. For a connected successful scan demonstration, choose the separate synthetic
   Plant A visit. The saved `synthetic-new-motor.mp4` and adjusted image illustrate
   timestamps, OCR, the source hash and the created `CNC-DEMO-041` record.
4. For a new trial use a new explicitly fictional identifier. Upload a photo/PDF or
   an authorized MP4/MOV; wait for processing. For video select a frame, optionally
   crop/rotate/improve contrast, then review the derived image's OCR.
5. Open **Create or update a registry record from this scan**. Review fields,
   acknowledge new/conflicting identity, enter a reason and save. Updating an
   existing record requires its current version. Refresh Overview to see it.
6. Review source facts separately, select a claim relationship and save its locator.
   Confirm the intended declaration, reconcile through existing Assessment, and
   review resulting findings. A nameplate does not establish commissioning or payment.
7. Use existing contextual conversation/follow-up controls only after their identity,
   consent and explicit confirmation requirements. A task-status change is not closure proof.
8. Reload; audit history and earlier findings remain. Restart with the same absolute
   `CDI_DATA_DIR` to retain files, data and sessions.

## Startup and limits

Use existing private configuration. macOS local trial:

```sh
CDI_ENV_FILE=/absolute/path/to/private/.env \
CDI_DATA_DIR=/absolute/path/to/persistent-data \
CDI_ENABLE_REMINDERS=false PORT=8003 python -m scripts.serve
```

Windows uses the same `scripts.serve` module and existing `.tools` discovery. Keep
FFmpeg/ffprobe, Tesseract and Poppler installed as documented in the field guide.
Do not run an older checkout against new `EvidenceKind.other` records without
checking rollback compatibility. Back up database **and** original/derived files.

Documents/images/audio: 12 MiB. Video: configured limit up to 100 MiB, 30 seconds,
six samples and at most three distinct OCR frames. Parent worker deadline: 120s;
source-worker failure retains original and retry status. The local demo was tested
with a small synthetic clip, not a 100 MiB stress test. Crop, 90° rotation and contrast
are implemented; document-boundary detection/perspective correction are not.

Gemini private configuration was rechecked as present; no new live-provider call was
claimed here. Classifier is rule based; no model training or calibrated confidence
was performed. Physical Android camera/mic acceptance, Windows startup, Docker,
current HTTPS phone session and an independent industrial OCR benchmark remain
unverified. No glasses hardware/SDK or live Wispr Flow streaming is claimed.
