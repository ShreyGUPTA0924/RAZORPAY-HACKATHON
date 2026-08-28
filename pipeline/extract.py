"""
Tier 1 centerpiece: attribute extraction agent.

extract_sku(sku_id, title, description) -> ExtractionResult:
  1. One structured-output Gemini call (get_chat_model("extractor")) fills a
     full pipeline.schema.ProductAttributes from title + description.
  2. Self-verification: a second, independent call re-derives ONE attribute
     -- the one the first call was most confident about -- from the same
     source text alone, blind to the first call's answer. Disagreement
     lowers that field's confidence; it never picks a winner between the
     two answers. Spot-checking the model's most confident claim is the
     more useful test of calibration than spot-checking a field it already
     flagged as uncertain.
  3. Every call is traced through LangSmith with sku_id/field tags (see
     pipeline/tracing.py -- configure_tracing() must be called once at
     process start, which run_batch() below does).

Never guesses: the system prompt is explicit that value=null + low
confidence beats a plausible-sounding fabrication, and pipeline/quarantine.py
is what actually enforces that downstream by refusing to publish anything
under threshold.
"""

import argparse
import functools
import json
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, create_model
from pydantic import Field as PydanticField

from pipeline.llm_clients import get_chat_model
from pipeline.quarantine import evaluate as quarantine_evaluate
from pipeline.schema import ATTRIBUTE_FIELDS, ProductAttributes
from pipeline.tracing import configure_tracing

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog.json"

# ---------------------------------------------------------------------------
# Split hygiene -- canonical home. eval/build_ground_truth.py imports these
# from here (not the other way around): stripping the seller's own spec
# table out of what the extractor sees is pipeline behavior the eval harness
# depends on, not the reverse.
# ---------------------------------------------------------------------------

SPEC_BLOCK_MARKER = re.compile(r"specifications of", re.IGNORECASE)


def strip_spec_block(description: str) -> str:
    match = SPEC_BLOCK_MARKER.search(description)
    return description[: match.start()].strip() if match else description


# ---------------------------------------------------------------------------
# Prompt construction -- field descriptions/enums are pulled from
# pipeline.schema at import time, so the prompt can't drift from the actual
# contract the way a hand-copied description would.
# ---------------------------------------------------------------------------


def _value_type_for(field_name: str) -> type:
    """Recover the concrete T from a field typed AttrValue[T]. Pydantic v2
    materializes each parameterization into a real class (not a typing
    generic alias), so typing.get_args() finds nothing on it -- the type
    argument lives in __pydantic_generic_metadata__ instead."""
    annotation = ProductAttributes.model_fields[field_name].annotation
    return annotation.__pydantic_generic_metadata__["args"][0]


FIELD_VALUE_TYPES: dict[str, type] = {name: _value_type_for(name) for name in ATTRIBUTE_FIELDS}


def _field_prompt_line(field_name: str) -> str:
    info = ProductAttributes.model_fields[field_name]
    value_type = FIELD_VALUE_TYPES[field_name]
    line = f"- {field_name}: {info.description}"
    if isinstance(value_type, type) and issubclass(value_type, Enum):
        allowed = ", ".join(v.value for v in value_type)
        line += f" Allowed values: {allowed}."
    return line


SYSTEM_PROMPT = """You are an attribute extraction agent for a phone-accessories e-commerce \
catalog (cases, pouches, screen protectors, cables, chargers, headphones, power banks).

Given a raw product title and description written by a marketplace seller -- often messy, \
inconsistent, abbreviated, or containing typos -- extract the structured attributes listed \
below. The text may bury a fact in unrelated marketing copy, restate it inconsistently, or \
never mention it at all.

Rules, in order of importance:
1. Only use information stated or very strongly and unambiguously implied by the title/description \
given to you. Never use outside knowledge about a brand or product line to fill a gap the text \
itself does not support.
2. If a field cannot be confidently determined from the given text, set its value to null and its \
confidence to 0.0-0.2. A plausible-sounding guess is worse than an honest null -- this catalog \
would rather quarantine a SKU than publish a wrong attribute.
3. confidence reflects how directly the text supports the value: ~1.0 = stated close to verbatim, \
~0.5-0.7 = reasonably inferred from context, <=0.2 = not supported / a guess you correctly avoided.
4. For model_compat specifically: an empty list is a valid, CONFIDENT answer when the text says the \
accessory fits any/all phones -- that is different from null, which means compatibility isn't \
stated at all.

Fields to extract:
{field_lines}
"""


def build_system_prompt() -> str:
    lines = "\n".join(_field_prompt_line(f) for f in ATTRIBUTE_FIELDS)
    return SYSTEM_PROMPT.format(field_lines=lines)


def build_user_message(title: str, description: str) -> str:
    return f"Title: {title}\n\nDescription: {description}"


# ---------------------------------------------------------------------------
# Extraction + self-verification.
# ---------------------------------------------------------------------------


