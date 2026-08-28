"""
Tier 2 extraction evaluation: per-field precision/recall/F1 against the
held-out ground truth in eval/ground_truth/labels_template.json, plus
overall coverage and expected-quarantine tracking.

Only scores SKUs marked "verified": true -- a human has reviewed/corrected
the pre-filled suggestions (see eval/build_ground_truth.py). An unverified
row is refused, not silently skipped-with-a-warning: scoring against a raw
auto-suggestion would launder it as ground truth, exactly the shortcut the
hybrid methodology exists to avoid.

Usage:
    python eval/extraction_eval.py                          # ground-truth stats only
    python eval/extraction_eval.py --predictions preds.json  # full P/R/F1

predictions.json shape: {sku_id: {field_name: value, ...}, ...} -- plain
values matching pipeline.schema field names/types, i.e. AttrValue.value
already unwrapped, not the confidence-carrying form.

No predictions file exists yet -- pipeline/extract.py hasn't been built
(Tier 1). This module is ready for when it is.

Matching is exact-value equality (case-insensitive for strings, set
equality for model_compat lists). That's necessarily a rough measure until
pipeline/canonical.py exists to normalize both sides onto the same
vocabulary -- e.g. a predicted "Xiaomi Mi 4i" against a ground-truth
"xiaomi mi4i" would currently score as a miss. Documented here rather than
silently producing an optimistic or pessimistic number.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.schema import ATTRIBUTE_FIELDS

ROOT = Path(__file__).resolve().parent.parent
LABELS_TEMPLATE = ROOT / "eval" / "ground_truth" / "labels_template.json"


@dataclass
class FieldMetrics:
    field: str
    support: int  # number of verified SKUs with a non-null ground-truth value for this field
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if not p or not r or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return frozenset(_normalize(v) for v in value)
    return value


def values_match(predicted: Any, ground_truth: Any) -> bool:
    return _normalize(predicted) == _normalize(ground_truth)


def load_ground_truth() -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Returns (verified ground truth {sku_id: {field: value}}, unverified sku_ids skipped)."""
    entries = json.loads(LABELS_TEMPLATE.read_text(encoding="utf-8"))
    verified, skipped = {}, []
    for entry in entries:
        if entry.get("verified"):
            verified[entry["sku_id"]] = entry["labels"]
        else:
            skipped.append(entry["sku_id"])
    return verified, skipped


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_quarantine_skus(ground_truth: dict[str, dict[str, Any]]) -> list[str]:
    """SKUs where a human found no recoverable value for any field -- the
    ground truth Tier 2's quarantine-correctness check compares the
    pipeline's actual quarantine decisions against."""
    return [sku_id for sku_id, labels in ground_truth.items() if all(v is None for v in labels.values())]


def score_field(field: str, predictions: dict[str, dict[str, Any]], ground_truth: dict[str, dict[str, Any]]) -> FieldMetrics:
    tp = fp = fn = support = 0
    for sku_id, labels in ground_truth.items():
        gt_value = labels.get(field)
        pred_value = predictions.get(sku_id, {}).get(field)

        if gt_value is None:
            if pred_value is not None:
                fp += 1  # extractor claimed a value where ground truth has none
            continue

        support += 1
        if pred_value is None:
            fn += 1
        elif values_match(pred_value, gt_value):
            tp += 1
        else:
            fp += 1
            fn += 1

    return FieldMetrics(field=field, support=support, tp=tp, fp=fp, fn=fn)


def score_all(predictions: dict[str, dict[str, Any]], ground_truth: dict[str, dict[str, Any]]) -> dict[str, FieldMetrics]:
    return {field: score_field(field, predictions, ground_truth) for field in ATTRIBUTE_FIELDS}


def _fmt(x: float | None) -> str:
    return f"{x:.2f}" if x is not None else "n/a"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, help="Path to a predictions JSON file (see module docstring for shape).")
    args = parser.parse_args()

    ground_truth, skipped = load_ground_truth()
    quarantine_skus = expected_quarantine_skus(ground_truth)

    print("=" * 72)
    print(f"Verified ground-truth SKUs: {len(ground_truth)}")
    if skipped:
        print(f"Skipped (not yet verified, excluded from scoring): {skipped}")
    print(f"Expected-quarantine SKUs (all fields null): {quarantine_skus}")

    if not args.predictions:
        print("\nNo --predictions given -- nothing to score yet (pipeline/extract.py isn't built).")
        print("Re-run with --predictions once it is.")
        print("=" * 72)
        return

    predictions = load_predictions(args.predictions)
    metrics = score_all(predictions, ground_truth)

    print(f"\n{'field':<20}{'support':>8}{'precision':>12}{'recall':>10}{'f1':>8}")
    for field, m in metrics.items():
        print(f"{field:<20}{m.support:>8}{_fmt(m.precision):>12}{_fmt(m.recall):>10}{_fmt(m.f1):>8}")

    scored = [m.f1 for m in metrics.values() if m.f1 is not None]
    if scored:
        print(f"\nMacro-average F1 across fields with support: {sum(scored) / len(scored):.2f}")
    print("=" * 72)


if __name__ == "__main__":
    main()
