"""
Tier 0 catalog curation: select ~60 SKUs from the raw Flipkart dump into
data/catalog.json, preserving every text field verbatim.

Source category: "Mobiles & Accessories" (data/raw/flipkart_com-ecommerce_sample.csv).
That category contains zero phone/handset SKUs -- only accessories (pouches/
cases, screen protectors, cables & chargers, headphones, power banks) whose
phone-model compatibility lives entirely in free text. See
data/catalog_selection_notes.md for why that shape was kept instead of forcing
a "phones + accessories" catalog the source data doesn't actually have.

This script is deliberately hand-curated, not randomly sampled: the SKU_IDS
below were chosen by inspecting the raw rows (messiness, missing fields,
genuine unparseability) rather than by a heuristic scorer, because "is this
realistically bad in the way Tier 1 needs" is a judgment call, not a metric.
Re-running this script reproduces the same catalog.json from the same raw CSV.
"""

import csv
import json
import re
from pathlib import Path

csv.field_size_limit(10**7)

ROOT = Path(__file__).resolve().parent.parent
RAW_CSV = ROOT / "data" / "raw" / "flipkart_com-ecommerce_sample.csv"
OUT_CATALOG = ROOT / "data" / "catalog.json"
OUT_NOTES = ROOT / "data" / "catalog_selection_notes.md"

# uniq_id -> curation tier, hand-picked by reading the raw rows.
# "unparseable" = a careful human can't recover the schema's attributes either.
# "missing_ambiguous" = a real but critical field is vague, contradictory, or absent.
# "messy_parseable" = recoverable, but inconsistent casing/abbreviations/prose.
UNPARSEABLE = {
    "ef6df5f016ae015f394e52e4ff13b974": "empty product_specifications; description is pure Flipkart boilerplate with no attributes beyond the title",
    "10e27e65a4abd19cef5dfefcf68d0ace": "only Brand/Model ID/Color present; no wired-vs-wireless, no connector, no phone compatibility anywhere",
    "67f4e285d5ad55e418a926063cfa5fc6": "only Brand/Model ID/Color present; same gap as above",
    "4fcc6115656b061c0a97b358d230a0f9": "only Brand/Model ID/Color present; same gap as above",
    "00e6fd068b140fac2c25d443d146c3c8": "only Brand/Model ID/Color present; title even has a stray empty '()' artifact from the scrape",
}

MISSING_AMBIGUOUS = {
    "79e75a50b7369dc6cc910346e3a85f73": "designed_for='All Smart Phones' (generic); 'Note 4' in the title could be a phone model or just the product's own name",
    "73251fa112fe08dbdbdc96c028c7db47": "designed_for='All Smart Phones'; 'M5' in title is not attributable to a specific phone",
    "b06840ec066994aa351c79bc34fa8d26": "designed_for='Mobile'; '23000' in title is a model number, not a phone reference",
    "136454e94f8b20fd332f510601919c2c": "title says 'Wired & Wireless Bluetooth' in the same breath -- contradicts itself on the single most basic attribute",
    "85746bd7ec397edbd4f727ab0f381cca": "designed_for='Mobile'; no specific phone named anywhere",
    "bfb1fcf0c9f0e4dd31a9842dc969375c": "designed_for='All Smart Phones'; 'C5' is ambiguous (own product line vs a phone model)",
    "ef9979756bed63f8769f27fe0a2f9242": "compat stated as 'for All Smartphone like Samsung HTC etc' -- explicitly open-ended, not enumerable",
    "b8a106b15649ee9bf320b22637928e82": "designed_for='Mobile, Tablet'; title only says 'Android Smart Phone', no model",
    "c23414205d9c0a3aa3d4858e302af6c1": "designed_for='Galaxy Note' with no number -- Note, Note 2, Note 3, Note 4, Note 5 all fit that string",
    "865132314c090f76c37f4dff3c23b8f6": "title says '7 Inch Oppo Find 7A', but the Find 7A is a ~5.5in phone -- the size claim contradicts the named device",
    "1809e7d5323129665c057c799d7e19f2": "'Samsung Galaxy Note 510' does not match any real Samsung Note model number",
    "ed5ac228227cc215a8a9974c7bfa8788": "brand is 'codio World' but the model name is 'Sony CP-V0 112' -- unclear if this is a genuine Sony part or an unrelated seller's own naming",
    "28816aea8f796815cbdf79045e391830": "compat given only as 'Motorola' (brand-level), no model at all",
    "ae5f7ee4c38b73b64d7be051f5251a10": "no wattage/amperage anywhere in specs or prose -- only 'Dual USB Compatible Compact Durable'",
    "253a7f050335f81d9c3b653b463f605e": "same open-ended 'All Smartphone like Samsung HTC etc' compat framing as its sibling SKU above",
}

