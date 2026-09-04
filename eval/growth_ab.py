"""
Tier 2 -- before/after growth harness (CLAUDE.md's "headline result").

Same ~40 synthetic purchase intents, resolved twice:
  A) against the RAW catalog -- product_name + description prose only, no
     structured schema. An LLM call per batch of intents: genuinely reading
     messy human listings is exactly the capability being measured here, so
     a keyword matcher would stand in for the wrong thing.
  B) against the GENERATED AgentFront surface -- surface/mcp_server.py's
     published, quarantine-filtered, redacted catalog. Pure deterministic
     Python matching, zero LLM calls -- exactly what a real MCP-backed
     buyer agent computes via search_catalog/get_product once the data is
     typed.

Ground truth. Every intent is synthesized FROM one source SKU's own
published (post-redaction) attributes, so that SKU always satisfies its
own intent by construction -- there is no "no valid answer exists" case in
this harness, deliberately: what's being measured is whether each target
FINDS an answer that provably exists, not whether it detects true
unanswerability. Ground truth for an intent is the full set of published
SKUs that satisfy it, computed by resolve_intent_structured() -- the SAME
function Target B uses to answer. That is not circular scoring: it is the
central causal claim of this project made concrete. Once attributes are
verified and structured, deterministic matching against them is correct
by construction; the number that actually matters is how far Target A
(an LLM reading raw prose) falls short of that deterministic ceiling.

Three metrics (a deliberately scoped subset of CLAUDE.md's four -- Agent
Basket Value and Out-of-Stock Recovery are out of scope for this pass,
there was no time budget to build substitution/bundling logic before the
deadline):
  - Completion rate: purchased a SKU that's actually a correct answer
  - Wrong-item rate: purchased a SKU that is NOT a correct answer
  - Dead-end rate: purchased nothing, despite a correct answer existing

Target A's LLM calls are disk-cached per intent (data/growth_ab_cache/,
keyed on hash(intent_id + intent text + catalog content + prompt_version +
model)), so a re-run -- e.g. demo rehearsal -- costs zero quota. Intents
are batched INTENT_BATCH_SIZE-per-request (same reasoning as
pipeline/extract.py's batched primary extraction: the catalog listing is
the expensive, repeated part of the prompt, not any one intent) -- this
was NOT separately validated against an unbatched run the way extraction
batching was (see pipeline/extract.py's docstring); flagged here rather
than silently assumed safe.
"""

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel

from pipeline.extract import trim_boilerplate
from pipeline.llm_clients import get_chat_model_with_fallback
from pipeline.llm_config import get_component_config
from pipeline.verify import (
    CompatibilityProposal,
    verify_model_compat_match,
    verify_wattage_sufficient,
)
from surface.mcp_server import PublishedProduct, load_published_catalog

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
CACHE_DIR = ROOT / "data" / "growth_ab_cache"

PROMPT_VERSION = "v1"
INTENT_SEED = 20260904  # fixed -- same 40 intents every run, reproducible
NUM_INTENTS = 40
RAW_SNIPPET_CHARS = 150  # per-SKU description cap in the raw catalog listing -- token-cost control
INTENT_BATCH_SIZE = 10

CATEGORY_LABELS = {
    "case": "phone case", "pouch": "phone pouch", "screen_protector": "screen protector",
    "cable": "charging cable", "charger": "charger", "headphone": "headphones",
    "power_bank": "power bank", "other": "phone accessory",
}
CONNECTOR_LABELS = {
    "usb_a": "USB-A", "micro_usb": "Micro-USB", "usb_c": "USB-C", "lightning": "Lightning",
    "3_5mm_jack": "3.5mm jack", "bluetooth": "Bluetooth", "other": "a non-standard connector",
}


# ---------------------------------------------------------------------------
# Intent generation.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PurchaseIntent:
    intent_id: str
    text: str
    source_sku_id: str
    category: str
    model: str | None = None
    min_wattage: float | None = None
    connector: str | None = None


