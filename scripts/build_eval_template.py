"""
Generate the held-out ground-truth label template (Tier 0, step 3).

Selects 20 SKUs from data/catalog.json and writes
eval/ground_truth/labels_template.json with every target attribute key
present and set to null. Attribute keys come from pipeline.schema so this
file can never drift from what the pipeline actually outputs.

This script does not, and must never, fill in a value. The human labels this
file by hand from raw_title/raw_description alone -- see
eval/ground_truth/README.md.
"""

import json
from pathlib import Path

from pipeline.schema import ATTRIBUTE_FIELDS

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog.json"
OUT = ROOT / "eval" / "ground_truth" / "labels_template.json"

# Held-out SKU IDs, hand-picked from data/catalog.json for spread across both
# curation tier (so Tier 2's quarantine-correctness check has something to
# check) and accessory type (so precision/recall isn't measured on one
# product shape). Not random sampling -- same reasoning as build_catalog.py.
EVAL_SKU_IDS = [
    # unparseable (2) -- ground truth here should end up all-null; this is
    # what "the pipeline correctly quarantined it" gets checked against.
    "SKU-001",
    "SKU-002",
    # missing_ambiguous (4) -- spread across headphone / case / cable / charger.
    "SKU-006",
    "SKU-012",
    "SKU-014",
    "SKU-019",
    # messy_parseable (14) -- spread across every accessory type in the catalog.
    "SKU-021",
    "SKU-024",
    "SKU-026",
    "SKU-030",
    "SKU-032",
    "SKU-036",
    "SKU-041",
    "SKU-044",
    "SKU-047",
    "SKU-053",
    "SKU-056",
    "SKU-057",
    "SKU-059",
    "SKU-060",
]
assert len(EVAL_SKU_IDS) == 20
assert len(set(EVAL_SKU_IDS)) == 20


def main():
    catalog = {row["sku_id"]: row for row in json.loads(CATALOG.read_text(encoding="utf-8"))}

    missing = [s for s in EVAL_SKU_IDS if s not in catalog]
    if missing:
        raise SystemExit(f"SKU ids not found in catalog.json: {missing}")

    template = []
    for sku_id in EVAL_SKU_IDS:
        row = catalog[sku_id]
        template.append(
            {
                "sku_id": row["sku_id"],
                "raw_title": row["product_name"],
                "raw_description": row["description"],
                "labels": {field: None for field in ATTRIBUTE_FIELDS},
            }
        )

    OUT.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(template)} unlabelled SKUs to {OUT.relative_to(ROOT)}")
    print(f"Label keys: {ATTRIBUTE_FIELDS}")


if __name__ == "__main__":
    main()