MESSY_PARSEABLE = {
    # Phone cases mis-filed by Flipkart's own taxonomy under "Tablet Accessories >>
    # Cases & Covers" despite being phone cases -- the category tree itself lies.
    "75a9ae324963e8e55c6daf5083db8645": "Cases & Covers",
    "355764d0c12a929a723f261ee8ddd623": "Cases & Covers",
    "62a03af5e515df26ea63540037882327": "Cases & Covers",
    "ea50eae5073795eade79e1ca03ddb8a8": "Cases & Covers",
    "e9fbc0f287fa176b41c5e1927e433774": "Cases & Covers",
    # Mobile Pouches -- correctly categorized phone soft-cases.
    "87ff92f89ef9d34b3d71c36955ce591a": "Mobile Pouches",
    "eff607ce599e3838eb6c59924ef228c6": "Mobile Pouches",
    "2c96ec1b2c02e4c29bb61d03668478a6": "Mobile Pouches",
    "db5907cf7031f5a8aaa39c5528f8c5d2": "Mobile Pouches",
    "23796e1090af5cf64b6e5e65588c9498": "Mobile Pouches",
    "329bfc353845d319b1ad7cd6c4ea482f": "Mobile Pouches",
    # Screen Protectors.
    "af70c64c8d00290fd4a12359324f07f7": "Screen Protectors",
    "6005ddffeb04cf1cbccb755fef765fa8": "Screen Protectors",
    "fe392901c6f553f081f3241102e0a2b7": "Screen Protectors",
    "be524d3b1ef3918ec82d6b19b3f2f117": "Screen Protectors",
    "e727291191aa38fdcbf1eb53cd1749c0": "Screen Protectors",
    "8f1048b1989d3e3f58b4703520fc002e": "Screen Protectors",
    "bbcade9935cfa9fd712f526eaa1e358b": "Screen Protectors",
    "afe5a8ff0ab55a568a0404cb3c73a7f5": "Screen Protectors",
    "cfb9a6c27ee36e9fb055aba00a6cb975": "Screen Protectors",
    "aff2e05f81dc8539185012cab56493aa": "Screen Protectors",
    "22315c1f2ff963fd776dce0deb0a34b7": "Screen Protectors",
    "2c6d5f208844efb2e3875b5988098dbd": "Screen Protectors",
    # Cables / Chargers.
    "017b4baf09ba01799cb01ecc96356f26": "Mobile Chargers",  # "Dzire VC" = HTC Desire VC
    "ad6210c447cbb2e5d7ff622bee497a2f": "Mobile Chargers",  # "Mt X (2nd Gen)" = Moto X 2nd Gen
    "46648b54c8bcf683369be053be1bf987": "Mobile Chargers",  # "Lnvo Vibe P1M" = Lenovo Vibe P1M
    "771687605b6817bda7fd00293d838211": "Chargers",
    "1adc62302d19c52dc67da80dc5afe2c0": "Chargers",  # "Huwai" typo for Huawei
    "4c36816e2cc47ec682fc127635543660": "Chargers",  # impossible dims (5x5x5mm) but real amperage in prose
    "03e236d543c63a869ae044a664b0eaf1": "Cables",
    "268e62d2ab00a036100ee9c29fd357ce": "Cables",
    "c666e51ec698f56a304d5fd9c1687229": "Cables",
    "b2bd8db9578465b8794619c2ddc2c4b8": "Cables",  # genuine USB-C example
    "6dbb5d4e70f833f2e6f87b2c463c276c": "Cables",
    "60195bad5fab468d54f1273a3d400f56": "Chargers",
    # Headphones.
    "c9e5e9b915f201516c40ed6c0b02e405": "Headphones",  # spec key says generic 'Mobile', title names exact model
    "19e429857f2b8f609c732dbe6ff3bc05": "Headphones",  # "XIOMI" typo for Xiaomi
    "685aef6aaa5cf32d29cab2b7a2e054ac": "Headphones",  # slash-separated multi-model list + wired/Bluetooth category conflict
    # Power Banks.
    "b381180b1795b4a37b3782dc4b60d6d9": "Power Banks",
    "1f3d9f893bf65048c8faef6af2c8032d": "Power Banks",
}