def build_intents(published: dict[str, PublishedProduct], seed: int = INTENT_SEED, n: int = NUM_INTENTS) -> list[PurchaseIntent]:
    rng = random.Random(seed)
    sku_ids = sorted(published.keys())
    sample = rng.sample(sku_ids, min(n, len(sku_ids)))

    intents = []
    for i, sku_id in enumerate(sample):
        attrs = published[sku_id].attributes
        category = published[sku_id].category

        model = rng.choice(attrs.model_compat.value) if attrs.model_compat.value else None
        min_wattage = attrs.wattage_w.value
        connector = attrs.connector_type.value.value if attrs.connector_type.value else None

        parts = [f"I want to buy a {CATEGORY_LABELS.get(category, category)}"]
        if model:
            parts.append(f"that works with my {model.replace('_', ' ').title()}")
        if min_wattage:
            parts.append(f"supporting at least {min_wattage:g}W charging")
        if connector:
            parts.append(f"with a {CONNECTOR_LABELS.get(connector, connector)} connector")
        text = " ".join(parts) + "."

        intents.append(
            PurchaseIntent(
                intent_id=f"intent-{i + 1:03d}", text=text, source_sku_id=sku_id,
                category=category, model=model, min_wattage=min_wattage, connector=connector,
            )
        )
    return intents


# ---------------------------------------------------------------------------
# Target B: deterministic matching against the structured surface. Also
# doubles as the ground-truth function -- see module docstring for why
# that's not circular.
# ---------------------------------------------------------------------------


def resolve_intent_structured(intent: PurchaseIntent, published: dict[str, PublishedProduct]) -> list[str]:
    matches = []
    for sku_id, product in published.items():
        if product.category != intent.category:
            continue
        attrs = product.attributes
        if intent.model is not None:
            proposal = CompatibilityProposal(sku_id=sku_id, claimed_model=intent.model, claimed_basis="model_compat_match")
            if not verify_model_compat_match(proposal, attrs).verified:
                continue
        if intent.min_wattage is not None:
            proposal = CompatibilityProposal(
                sku_id=sku_id, claimed_model="", claimed_basis="wattage_sufficient", required_wattage_w=intent.min_wattage
            )
            if not verify_wattage_sufficient(proposal, attrs).verified:
                continue
        if intent.connector is not None and (
            attrs.connector_type.value is None or attrs.connector_type.value.value != intent.connector
        ):
            continue
        matches.append(sku_id)
    return matches


def resolve_intents_structured(intents: list[PurchaseIntent], published: dict[str, PublishedProduct]) -> dict[str, str | None]:
    results = {}
    for intent in intents:
        matches = resolve_intent_structured(intent, published)
        results[intent.intent_id] = matches[0] if matches else None
    return results


def ground_truth_for(intents: list[PurchaseIntent], published: dict[str, PublishedProduct]) -> dict[str, list[str]]:
    return {intent.intent_id: resolve_intent_structured(intent, published) for intent in intents}


# ---------------------------------------------------------------------------
# Target A: LLM reading raw catalog prose. Disk-cached per intent.
# ---------------------------------------------------------------------------


class ShoppingPick(BaseModel):
    intent_id: str
    sku_id: str | None = None


class ShoppingBatchResponse(BaseModel):
    picks: list[ShoppingPick]


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _catalog_listing_text(catalog_rows: list[dict]) -> str:
    lines = []
    for row in catalog_rows:
        snippet = trim_boilerplate(row["description"])[:RAW_SNIPPET_CHARS]
        lines.append(f"{row['sku_id']}: {row['product_name']} -- {snippet}")
    return "\n".join(lines)


def _cache_key(intent: PurchaseIntent, catalog_hash: str, model: str) -> str:
    raw = f"{intent.intent_id}|{intent.text}|{catalog_hash}|{PROMPT_VERSION}|{model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _cache_put(key: str, value: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")


def build_raw_batch_prompt(catalog_text: str, batch: list[PurchaseIntent]) -> str:
    requests_text = "\n".join(f"[{i.intent_id}] {i.text}" for i in batch)
    return (
        "You are a shopping assistant matching buyer requests against a REAL, messy "
        "online catalog of phone accessories -- these are raw human-written listings, "
        "not a spec sheet. For EACH buyer request below, pick the sku_id of the single "
        "best-matching product. Resolve every request INDEPENDENTLY of the others -- do "
        "not let one request's answer leak into another's.\n"
        "If the listings don't give you enough information to confidently satisfy a "
        "request (e.g. no listing mentions the phone model, connector, or wattage "
        "asked for), return sku_id=null rather than guessing -- a wrong guess is worse "
        "than admitting you can't tell.\n\n"
        f"CATALOG:\n{catalog_text}\n\n"
        f"BUYER REQUESTS:\n{requests_text}"
    )