@dataclass
class SelfVerification:
    field_checked: str | None = None
    first_value: Any = None
    second_value: Any = None
    agreed: bool | None = None
    confidence_before: float | None = None
    confidence_after: float | None = None


@dataclass
class ExtractionResult:
    sku_id: str
    attributes: ProductAttributes
    self_verification: SelfVerification = field(default_factory=SelfVerification)
    error: str | None = None


DISAGREEMENT_CONFIDENCE_FACTOR = 0.4


def _values_match(a: Any, b: Any) -> bool:
    def norm(v):
        if isinstance(v, str):
            return v.strip().lower()
        if isinstance(v, list):
            return frozenset(norm(x) for x in v)
        if isinstance(v, Enum):
            return v.value
        return v

    return norm(a) == norm(b)


def _pick_field_to_verify(attrs: ProductAttributes) -> str | None:
    """The non-null field the primary call was most confident about --
    spot-checking the model's strongest claim is a sharper calibration test
    than spot-checking one it already flagged as uncertain."""
    candidates = [(name, getattr(attrs, name)) for name in ATTRIBUTE_FIELDS]
    candidates = [(name, av) for name, av in candidates if av.value is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[1].confidence)[0]


@functools.cache
def _verification_schema(field_name: str) -> type[BaseModel]:
    """A concretely-named single-field schema for the self-verification
    call, built with create_model() rather than parameterizing the generic
    AttrValue[T] from pipeline.schema. Pydantic v2 materializes each
    AttrValue[T] into its own class, but that class's name doesn't round-trip
    reliably through every provider's tool-calling API -- confirmed: it
    breaks on Groq ("attempted to call tool 'AttrValue' which was not in
    request.tools") while working fine on Gemini. A plain create_model()
    class with an explicit name avoids the whole category of issue and
    works identically across providers, which matters here since extractor
    is exactly the component pipeline/llm_config.py expects to move between
    providers (e.g. a quota contingency)."""
    value_type = FIELD_VALUE_TYPES[field_name]
    class_name = "Verify" + "".join(part.title() for part in field_name.split("_"))
    return create_model(
        class_name,
        value=(value_type | None, None),
        confidence=(float, PydanticField(default=0.0, ge=0.0, le=1.0)),
    )


def self_verify_field(sku_id: str, title: str, description: str, field_name: str) -> Any:
    """Independently re-derive ONE field's value from source text alone,
    blind to whatever the primary extraction call already produced."""
    value_type = FIELD_VALUE_TYPES[field_name]
    schema_field = ProductAttributes.model_fields[field_name]
    verify_model = get_chat_model("extractor", output_schema=_verification_schema(field_name))

    prompt = (
        f"From the product listing below, determine only this one attribute: {field_name}.\n"
        f"{schema_field.description}\n"
    )
    if isinstance(value_type, type) and issubclass(value_type, Enum):
        prompt += f"Allowed values: {', '.join(v.value for v in value_type)}.\n"
    prompt += (
        "If it cannot be confidently determined from the text, return value=null and a low confidence.\n\n"
        + build_user_message(title, description)
    )

    result = verify_model.invoke(
        prompt,
        config={"run_name": f"self_verify:{sku_id}:{field_name}", "tags": ["self_verification", sku_id, field_name]},
    )
    return result.value


def run_self_verification(sku_id: str, title: str, description: str, attrs: ProductAttributes) -> SelfVerification:
    field_name = _pick_field_to_verify(attrs)
    if field_name is None:
        return SelfVerification()

    original = getattr(attrs, field_name)
    second_value = self_verify_field(sku_id, title, description, field_name)
    agreed = _values_match(original.value, second_value)

    sv = SelfVerification(
        field_checked=field_name,
        first_value=original.value,
        second_value=second_value,
        agreed=agreed,
        confidence_before=original.confidence,
    )

    if not agreed:
        original.confidence = round(original.confidence * DISAGREEMENT_CONFIDENCE_FACTOR, 4)
    sv.confidence_after = original.confidence
    return sv


def extract_sku(sku_id: str, title: str, description: str) -> ExtractionResult:
    try:
        model = get_chat_model("extractor", output_schema=ProductAttributes)
        attrs = model.invoke(
            [
                ("system", build_system_prompt()),
                ("human", build_user_message(title, description)),
            ],
            config={"run_name": f"extract:{sku_id}", "tags": ["extraction", sku_id]},
        )
    except Exception as e:  # noqa: BLE001 -- batch runner must not die on one bad SKU
        return ExtractionResult(sku_id=sku_id, attributes=ProductAttributes(), error=f"extraction call failed: {e}")

    try:
        sv = run_self_verification(sku_id, title, description, attrs)
    except Exception as e:  # noqa: BLE001 -- self-verification failure shouldn't discard a good primary extraction
        return ExtractionResult(sku_id=sku_id, attributes=attrs, error=f"self-verification call failed: {e}")

    return ExtractionResult(sku_id=sku_id, attributes=attrs, self_verification=sv)


