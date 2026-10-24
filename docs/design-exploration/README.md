# Frontend layout exploration — 20 generated mockups

Five layout directions for each of four proposed V1 pages. These are raster concept templates, not implemented UI or an approved scope change. Generated with the built-in image-generation tool; prompts are preserved in `prompts.json`.

The images use the original prepared trial baseline (15 supported / 3 unresolved). The current live demo has 16 supported / 2 unresolved after the certificate test. Generated names, dates, control labels and counts are illustrative and must be checked against the API contract before implementation. A layout mockup does not add a feature to V1.

| Direction | Density | Main idea |
|---|---|---|
| A — Minimal notebook | Low | Document-like whitespace, inline tables, simple forms |
| B — Clean product dashboard | Comfortable | Sidebar, cards, clear status summaries |
| C — Evidence-first split workspace | Medium | Navigator, original evidence and analyst inspector side by side |
| D — Guided workflow cockpit | High | Task queue, process stages, current action and context |
| E — Dense operations dashboard | Highest | Dark console, compact panels and persistent history |

Choose a structure for each page; there is no requirement to use the densest option. The final application should use one coherent typography, spacing and navigation system even if its pages use different layouts.

- [Inspection overview: compare A–E](01-overview.md)
- [Evidence workspace: compare A–E](02-evidence.md)
- [Site inspection: compare A–E](03-site-inspection.md)
- [Assessment and follow-ups: compare A–E](04-assessment.md)

## Elements to retain when choosing

- Overview: inspection/role context, machine cards, six-claim matrix, counts, next actions and unresolved requests.
- Evidence: upload/list, original preview, editable extracted fields, quality flags, acceptance, claim links and history.
- Site inspection: machine/checklist, photo, observed identifiers, condition, presence/installation unknown states, source, timestamp and notes.
- Assessment: reconciliation, computed/reviewed conclusions, reasons, evidence, follow-ups, review completion, exports and audit history.
- Shared: loading/errors, stale assessment indicator, edit-conflict handling and read-only judge access.

No frontend code or backend behavior was changed to create this gallery.

## Labelled simple-theme guide

[Theme A: all four screens with numbered explanations](labelled-theme-a/README.md), covering data sources, analyst-editable fields, system results and read-only judge access.
