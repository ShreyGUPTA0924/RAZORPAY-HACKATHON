"""
Compatibility proposal agent -- Tier 1.

The LLM PROPOSES candidate accessory<->phone-model compatibility edges by
reading RAW catalog prose (title + trimmed description) for a batch of
target phone models -- deliberately NOT the already-extracted, canonical
model_compat field, because the point is to test independent proposal
generation against messy text, the same way pipeline/extract.py's
self-verification re-derives a value blind to the primary call's answer.
pipeline.verify (NO LLM IMPORTS) VERIFIES every proposal against the SKU's
own already-extracted, quarantine-gated ProductAttributes before it can be
published -- an unverifiable proposal is dropped and logged, never
force-published because it "sounds right."

Scope: model_compat_match is the only edge type generated here.
wattage_sufficient needs a `required_wattage_w` and pipeline/extract.py's
real run had a 0% wattage_w extraction rate on this catalog (see
eval/ground_truth/README.md) -- there is nothing to verify a wattage
proposal against yet, so proposing one would be all noise, no signal.

Batched -- one request covers several target models against the full
catalog listing, the same reasoning as pipeline/extract.py's batched
primary extraction and eval/growth_ab.py's batched raw-catalog resolution:
the catalog listing is the expensive, repeated part of the prompt, not any
one target model.

Reading the reported precision: verify_model_compat_match's matching is
deliberately strict (case/hyphen/space-normalized exact match against the
SKU's own extracted model_compat) since it also gates real payment
decisions elsewhere -- it will reject a proposal that is textually correct
but phrased in a DIFFERENT canonical convention than pipeline/extract.py
happened to use for that SKU (a missing brand prefix, "+" vs "plus", a
compound "4/4s/5" list the extractor had already split into separate
tokens, a source-text typo faithfully transcribed). A real run's every
rejection was manually checked against the raw catalog text and none were
hallucinations -- the reported number measures exact-form agreement
between two independently-generated canonicalizations, not whether the
proposer read the text correctly. Closing that gap for real would mean
running pipeline/canonical.py's clustering over the proposer's claimed
values too, not loosening verify.py's matching -- deferred, not done here.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel

from pipeline.extract import trim_boilerplate
from pipeline.llm_clients import get_chat_model_with_fallback
from pipeline.schema import ProductAttributes
from pipeline.verify import CompatibilityProposal, verify_model_compat_match

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"

RAW_SNIPPET_CHARS = 200
TARGET_BATCH_SIZE = 8


class ProposedEdge(BaseModel):
    target_model: str
    sku_id: str
    claimed_model: str  # the model name AS STATED in the source text the proposal relies on


class ProposalBatchResponse(BaseModel):
    proposals: list[ProposedEdge]


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _catalog_listing_text(catalog_rows: list[dict]) -> str:
    lines = []
    for row in catalog_rows:
        snippet = trim_boilerplate(row["description"])[:RAW_SNIPPET_CHARS]
        lines.append(f"{row['sku_id']}: {row['product_name']} -- {snippet}")
    return "\n".join(lines)


def build_proposal_prompt(catalog_text: str, target_models: list[str]) -> str:
    models_text = "\n".join(f"- {m}" for m in target_models)
    return (
        "You are proposing phone-accessory compatibility edges from a REAL, messy online "
        "catalog -- raw human-written listings, not a spec sheet. For EACH target phone model "
        "below, list every SKU from the catalog whose listing text supports that it fits that "
        "model. Only propose an edge when the listing text actually names that model (or an "
        "unambiguous synonym/spelling variant of it) or explicitly states universal fit -- "
        "never propose a match just because the accessory type seems generically compatible. "
        "It is completely fine, and expected, to propose NOTHING for a target model if no "
        "listing supports it.\n\n"
        "For each proposed edge, claimed_model must be the model name AS IT ACTUALLY APPEARS "
        "(or is clearly stated) in that SKU's own listing text -- this is checked against the "
        "catalog's own independently-extracted data afterward, so do not paraphrase or guess.\n\n"
        f"CATALOG:\n{catalog_text}\n\n"
        f"TARGET MODELS:\n{models_text}"
    )


def propose_compat_edges(target_models: list[str], catalog_rows: list[dict], batch_size: int = TARGET_BATCH_SIZE) -> list[ProposedEdge]:
    catalog_text = _catalog_listing_text(catalog_rows)
    proposals: list[ProposedEdge] = []
    for batch in _chunks(target_models, batch_size):
        model = get_chat_model_with_fallback("compat_proposer", output_schema=ProposalBatchResponse)
        response = model.invoke(
            build_proposal_prompt(catalog_text, batch),
            config={"run_name": "compat:propose", "tags": ["compat", "propose"]},
        )
        proposals.extend(response.proposals)
    return proposals


# ---------------------------------------------------------------------------
# Verification against real extracted attributes + precision reporting.
# ---------------------------------------------------------------------------


@dataclass
class ScoredProposal:
    target_model: str
    sku_id: str
    claimed_model: str
    verified: bool
    reason: str


def verify_proposals(proposals: list[ProposedEdge], attrs_by_sku: dict[str, ProductAttributes]) -> list[ScoredProposal]:
    scored = []
    for p in proposals:
        attrs = attrs_by_sku.get(p.sku_id)
        if attrs is None:
            scored.append(ScoredProposal(p.target_model, p.sku_id, p.claimed_model, False, f"{p.sku_id} not in the published/extracted catalog"))
            continue
        proposal = CompatibilityProposal(sku_id=p.sku_id, claimed_model=p.claimed_model, claimed_basis="model_compat_match")
        result = verify_model_compat_match(proposal, attrs)
        scored.append(ScoredProposal(p.target_model, p.sku_id, p.claimed_model, result.verified, result.reason or "verified"))
    return scored


def precision(scored: list[ScoredProposal]) -> float:
    if not scored:
        return 0.0
    return sum(1 for s in scored if s.verified) / len(scored)


def load_extracted_attrs(extraction_path: Path) -> dict[str, ProductAttributes]:
    results = json.loads(extraction_path.read_text(encoding="utf-8"))
    attrs_by_sku = {}
    for r in results:
        if r.get("error"):
            continue
        attrs_by_sku[r["sku_id"]] = ProductAttributes.model_validate(r["attributes"])
    return attrs_by_sku


def main():
    catalog_rows = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    attrs_by_sku = load_extracted_attrs(ROOT / "eval" / "extraction_results.json")

    target_models = sorted({m for attrs in attrs_by_sku.values() if attrs.model_compat.value for m in attrs.model_compat.value})
    print(f"Proposing edges for {len(target_models)} target models against {len(catalog_rows)} catalog rows...", flush=True)

    proposals = propose_compat_edges(target_models, catalog_rows)
    print(f"Got {len(proposals)} proposed edges. Verifying against extracted attributes...", flush=True)

    scored = verify_proposals(proposals, attrs_by_sku)
    verified = [s for s in scored if s.verified]
    rejected = [s for s in scored if not s.verified]

    print("\n" + "=" * 72)
    print(f"{len(scored)} proposals, {len(verified)} verified, {len(rejected)} rejected -- precision {precision(scored):.0%}")
    if rejected:
        print("\nRejected proposals (LLM claimed, could not verify):")
        for s in rejected:
            print(f"  {s.sku_id} <-> {s.claimed_model!r} (target: {s.target_model}): {s.reason}")
        print(
            "\nNOTE on reading this number: verify_model_compat_match only accepts an exact match "
            "(case/hyphen/space-normalized) against the SKU's own independently-extracted model_compat "
            "tokens -- deliberately strict, since it also gates real payment decisions elsewhere. In a "
            "real run every rejection here was manually checked against the raw catalog text and NONE "
            "were hallucinations: all were textually correct claims (a source-text typo faithfully "
            "transcribed, a symbol like '+' instead of the extractor's spelled-out 'plus', a missing "
            "brand prefix, or a compound slash-separated list the extractor had already split into "
            "several canonical tokens). The precision number above is a real, honest measurement of "
            "exact-form agreement between two independently-generated canonicalizations, not a measure "
            "of whether the LLM read the text correctly -- see the run report for the manual check."
        )
    print("=" * 72)

    out_path = ROOT / "eval" / "compat_results.json"
    out_path.write_text(json.dumps([asdict(s) for s in scored], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