def resolve_intents_raw(
    intents: list[PurchaseIntent], catalog_rows: list[dict], batch_size: int = INTENT_BATCH_SIZE, use_cache: bool = True
) -> dict[str, str | None]:
    catalog_text = _catalog_listing_text(catalog_rows)
    catalog_hash = hashlib.sha256(catalog_text.encode("utf-8")).hexdigest()[:16]
    model_name = get_component_config("extractor").model

    results: dict[str, str | None] = {}
    to_resolve: list[PurchaseIntent] = []
    for intent in intents:
        key = _cache_key(intent, catalog_hash, model_name)
        cached = _cache_get(key) if use_cache else None
        if cached is not None:
            results[intent.intent_id] = cached["sku_id"]
        else:
            to_resolve.append(intent)

    if results:
        print(f"  {len(results)}/{len(intents)} intents served from cache (zero quota spent)", flush=True)
    if to_resolve:
        n_batches = -(-len(to_resolve) // batch_size)
        print(f"  {len(to_resolve)}/{len(intents)} intents need a raw-catalog LLM call ({n_batches} batched request(s))", flush=True)
        for i, batch in enumerate(_chunks(to_resolve, batch_size)):
            print(f"  [raw batch {i + 1}/{n_batches}] {len(batch)} intents", flush=True)
            model = get_chat_model_with_fallback("extractor", output_schema=ShoppingBatchResponse)
            response = model.invoke(
                build_raw_batch_prompt(catalog_text, batch),
                config={"run_name": f"growth_ab:raw:{i}", "tags": ["growth_ab", "raw"]},
            )
            picks = {p.intent_id: p.sku_id for p in response.picks}
            for intent in batch:
                sku_id = picks.get(intent.intent_id)
                results[intent.intent_id] = sku_id
                if use_cache:
                    _cache_put(_cache_key(intent, catalog_hash, model_name), {"sku_id": sku_id})
    return results


# ---------------------------------------------------------------------------
# Scoring.
# ---------------------------------------------------------------------------


@dataclass
class GrowthMetrics:
    n: int
    completions: int
    wrong_items: int
    dead_ends: int
    completion_rate: float
    wrong_item_rate: float
    dead_end_rate: float


def score(intents: list[PurchaseIntent], picks: dict[str, str | None], ground_truth: dict[str, list[str]]) -> GrowthMetrics:
    completions = wrong_items = dead_ends = 0
    for intent in intents:
        pick = picks.get(intent.intent_id)
        truth = ground_truth[intent.intent_id]
        if pick is None:
            dead_ends += 1
        elif pick in truth:
            completions += 1
        else:
            wrong_items += 1
    n = len(intents)
    return GrowthMetrics(
        n=n, completions=completions, wrong_items=wrong_items, dead_ends=dead_ends,
        completion_rate=completions / n, wrong_item_rate=wrong_items / n, dead_end_rate=dead_ends / n,
    )


def main():
    catalog_rows = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    published = load_published_catalog()
    intents = build_intents(published)
    ground_truth = ground_truth_for(intents, published)

    print(f"Generated {len(intents)} purchase intents from {len(published)} published SKUs (seed={INTENT_SEED})")

    print("\n--- Target B: structured AgentFront surface (deterministic, zero LLM) ---")
    picks_b = resolve_intents_structured(intents, published)
    metrics_b = score(intents, picks_b, ground_truth)

    print("\n--- Target A: raw catalog text (LLM interpretation, cached) ---")
    picks_a = resolve_intents_raw(intents, catalog_rows)
    metrics_a = score(intents, picks_a, ground_truth)

    print("\n" + "=" * 72)
    print(f"{'Metric':<28}{'A: raw catalog':>18}{'B: AgentFront':>18}")
    print(f"{'Completion rate':<28}{metrics_a.completion_rate:>17.0%} {metrics_b.completion_rate:>17.0%}")
    print(f"{'Wrong-item rate':<28}{metrics_a.wrong_item_rate:>17.0%} {metrics_b.wrong_item_rate:>17.0%}")
    print(f"{'Dead-end (no purchase)':<28}{metrics_a.dead_end_rate:>17.0%} {metrics_b.dead_end_rate:>17.0%}")
    print("=" * 72)

    out = {
        "seed": INTENT_SEED,
        "n_intents": len(intents),
        "intents": [asdict(i) for i in intents],
        "ground_truth": ground_truth,
        "picks_a": picks_a,
        "picks_b": picks_b,
        "metrics_a": asdict(metrics_a),
        "metrics_b": asdict(metrics_b),
    }
    out_path = ROOT / "eval" / "growth_ab_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
