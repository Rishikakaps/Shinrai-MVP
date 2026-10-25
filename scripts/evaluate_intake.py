"""Measure the actual local rule/OCR pipeline on manifest-held-out fixtures."""

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

from app.intake_perception import perceive
from app.intake_understanding import classify, extract_fields, resolve, values
from app.models import Asset
from scripts.intake_demo import ASSETS


def evaluate(root):
    samples = [json.loads(line) for line in (root / "manifest.jsonl").read_text().splitlines()]
    assets = [
        Asset(
            inspection_id="evaluation",
            tag=tag,
            serial=serial,
            model=model,
            site="Plant A",
            invoice_ref="DEMO-INV",
            payment_ref="DEMO-PAY",
        )
        for tag, model, serial in ASSETS
    ]
    matrix, rows, serial_correct, serial_total = Counter(), [], 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for sample in samples:
            path = root / sample["file_path"]
            raw = perceive(path, sample["media_type"], Path(tmp) / sample["sample_id"], path.name)
            category, _ = classify(raw["text"], sample["media_type"])
            fields = extract_fields(raw["pages"])
            resolution = resolve(fields, assets)
            matrix[(sample["document_category"], category)] += 1
            if sample["ground_truth_serial"]:
                serial_total += 1
                serial_correct += values(fields, "serial_number") == {
                    sample["ground_truth_serial"].casefold()
                }
            rows.append(
                {
                    "sample_id": sample["sample_id"],
                    "expected_category": sample["document_category"],
                    "predicted_category": category,
                    "resolution": resolution["decision"],
                    "automatic_association": resolution["automatic_association"],
                }
            )
    labels = sorted({x for pair in matrix for x in pair})
    f1 = []
    for label in labels:
        tp = matrix[(label, label)]
        fp = sum(n for (truth, pred), n in matrix.items() if pred == label and truth != label)
        fn = sum(n for (truth, pred), n in matrix.items() if truth == label and pred != label)
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    return {
        "pipeline": "pretrained_tesseract_zxing_and_rules_v1",
        "trained_classifier": False,
        "dataset": "project-authored synthetic held-out fixtures; not industrial production accuracy",
        "samples": len(rows),
        "classification_accuracy": sum(n for (truth, pred), n in matrix.items() if truth == pred) / len(rows),
        "classification_macro_f1": sum(f1) / len(f1),
        "serial_exact_match": {"correct": serial_correct, "total_with_known_ground_truth": serial_total},
        "automatic_associations": sum(r["automatic_association"] for r in rows),
        "automatic_association_coverage": 0,
        "confusion_matrix": [
            {"truth": truth, "prediction": pred, "count": n} for (truth, pred), n in sorted(matrix.items())
        ],
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/raw/synthetic"))
    parser.add_argument("--output", type=Path, default=Path("datasets/evaluation/synthetic-rules.json"))
    args = parser.parse_args()
    result = evaluate(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "samples",
                    "classification_accuracy",
                    "classification_macro_f1",
                    "serial_exact_match",
                    "automatic_associations",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
