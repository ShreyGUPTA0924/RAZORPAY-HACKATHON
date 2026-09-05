"""One-off: regenerate frontend/src/data/catalog-sample-raw.json from the
real, committed 60-SKU extraction run (eval/extraction_results.json) plus
the raw catalog's title/price (data/catalog.json) -- replacing the earlier
18-SKU curated subset so the Extraction and Surface screens show the
actual full production run, not an eval-only sample. Not something that
needs to be re-run regularly; kept for reproducibility.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTION_PATH = ROOT / "eval" / "extraction_results.json"
CATALOG_PATH = ROOT / "data" / "catalog.json"
OUT_PATH = ROOT / "frontend" / "src" / "data" / "catalog-sample-raw.json"

ATTRIBUTE_FIELDS = [
    "accessory_type",
    "model_compat",
    "connector_type",
    "wattage_w",
    "capacity_mah",
    "screen_size_in",
    "wireless_charging",
    "material",
]


def price_to_paise(retail_price, discounted_price) -> int:
    raw = discounted_price or retail_price
    try:
        return round(float(raw) * 100)
    except (TypeError, ValueError):
        return 0


def main() -> None:
    extraction_results = json.loads(EXTRACTION_PATH.read_text(encoding="utf-8"))
    catalog = {row["sku_id"]: row for row in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))}

    rows = []
    skipped_errors = 0
    for result in extraction_results:
        if result.get("error"):
            skipped_errors += 1
            continue
        sku_id = result["sku_id"]
        catalog_row = catalog[sku_id]
        quarantine = result["quarantine"]

        attributes = {}
        for field in ATTRIBUTE_FIELDS:
            attr = result["attributes"][field]
            attributes[field] = {"value": attr["value"], "confidence": attr["confidence"]}

        rows.append(
            {
                "skuId": sku_id,
                "title": catalog_row["product_name"],
                "pricePaise": price_to_paise(catalog_row.get("retail_price"), catalog_row.get("discounted_price")),
                "published": quarantine["published"],
                "redactedFields": quarantine["redacted_fields"],
                "attributes": attributes,
            }
        )

    OUT_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} SKUs to {OUT_PATH} ({skipped_errors} skipped for extraction errors)")
    print(f"published: {sum(1 for r in rows if r['published'])}, quarantined: {sum(1 for r in rows if not r['published'])}")
    print(f"with redacted fields: {sum(1 for r in rows if r['redactedFields'])}")


if __name__ == "__main__":
    main()