ALL_IDS = {**UNPARSEABLE, **MISSING_AMBIGUOUS, **MESSY_PARSEABLE}
assert len(UNPARSEABLE) == 5
assert len(MISSING_AMBIGUOUS) == 15
assert len(MESSY_PARSEABLE) == 40
assert len(ALL_IDS) == 60


def parse_specs_display(raw: str) -> dict:
    """Best-effort key/value pull from the Ruby-hash-rocket spec string, for the
    human-readable report only. catalog.json keeps the raw string untouched."""
    pairs = re.findall(r'"key"=>"(.*?)", "value"=>"(.*?)"', raw or "")
    return dict(pairs)


def main():
    rows_by_id = {}
    with RAW_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["uniq_id"] in ALL_IDS:
                rows_by_id[row["uniq_id"]] = row

    missing = ALL_IDS.keys() - rows_by_id.keys()
    if missing:
        raise SystemExit(f"{len(missing)} curated uniq_ids not found in raw CSV: {missing}")

    catalog = []
    for i, (uid, tier) in enumerate(
        [(u, "unparseable") for u in UNPARSEABLE]
        + [(u, "missing_ambiguous") for u in MISSING_AMBIGUOUS]
        + [(u, "messy_parseable") for u in MESSY_PARSEABLE],
        start=1,
    ):
        row = rows_by_id[uid]
        catalog.append(
            {
                "sku_id": f"SKU-{i:03d}",
                "curation_tier": tier,
                "source_uniq_id": row["uniq_id"],
                "source_pid": row["pid"],
                "product_name": row["product_name"],
                "product_category_tree": row["product_category_tree"],
                "brand": row["brand"],
                "retail_price": row["retail_price"],
                "discounted_price": row["discounted_price"],
                "description": row["description"],
                "product_specifications_raw": row["product_specifications"],
                "product_rating": row["product_rating"],
                "overall_rating": row["overall_rating"],
                "product_url": row["product_url"],
            }
        )

    OUT_CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- report ----
    lines = []
    lines.append("# Catalog selection report\n")
    lines.append(f"{len(catalog)} SKUs written to `data/catalog.json`.\n")
    lines.append(
        "Category: **Mobiles & Accessories** (phone cases/pouches, screen protectors, "
        "cables & chargers, headphones, power banks). The raw dataset has **no phone "
        "handset SKUs at all** in this category -- every row is an accessory, and phone "
        "compatibility is expressed as free text (title / description / a "
        "`Designed For`-style spec key), never as a link to an actual phone product.\n"
    )
    for tier, ids_map in [
        ("messy_parseable", MESSY_PARSEABLE),
        ("missing_ambiguous", MISSING_AMBIGUOUS),
        ("unparseable", UNPARSEABLE),
    ]:
        lines.append(f"\n## {tier} ({len(ids_map)})\n")
        for uid in ids_map:
            row = rows_by_id[uid]
            lines.append(f"- `{row['pid']}` {row['product_name']}")
            if tier != "messy_parseable":
                lines.append(f"  - why: {ids_map[uid]}")
    OUT_NOTES.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(catalog)} SKUs to {OUT_CATALOG.relative_to(ROOT)}")
    print(f"Wrote selection notes to {OUT_NOTES.relative_to(ROOT)}")

    by_sub = {}
    for uid in ALL_IDS:
        row = rows_by_id[uid]
        sub = row["product_category_tree"].strip('[]"').split(" >> ")[2] if row["product_category_tree"].count(">>") >= 2 else "?"
        by_sub[sub] = by_sub.get(sub, 0) + 1
    print("\nBy accessory subcategory:")
    for sub, n in sorted(by_sub.items(), key=lambda x: -x[1]):
        print(f"  {n:3d}  {sub}")


if __name__ == "__main__":
    main()