# ---------------------------------------------------------------------------
# Batch runner against the real catalog.
# ---------------------------------------------------------------------------

PACING_DELAY_S = 1.0  # proactive spacing between SKUs, on top of reactive retry-with-backoff


def run_batch(catalog_path: Path = CATALOG, limit: int | None = None, sku_ids: list[str] | None = None) -> list[ExtractionResult]:
    """Runs extraction over data/catalog.json using the FULL raw description
    -- deliberately not strip_spec_block()'d. That strip exists only to keep
    the held-out eval leak-free when scoring against ground truth derived
    from the same spec column (see eval/build_ground_truth.py's
    extractor_eval_description); it has no reason to apply here. Stripping
    it from every catalog row starves connector_type/material of real
    signal for no benefit -- there's nothing to leak against when the
    production pipeline just extracts and publishes, it isn't being scored.
    """
    configure_tracing()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if sku_ids:
        catalog = [row for row in catalog if row["sku_id"] in sku_ids]
    if limit:
        catalog = catalog[:limit]

    results = []
    for i, row in enumerate(catalog):
        title = row["product_name"]
        description = row["description"]
        print(f"[{i + 1}/{len(catalog)}] {row['sku_id']}: {title[:60]}")
        result = extract_sku(row["sku_id"], title, description)
        if result.error:
            print(f"    ERROR: {result.error}")
        results.append(result)
        if i < len(catalog) - 1:
            time.sleep(PACING_DELAY_S)
    return results


def _result_to_dict(result: ExtractionResult, decision) -> dict:
    return {
        "sku_id": result.sku_id,
        "error": result.error,
        "attributes": result.attributes.model_dump(mode="json"),
        "self_verification": asdict(result.self_verification),
        "quarantine": asdict(decision) if decision else None,
    }


def print_report(results: list[ExtractionResult], decisions: dict[str, Any]) -> None:
    errored = [r for r in results if r.error]
    ok = [r for r in results if not r.error]
    quarantined = [r for r in ok if not decisions[r.sku_id].published]
    clean = [r for r in ok if decisions[r.sku_id].published]

    print("\n" + "=" * 72)
    print(f"{len(clean)} published clean / {len(quarantined)} quarantined / {len(errored)} extraction errors (of {len(results)})")

    if quarantined:
        print("\nQuarantined SKUs:")
        for r in quarantined:
            print(f"  {r.sku_id}: {decisions[r.sku_id].reasons[0]}")

    if errored:
        print("\nExtraction errors:")
        for r in errored:
            print(f"  {r.sku_id}: {r.error}")

    # Systematic patterns: which fields go null / get redacted across the
    # WHOLE batch, not just individual rows -- this is what actually tells
    # you if the extractor (or the prompt, or the source data) has a
    # structural gap, as opposed to one row being unusually messy.
    null_counts = dict.fromkeys(ATTRIBUTE_FIELDS, 0)
    redacted_counts = dict.fromkeys(ATTRIBUTE_FIELDS, 0)
    for r in ok:
        for field_name in ATTRIBUTE_FIELDS:
            if getattr(r.attributes, field_name).value is None:
                null_counts[field_name] += 1
        for field_name in decisions[r.sku_id].redacted_fields:
            redacted_counts[field_name] += 1

    if ok:
        print(f"\nPer-field null rate (extractor found nothing), out of {len(ok)} extracted SKUs:")
        for field_name in ATTRIBUTE_FIELDS:
            pct = 100 * null_counts[field_name] / len(ok)
            print(f"  {field_name:<20} {null_counts[field_name]:>3}/{len(ok)}  ({pct:.0f}%)")

        redacted_total = sum(redacted_counts.values())
        if redacted_total:
            print("\nRedacted-for-low-confidence, by field:")
            for field_name, n in redacted_counts.items():
                if n:
                    print(f"  {field_name}: {n}")

    verified = [r for r in ok if r.self_verification.field_checked]
    disagreements = [r for r in verified if r.self_verification.agreed is False]
    if verified:
        print(f"\nSelf-verification: checked on {len(verified)}/{len(ok)} SKUs, disagreed on {len(disagreements)}")
        if disagreements:
            by_field: dict[str, int] = {}
            for r in disagreements:
                by_field[r.self_verification.field_checked] = by_field.get(r.self_verification.field_checked, 0) + 1
            print(f"  Disagreements by field: {by_field}")

    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N catalog rows.")
    parser.add_argument("--sku-id", action="append", dest="sku_ids", help="Only process specific SKU id(s). Repeatable.")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "extraction_results.json")
    args = parser.parse_args()
    out_path = args.out.resolve()

    results = run_batch(limit=args.limit, sku_ids=args.sku_ids)
    decisions = {r.sku_id: quarantine_evaluate(r.sku_id, r.attributes) for r in results if not r.error}

    output = [_result_to_dict(r, decisions.get(r.sku_id)) for r in results]
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(output)} results to {out_path}")

    print_report(results, decisions)


if __name__ == "__main__":
    main()
