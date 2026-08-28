"""
Ground-truth pre-fill from seller-authored structured specs (hybrid eval
methodology -- see eval/ground_truth/README.md for the full rationale).

This does NOT replace hand labeling. It parses the raw dataset's
product_specifications column for the 20 held-out SKUs and writes SUGGESTED
values into eval/ground_truth/labels_template.json's `labels`, so a human
reviews and corrects 20 pre-filled rows instead of writing 20 from a blank
page. Every SKU keeps a `verified` flag (default false); eval/extraction_eval.py
refuses to score a SKU until a human has set it to true. That flag is the
whole point -- it's what keeps "hand-verified, held-out" honestly true while
cutting labeling time down.

Never overwrites a label a human has already set (i.e. any non-null value,
or any SKU already marked verified) -- rerunning this after labeling starts
only fills in what's still blank.

Split hygiene: many raw descriptions embed the seller's own spec table
inline, starting at "Specifications of ...". That block is stripped to
produce `extractor_eval_description` -- what Tier 2 will actually feed the
extractor -- so the extractor is never handed the answer key formatted as a
literal table. tests/test_ground_truth_leakage.py re-asserts the marker
never survives the strip, against whatever is actually committed, so a
future hand-edit can't silently reintroduce it.

That strip does NOT chase every verbatim occurrence of a ground-truth value
elsewhere in the description. Sellers routinely restate the compatible
phone model in the description's own opening sentence ("Key Features of X
For Y") -- that's the same fact recoverable from prose, worded/positioned
differently than the structured key, and it's the actual extraction signal
this eval is supposed to measure, not a leak. An earlier version of this
script truncated on any such match and produced near-empty descriptions for
most rows (e.g. "Instyles Back Cover for" with the model cut off) -- that
defeated the eval rather than protecting it. What's implemented instead:
find_leaking_fields() runs as a diagnostic over the post-strip text and
records which fields are naturally restated in prose, per SKU
(`prose_restated_fields`, informational only -- not evidence of a problem).

Usage:
    python eval/build_ground_truth.py
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # scripts/ isn't a package; let this run directly, matching the other scripts

from pipeline.extract import SPEC_BLOCK_MARKER, strip_spec_block
from scripts.build_eval_template import EVAL_SKU_IDS

RAW_CSV = ROOT / "data" / "raw" / "flipkart_com-ecommerce_sample.csv"
CATALOG = ROOT / "data" / "catalog.json"
LABELS_TEMPLATE = ROOT / "eval" / "ground_truth" / "labels_template.json"

# ---------------------------------------------------------------------------
# Spec key -> schema field mapping. Key names vary across sellers (this is
# the same messy dataset the whole project is built on), so each field
# checks a list of observed variant key names, case-insensitively.
# ---------------------------------------------------------------------------

DESIGNED_FOR_KEYS = ["designed for", "designed_for", "compatible devices", "suitable for"]
CONNECTOR_KEYS = ["connector", "connector 1", "connectors"]
TYPE_KEYS = ["type", "case or cover", "headset design"]
MATERIAL_KEYS = ["material"]
BATTERY_CAPACITY_KEYS = ["battery capacity"]
WATTAGE_KEYS = ["wattage", "output wattage"]
WIRED_WIRELESS_KEYS = ["wired/wireless"]


def parse_specs(raw: str) -> dict[str, str]:
    pairs = re.findall(r'"key"=>"(.*?)", "value"=>"(.*?)"', raw or "")
    return {k.strip().lower(): v.strip() for k, v in pairs}


def get_any(specs: dict[str, str], keys: list[str]) -> str | None:
    for k in keys:
        if specs.get(k):
            return specs[k]
    return None


ALL_TARGET_KEYS = (
    DESIGNED_FOR_KEYS + CONNECTOR_KEYS + TYPE_KEYS + MATERIAL_KEYS + BATTERY_CAPACITY_KEYS + WATTAGE_KEYS + WIRED_WIRELESS_KEYS
)


def has_structured_signal(specs: dict[str, str]) -> bool:
    """Whether product_specifications contains ANY of our mapped keys --
    independent of accessory_type's product-name fallback, which almost
    always finds something and would otherwise mask a SKU that genuinely has
    no usable structured data (the point of tracking this separately)."""
    return get_any(specs, ALL_TARGET_KEYS) is not None


def suggest_accessory_type(specs: dict[str, str], product_name: str) -> str | None:
    signal = (get_any(specs, TYPE_KEYS) or "") + " " + product_name
    signal = signal.lower()
    # Order matters: check the more specific phrases before generic ones.
    if "power bank" in signal or "powerbank" in signal:
        return "power_bank"
    if "screen guard" in signal or "tempered glass" in signal or "screen protector" in signal:
        return "screen_protector"
    if "pouch" in signal or "sleeve" in signal:
        return "pouch"
    if "case" in signal or "cover" in signal:
        return "case"
    if "charger" in signal or "charging pad" in signal:
        return "charger"
    if "headphone" in signal or "earphone" in signal or "headset" in signal or "earbud" in signal:
        return "headphone"
    if "cable" in signal or "otg" in signal:
        return "cable"
    return None


def suggest_connector_type(specs: dict[str, str], accessory_type: str | None) -> str | None:
    if accessory_type == "headphone":
        wired = get_any(specs, WIRED_WIRELESS_KEYS)
        if wired:
            return "bluetooth" if wired.lower() == "wireless" else "3_5mm_jack"
        return None

    raw = get_any(specs, CONNECTOR_KEYS)
    if not raw:
        return None
    v = raw.lower()
    if "micro usb" in v or "micro-usb" in v:
        return "micro_usb"
    if "type c" in v or "type-c" in v or "usb c" in v or "usb-c" in v:
        return "usb_c"
    if "lightning" in v or "8 pin" in v:
        return "lightning"
    if v.strip() in ("a type", "usb a", "usb-a"):
        return "usb_a"
    return None  # e.g. "AC - 3N Pin" is a wall-plug pin standard, not a data connector -- don't guess


def suggest_material(specs: dict[str, str]) -> str | None:
    raw = get_any(specs, MATERIAL_KEYS)
    if not raw:
        return None
    v = raw.lower()
    if "plastic" in v:
        return "plastic"
    if "silicone" in v or "tpu" in v or "rubber" in v:
        return "silicone_tpu"
    if "leather" in v:
        return "leather"
    if "metal" in v or "aluminium" in v or "aluminum" in v:
        return "metal"
    if "glass" in v:
        return "tempered_glass"
    if "fabric" in v or "nylon" in v or "canvas" in v:
        return "fabric_nylon"
    return "other"


def suggest_model_compat(specs: dict[str, str]) -> list[str] | None:
    raw = get_any(specs, DESIGNED_FOR_KEYS)
    if not raw:
        return None
    parts = re.split(r",| and |&", raw)
    return [p.strip() for p in parts if p.strip()]


def suggest_capacity_mah(specs: dict[str, str]) -> int | None:
    raw = get_any(specs, BATTERY_CAPACITY_KEYS)
    if not raw:
        return None
    m = re.search(r"([\d,]+)\s*mah", raw, re.IGNORECASE)
    return int(m.group(1).replace(",", "")) if m else None


def suggest_wattage_w(specs: dict[str, str]) -> float | None:
    raw = get_any(specs, WATTAGE_KEYS)
    if not raw:
        return None
    m = re.search(r"([\d.]+)\s*w\b", raw, re.IGNORECASE)
    return float(m.group(1)) if m else None


def suggest_wireless_charging(specs: dict[str, str], accessory_type: str | None, product_name: str) -> bool | None:
    if accessory_type not in ("charger", "power_bank", "case"):
        return None  # field doesn't apply to this accessory type
    signal = (product_name + " " + " ".join(specs.values())).lower()
    # confident negative when nothing indicates wireless support, not "unknown"
    return "wireless" in signal or " qi " in signal or "qi-" in signal


def suggest_labels(specs: dict[str, str], product_name: str) -> dict:
    accessory_type = suggest_accessory_type(specs, product_name)
    return {
        "accessory_type": accessory_type,
        "model_compat": suggest_model_compat(specs),
        "connector_type": suggest_connector_type(specs, accessory_type),
        "wattage_w": suggest_wattage_w(specs),
        "capacity_mah": suggest_capacity_mah(specs),
        "screen_size_in": None,  # not present as a structured field anywhere in this dataset
        "wireless_charging": suggest_wireless_charging(specs, accessory_type, product_name),
        "material": suggest_material(specs),
    }


# ---------------------------------------------------------------------------
# Split hygiene: strip_spec_block/SPEC_BLOCK_MARKER now live in
# pipeline/extract.py (imported above) -- that's the module that actually
# uses them at extraction time; this file just needs the same behavior for
# consistency between what gets scored and what gets published. See the
# module docstring above for why this is a hard strip at the marker only,
# not a chase-every-substring truncation.
# ---------------------------------------------------------------------------


def find_leaking_fields(labels: dict, text: str) -> dict[str, int]:
    """Diagnostic only -- NOT used to truncate. Returns {field_name:
    earliest_index} for every label value that appears verbatim
    (case-insensitive) in text, so a human reviewing the SKU can see which
    fields are naturally restated in the prose. Only checks strings of
    meaningful length (>=4 chars) to avoid noise from short/common tokens --
    this is the same reason enum values (e.g. "usb_c") rarely trigger it:
    the raw prose says "USB C", not the canonical snake_case form, so this
    naturally has little to say about already-canonicalized fields and
    mostly flags the free-text ones (model_compat)."""
    text_l = text.lower()
    leaks: dict[str, int] = {}
    for field, value in labels.items():
        candidates = value if isinstance(value, list) else [value]
        for v in candidates:
            if not isinstance(v, str) or len(v) < 4:
                continue
            idx = text_l.find(v.lower())
            if idx != -1:
                leaks[field] = min(idx, leaks.get(field, idx))
    return leaks


def main():
    catalog = {row["sku_id"]: row for row in json.loads(CATALOG.read_text(encoding="utf-8"))}
    raw_rows = {}
    csv.field_size_limit(10**7)
    with RAW_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw_rows[row["uniq_id"]] = row

    template = json.loads(LABELS_TEMPLATE.read_text(encoding="utf-8"))
    by_id = {entry["sku_id"]: entry for entry in template}

    missing = [s for s in EVAL_SKU_IDS if s not in by_id]
    if missing:
        raise SystemExit(f"labels_template.json is missing SKUs: {missing}. Run scripts/build_eval_template.py first.")

    n_suggested = 0
    n_no_structured_specs = 0
    n_prose_restated = 0
    n_already_verified = 0

    for sku_id in EVAL_SKU_IDS:
        entry = by_id[sku_id]
        if entry.get("verified"):
            n_already_verified += 1
            continue

        catalog_row = catalog[sku_id]
        raw_row = raw_rows[catalog_row["source_uniq_id"]]
        specs = parse_specs(raw_row["product_specifications"])
        suggestion = suggest_labels(specs, catalog_row["product_name"])

        suggested_fields = []
        for field, value in suggestion.items():
            if entry["labels"].get(field) is None and value is not None:
                entry["labels"][field] = value
                suggested_fields.append(field)
        entry["suggested_fields"] = suggested_fields
        entry.setdefault("verified", False)

        if not has_structured_signal(specs):
            n_no_structured_specs += 1
        else:
            n_suggested += 1

        extractor_text = strip_spec_block(catalog_row["description"])
        assert not SPEC_BLOCK_MARKER.search(extractor_text), f"{sku_id}: spec-block marker survived the strip"
        entry["extractor_eval_description"] = extractor_text

        restated = find_leaking_fields(entry["labels"], extractor_text)
        entry["prose_restated_fields"] = sorted(restated)
        if restated:
            n_prose_restated += 1

    LABELS_TEMPLATE.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Updated {LABELS_TEMPLATE.relative_to(ROOT)}")
    print(f"  {n_suggested} SKUs had usable structured specs -- at least one field pre-filled")
    print(f"  {n_no_structured_specs} SKUs had no usable structured specs at all -- hand-label from raw text (good quarantine test cases)")
    print(f"  {n_prose_restated} SKUs naturally restate a suggested value in the description's own prose (informational, not a problem)")
    print(f"  {n_already_verified} SKUs already verified -- left untouched")
    print("\nNothing here is final ground truth yet. Every row still needs a human to review")
    print("suggested_fields, fill in what's blank, correct anything wrong, and set \"verified\": true.")


if __name__ == "__main__":
    main()
