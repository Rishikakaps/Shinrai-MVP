# Uploaded backend integration record

Source: `backend-and-diagrams-github-upload.zip`, supplied by the project owner on 24 October 2026.

Archive SHA-256: `8a95836c39cc5d0dfd961d8e2521fd8a0d97e78003fe7918afd1cd54ef7bf489`.

The source was unpacked with traversal/symlink/size checks and compared with the existing GitHub revision before integration. Text line endings were normalized. Its Postgres adapter/migration, deployment tests, runtime limits, readiness/metadata endpoints, forced OCR, report correctness fixes, backup verification and native/tunnel runners were integrated into the source tree. Existing browser authentication and frontend work were merged rather than replaced. SQLite remains available for the minimal native trial.

The uploaded README referred to `docs/backend-deployment.md` and `docs/frontend-handoff.md`, but neither file was included. Those guides now describe the actual combined implementation and its verified limits. The archive's `docs/diagrams/` entry was an empty directory: no new diagram files were supplied. Existing design galleries and labelled screens were preserved. Older documentation deletions from the ZIP were not applied.

The archived `output/` artifacts were copies of existing synthetic verification records; existing records were preserved. The new live browser exercise has its own `output/ui-trial/` folder. Runtime databases, credentials, environment files and unrelated local design duplicates are excluded from the commit. The original source ZIP is preserved locally in Downloads; GitHub contains the integrated, reviewable source code.
