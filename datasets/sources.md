# Dataset and rights register — checkpoint, 25 October 2026

| Source | Role and inspected status | Rights / evaluation boundary |
|---|---|---|
| [Motor Nameplate](https://huggingface.co/datasets/sergiudanstan/motor-nameplate) | 37 uniquely matched source photos downloaded locally and processed; 3 of 40 lookups ambiguous; publisher labels remain unverified | MIT repository tag does not settle rights to web-sourced photographs. Manual image/label audit still needed. |
| [Auto-labelled nameplates](https://huggingface.co/datasets/sergiudanstan/motor-nameplate-labels) | Card inspected; auto-generated model outputs visible; not used as truth | Underlying image rights unverified; automated labels are not independently verified ground truth. |
| [SmartDoc 2015](https://zenodo.org/records/1230218) | 21,203,716-byte sample archive downloaded, publisher MD5 verified; real datasheet video tested | CC BY 4.0. Cite Burie et al., “ICDAR2015 Competition on Smartphone Document Capture and OCR (SmartDoc),” ICDAR 2015. Geometry annotations do not establish machine IDs. Results in `evaluation/smartdoc.json`. |
| [FUNSD](https://guillaumejaume.github.io/FUNSD/) | 199 annotated forms advertised; not downloaded/scored | Dataset use/license terms need confirmation before redistribution; not industrial commissioning ground truth. |
| [DocLayNet](https://huggingface.co/datasets/docling-project/DocLayNet) | Card inspected; viewer reported dataset-script error; full corpus not downloaded | Card license is “other”; review original component terms. Layout corpus, not unique-machine identity truth. |
| [ICDAR Scene Text](https://rrc.cvc.uab.es/?ch=4) | Page fetch timed out; no files used | Access and terms not verified; no recognition claim based on this source. |
| [Haas VF-2](https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2.html) | Referenced product page returned dynamic fragments; no technical-document extraction evaluated | Manufacturer specifications are model context, not serial/procurement/installation proof. No manufacturer material redistributed. |
| [Manufacturing POV sample](https://huggingface.co/datasets/VerboseTechLabs/manufacturing-unit-egocentric-sample) | Card inspected; viewer loading error observed; direct video downloads not tested | CC BY 4.0 advertised; no asset-serial ground truth established. Optional, not an MVP dependency. |
| [DocILE](https://docile.rossum.ai/) | Future source; no restricted files requested/downloaded | Access and source terms must be checked; not a build dependency. |

`annotations/synthetic-manifest.jsonl` describes 14 project-authored, explicitly
fictional files produced by `python -m scripts.intake_demo`. Ground truth comes
from those authored fixtures. Missing/partial identifiers remain unknown. All
fixtures are evaluation-only; no classifier training or production accuracy is
claimed. Raw public media is ignored and is not included in the PR.
