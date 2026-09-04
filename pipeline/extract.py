"""
Tier 1 centerpiece: attribute extraction agent.

extract_sku(sku_id, title, description) -> ExtractionResult:
  1. One structured-output call (get_chat_model_with_fallback("extractor"))
     fills a full pipeline.schema.ProductAttributes from title + description.
     Tries every (provider, model) in pipeline.llm_config's fallback chain
     in order -- free-tier quotas are per (provider, model), so exhausting
     one doesn't stop the pipeline.
  2. Self-verification: a second, independent call re-derives ONE attribute
     -- the one the first call was LEAST confident about -- from the same
     source text alone, blind to the first call's answer. Disagreement
     lowers that field's confidence; it never picks a winner between the
     two answers. (Originally targeted the highest-confidence field instead
     -- see _pick_field_to_verify's docstring for why that was backwards
     and produced a 0% quarantine rate.) Always one-SKU-at-a-time, even in
     batch mode -- see the "Batch mode" section below for why.
  3. Every call is traced through LangSmith with sku_id/field tags (see
     pipeline/tracing.py -- configure_tracing() must be called once at
     process start, which run_batch() below does).

run_batch() is the real entrypoint for processing data/catalog.json (or a
subset via --sku-id/--limit) and composes four things to make the free tier
workable at catalog scale:
  - disk cache (pipeline/extract_cache.py): a SKU already extracted under
    the current PROMPT_VERSION + model is never recomputed, so a re-run
    (e.g. demo rehearsal) costs zero quota.
  - batched primary extraction (extract_primary_batch): several SKUs'
    primary calls in one request instead of one each -- see "Batch mode".
  - the fallback chain (see point 1) for every call that isn't cached.
  - token diet (trim_boilerplate): strips generic marketing/warranty
    boilerplate before it goes over the wire. Never applied to what's
    persisted to disk -- data/catalog.json and raw_description stay
    verbatim; this only shrinks what the LLM actually sees.

Never guesses: the system prompt is explicit that value=null + low
confidence beats a plausible-sounding fabrication, and pipeline/quarantine.py
is what actually enforces that downstream by refusing to publish anything
under threshold.
"""

import argparse
import functools
import json
import random
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, create_model
from pydantic import Field as PydanticField

from pipeline import extract_cache
from pipeline.llm_clients import get_chat_model_with_fallback
from pipeline.llm_config import get_component_config
from pipeline.quarantine import evaluate as quarantine_evaluate
from pipeline.schema import ATTRIBUTE_FIELDS, ProductAttributes
from pipeline.tracing import configure_tracing

# Bump whenever a change to the system prompt, batching behavior, or token
# diet could plausibly change what the model returns for the same
# sku_id+description+model -- this is part of the cache key
# (pipeline/extract_cache.py) specifically so such a change correctly
# misses the cache instead of serving a stale pre-change result.
PROMPT_VERSION = "v2-batch-trim-fallback"

# Separate from PROMPT_VERSION: self-verification result (which field got
# checked, agreement, confidence knockdown) is stored bundled with attrs in
# the same cache entry, but which field to check is a decision made
# entirely on our side, not part of what's sent to the LLM -- bumping
# PROMPT_VERSION over a self-verify logic change would force a wasteful
# full primary re-extraction just to get a different field spot-checked.
# This version is compared against what's stored in a cache HIT: a
# mismatch means the attrs are still valid (reuse, zero quota) but the
# self-verification that rode along with them used old logic and must be
# redone -- see run_batch()'s cache-hit handling.
SELF_VERIFY_VERSION = "v2-lowest-confidence"

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
# Token diet -- generic Flipkart marketing/policy boilerplate that carries
# zero product-attribute signal but shows up, verbatim or near-verbatim,
# across a large fraction of descriptions. Trimmed only from what goes over
# the wire to the LLM; data/catalog.json and raw_description on disk are
# never touched -- this is purely a request-cost optimization, not a
# cleaning pass on the source data (Tier 0's "preserve verbatim" rule still
# applies to what's stored).
# ---------------------------------------------------------------------------

BOILERPLATE_PATTERNS = [
    # "Buy X only for Rs. Y from Flipkart.com. Only Genuine Products. 30 Day
    # Replacement Guarantee. Free Shipping. Cash On Delivery!" -- the entire
    # generic marketing sentence, seen verbatim on many listings.
    re.compile(
        r"Buy .*? from Flipkart\.com\.\s*Only Genuine Products\.\s*\d+\s*Day Replacement Guarantee\.\s*"
        r"Free Shipping\.\s*Cash On Delivery!?",
        re.IGNORECASE,
    ),
    # The same clauses, individually, when they appear without the full
    # "Buy ... Flipkart.com" lead-in (e.g. inside a "Key Features" sentence).
    re.compile(r"Only Genuine Products\.?", re.IGNORECASE),
    re.compile(r"\d+\s*Day Replacement Guarantee\.?", re.IGNORECASE),
    re.compile(r"Free Shipping\.?", re.IGNORECASE),
    re.compile(r"Cash On Delivery!?", re.IGNORECASE),
    # Standalone price restatement -- price already lives in catalog.json's
    # own retail_price/discounted_price fields, not needed for attribute
    # extraction.
    re.compile(r"Price:\s*Rs\.?\s*[\d,]+(\.\d+)?", re.IGNORECASE),
    # Warranty boilerplate that sometimes leaks into prose outside the
    # structured spec block (which strip_spec_block already removes wholesale).
    re.compile(r"Not Covered in Warranty", re.IGNORECASE),
    re.compile(r"Covered in Warranty\s*:?\s*\w*", re.IGNORECASE),
    re.compile(r"\d+\s*Days?\s*Brand Warranty", re.IGNORECASE),
    re.compile(r"Domestic Warranty", re.IGNORECASE),
    re.compile(r"International Warranty", re.IGNORECASE),
    re.compile(r"Warranty Summary\s*:?", re.IGNORECASE),
]

WHITESPACE_RUN = re.compile(r"[ \t]{2,}")
BLANK_LINES = re.compile(r"\n{2,}")
STRAY_PUNCTUATION = re.compile(r"\s+([,.])")


def trim_boilerplate(text: str) -> str:
    """Strip generic marketing/policy/warranty boilerplate before it goes
    over the wire. Never applied to anything persisted to disk."""
    for pattern in BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    text = STRAY_PUNCTUATION.sub(r"\1", text)  # e.g. "cable ." left behind by a removed clause
    text = WHITESPACE_RUN.sub(" ", text)
    text = BLANK_LINES.sub("\n", text)
    return text.strip()


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
# Batch mode (B1): N SKUs in one structured-output call instead of one.
# Gemini's free tier limits REQUESTS/day, not tokens, so one call covering
# 8-10 SKUs is worth roughly 8-10x a single-SKU call against that budget.
# Only the PRIMARY extraction call is batched -- self-verification stays
# one-SKU-at-a-time (see run_self_verification), because its whole value is
# genuine independence from the primary call, and batching it would need a
# stringly-typed cross-field response shape that trades exactly the kind of
# quality risk this batching is required to be validated against. Combined
# with the disk cache, self-verification's cost is paid once per SKU ever,
# not once per SKU per run.
#
# Validated, not assumed: re-ran 5 already-extracted SKUs (spanning cable,
# charger, case, screen_protector, headphone) through this batched path at
# batch_size=5, same model, and diffed against their earlier unbatched
# results field-by-field -- 38/40 field comparisons matched exactly. The 2
# that didn't were both on ambiguous/underspecified fields, not evidence of
# cross-SKU contamination: one was model_compat on a SKU whose title says
# "for Android Smart Phone" (arguably a genuinely universal accessory --
# unbatched hedged with value=None conf=0.10, batched called it value=[]
# conf=0.70, which is plausibly the *better* answer per this schema's own
# "empty list means confidently universal" semantics); the other was
# wireless_charging on a wired headphone, where the schema/prompt doesn't
# explicitly say the field only applies to charger/power_bank/case (the
# ground-truth suggester in eval/build_ground_truth.py already encodes that
# gating; the extraction prompt here doesn't yet) -- worth tightening
# independent of batching, since it'd likely reduce this same inconsistency
# in unbatched runs too. No SKU picked up another SKU's connector_type,
# material, or model_compat -- the actual "does information bleed between
# SKUs" failure mode this validation was checking for.
# ---------------------------------------------------------------------------

BATCH_SYSTEM_PROMPT_SUFFIX = """

You will be given MULTIPLE product listings in one request, each labeled with its own sku_id. \
Extract attributes for EACH one independently -- never let information from one listing (brand, \
model, connector, material, etc.) leak into another's answer just because they appeared in the \
same request. Return exactly one result per input sku_id, using the same sku_id string, in any order.
"""


class BatchItem(BaseModel):
    sku_id: str
    attributes: ProductAttributes


class BatchExtractionResponse(BaseModel):
    items: list[BatchItem]


def build_batch_system_prompt() -> str:
    return build_system_prompt() + BATCH_SYSTEM_PROMPT_SUFFIX


def build_batch_user_message(rows: list[tuple[str, str, str]]) -> str:
    """rows: list of (sku_id, title, description)."""
    parts = [f"=== SKU: {sku_id} ===\nTitle: {title}\n\nDescription: {description}" for sku_id, title, description in rows]
    return "\n\n".join(parts)


DEFAULT_BATCH_SIZE = 8


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def extract_primary_batch(rows: list[tuple[str, str, str]], batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, ProductAttributes | None]:
    """Primary extraction only (no self-verification), batch_size SKUs per
    request. rows: list of (sku_id, title, description).

    Returns {sku_id: ProductAttributes}; a SKU missing from the model's
    response maps to None -- a batch-level failure for that SKU, reported
    as an error by the caller, never silently defaulted to empty attributes.
    """
    results: dict[str, ProductAttributes | None] = {}
    chunks = list(_chunks(rows, batch_size))
    for i, chunk in enumerate(chunks):
        sku_ids = [r[0] for r in chunk]
        print(f"  [batch {i + 1}/{len(chunks)}] {sku_ids[0]}..{sku_ids[-1]} ({len(chunk)} SKUs)", flush=True)
        model = get_chat_model_with_fallback("extractor", output_schema=BatchExtractionResponse)
        response = model.invoke(
            [
                ("system", build_batch_system_prompt()),
                ("human", build_batch_user_message(chunk)),
            ],
            config={"run_name": f"extract_batch:{sku_ids[0]}..{sku_ids[-1]}", "tags": ["extraction", "batch", *sku_ids]},
        )
        by_id = {item.sku_id: item.attributes for item in response.items}
        for sku_id in sku_ids:
            results[sku_id] = by_id.get(sku_id)
    return results


# ---------------------------------------------------------------------------
# Extraction + self-verification.
# ---------------------------------------------------------------------------


@dataclass
class FieldCheck:
    field_checked: str
    first_value: Any
    second_value: Any
    agreed: bool
    confidence_before: float
    confidence_after: float


@dataclass
class SelfVerification:
    field_checked: str | None = None
    first_value: Any = None
    second_value: Any = None
    agreed: bool | None = None
    confidence_before: float | None = None
    confidence_after: float | None = None
    # A second, randomly-chosen field check -- see _pick_second_field_to_verify
    # for why this exists: quarantine only fires on accessory_type, and
    # accessory_type is essentially never the LOWEST-confidence field (it's
    # the model's most reliable call by construction), so field_checked
    # above almost never lands on it. Whole-SKU quarantine was structurally
    # unreachable through self-verification alone even after fixing the
    # lowest-vs-highest bug -- a random second check gives every field,
    # including accessory_type, a real chance of being spot-checked.
    extra_check: FieldCheck | None = None


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
    """The non-null field the primary call was LEAST confident about.

    Originally this picked the highest-confidence field, on the theory that
    spot-checking the model's strongest claim was a sharper calibration
    test. That was backwards in practice: a field the model is already very
    sure of gets the same answer on a second independent pass almost every
    time, so disagreement essentially never fires there -- across a real
    60-SKU production run this produced a 0% quarantine rate, which is not
    a believable outcome for free-tier extraction over messy listing text.
    The model's own lowest-confidence non-null field is exactly where a
    second independent read is most likely to genuinely disagree, which is
    the only place self-verification's confidence knockdown can do
    anything -- it's the field most likely to actually be wrong."""
    candidates = [(name, getattr(attrs, name)) for name in ATTRIBUTE_FIELDS]
    candidates = [(name, av) for name, av in candidates if av.value is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[1].confidence)[0]


def _pick_second_field_to_verify(attrs: ProductAttributes, exclude: str) -> str | None:
    """A random non-null field other than `exclude` (the field
    _pick_field_to_verify already picked) -- see SelfVerification.extra_check
    for why a second, randomly-chosen field matters here."""
    candidates = [name for name in ATTRIBUTE_FIELDS if name != exclude and getattr(attrs, name).value is not None]
    if not candidates:
        return None
    return random.choice(candidates)


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
    verify_model = get_chat_model_with_fallback("extractor", output_schema=_verification_schema(field_name))

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


def _run_field_check(sku_id: str, title: str, description: str, attrs: ProductAttributes, field_name: str) -> FieldCheck:
    """Independently re-derives one field and applies the disagreement
    confidence knockdown IN PLACE on attrs. Shared by the primary
    (lowest-confidence) check and the optional second (random) check so
    both apply the exact same comparison and knockdown logic."""
    original = getattr(attrs, field_name)
    second_value = self_verify_field(sku_id, title, description, field_name)
    agreed = _values_match(original.value, second_value)
    confidence_before = original.confidence
    if not agreed:
        original.confidence = round(original.confidence * DISAGREEMENT_CONFIDENCE_FACTOR, 4)
    return FieldCheck(
        field_checked=field_name,
        first_value=original.value,
        second_value=second_value,
        agreed=agreed,
        confidence_before=confidence_before,
        confidence_after=original.confidence,
    )


def run_self_verification(
    sku_id: str, title: str, description: str, attrs: ProductAttributes, verify_second_field: bool = False
) -> SelfVerification:
    field_name = _pick_field_to_verify(attrs)
    if field_name is None:
        return SelfVerification()

    check = _run_field_check(sku_id, title, description, attrs, field_name)
    sv = SelfVerification(
        field_checked=check.field_checked,
        first_value=check.first_value,
        second_value=check.second_value,
        agreed=check.agreed,
        confidence_before=check.confidence_before,
        confidence_after=check.confidence_after,
    )

    if verify_second_field:
        second_field_name = _pick_second_field_to_verify(attrs, exclude=field_name)
        if second_field_name is not None:
            sv.extra_check = _run_field_check(sku_id, title, description, attrs, second_field_name)

    return sv


def add_second_verification(
    sku_id: str, title: str, description: str, attrs: ProductAttributes, sv: SelfVerification
) -> SelfVerification:
    """Upgrades an already-completed primary self_verification to two-field
    mode WITHOUT re-deriving the primary field again -- used when a cached
    result already has a valid lowest-confidence check and only the random
    second check needs to be added, so re-verifying doesn't pay for the
    (already-valid) primary field a second time."""
    if sv.field_checked is None or sv.extra_check is not None:
        return sv
    second_field_name = _pick_second_field_to_verify(attrs, exclude=sv.field_checked)
    if second_field_name is not None:
        sv.extra_check = _run_field_check(sku_id, title, description, attrs, second_field_name)
    return sv


def finish_with_self_verification(
    sku_id: str, title: str, description: str, attrs: ProductAttributes | None, verify_second_field: bool = False
) -> ExtractionResult:
    """Shared tail end of both extraction paths (single-call and batched):
    given the primary call's attributes (or None if it's missing -- e.g. a
    SKU absent from a batch response), run self-verification and wrap the
    result. Used directly by extract_sku() and by the batch orchestrator in
    run_batch()."""
    if attrs is None:
        return ExtractionResult(sku_id=sku_id, attributes=ProductAttributes(), error="no attributes returned (missing from batch response)")
    try:
        sv = run_self_verification(sku_id, title, description, attrs, verify_second_field=verify_second_field)
    except Exception as e:  # noqa: BLE001 -- self-verification failure shouldn't discard a good primary extraction
        return ExtractionResult(sku_id=sku_id, attributes=attrs, error=f"self-verification call failed: {e}")
    return ExtractionResult(sku_id=sku_id, attributes=attrs, self_verification=sv)


def extract_sku(sku_id: str, title: str, description: str, verify_second_field: bool = False) -> ExtractionResult:
    try:
        model = get_chat_model_with_fallback("extractor", output_schema=ProductAttributes)
        attrs = model.invoke(
            [
                ("system", build_system_prompt()),
                ("human", build_user_message(title, description)),
            ],
            config={"run_name": f"extract:{sku_id}", "tags": ["extraction", sku_id]},
        )
    except Exception as e:  # noqa: BLE001 -- batch runner must not die on one bad SKU
        return ExtractionResult(sku_id=sku_id, attributes=ProductAttributes(), error=f"extraction call failed: {e}")

    return finish_with_self_verification(sku_id, title, description, attrs, verify_second_field=verify_second_field)


# ---------------------------------------------------------------------------
# Batch runner against the real catalog.
# ---------------------------------------------------------------------------

PACING_DELAY_S = 1.0  # proactive spacing between SKUs, on top of reactive retry-with-backoff


def _self_verification_from_dict(data: dict) -> SelfVerification:
    extra = data.get("extra_check")
    return SelfVerification(
        field_checked=data.get("field_checked"),
        first_value=data.get("first_value"),
        second_value=data.get("second_value"),
        agreed=data.get("agreed"),
        confidence_before=data.get("confidence_before"),
        confidence_after=data.get("confidence_after"),
        extra_check=FieldCheck(**extra) if extra else None,
    )


def _cache_entry_to_result(sku_id: str, entry: dict) -> ExtractionResult:
    return ExtractionResult(
        sku_id=sku_id,
        attributes=ProductAttributes.model_validate(entry["attributes"]),
        self_verification=_self_verification_from_dict(entry["self_verification"]),
    )


def _result_to_cache_entry(result: ExtractionResult) -> dict:
    return {
        "attributes": result.attributes.model_dump(mode="json"),
        "self_verification": asdict(result.self_verification),
        "self_verify_version": SELF_VERIFY_VERSION,
    }


def _self_verify_stale(entry: dict) -> bool:
    return entry.get("self_verify_version") != SELF_VERIFY_VERSION


def run_batch(
    catalog_path: Path = CATALOG,
    limit: int | None = None,
    sku_ids: list[str] | None = None,
    use_cache: bool = True,
    force: bool = False,
    batching: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    verify_two_fields: bool = False,
) -> list[ExtractionResult]:
    """Runs extraction over data/catalog.json using the FULL raw description
    (trim_boilerplate()'d, but NOT strip_spec_block()'d -- that strip exists
    only to keep the held-out eval leak-free when scoring against ground
    truth derived from the same spec column; it has no reason to apply here.
    Stripping it from every catalog row would starve connector_type/material
    of real signal for no benefit -- there's nothing to leak against when
    the production pipeline just extracts and publishes, it isn't scored.)

    Cache-checks every row first (unless force=True); only SKUs that miss
    the cache actually call an LLM, batched batch_size-at-a-time unless
    batching=False.

    verify_two_fields: also spot-check a random second field per SKU (see
    SelfVerification.extra_check). A cache hit whose primary check is still
    valid but lacks this second check only pays for the ONE additional call,
    not a full re-verification.
    """
    configure_tracing()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if sku_ids:
        catalog = [row for row in catalog if row["sku_id"] in sku_ids]
    if limit:
        catalog = catalog[:limit]

    model_name = get_component_config("extractor").model  # cache key uses the configured primary model, even if a fallback ends up serving a given call
    results: dict[str, ExtractionResult] = {}
    to_process: list[tuple[dict, str, str]] = []  # (row, trimmed_description, cache_key) -- full primary extraction needed
    to_reverify: list[tuple[dict, str, str]] = []  # cached attrs are still valid, but self-verification used stale logic
    to_add_second: list[tuple[dict, str, str]] = []  # primary check valid, only the second/random check is missing

    for row in catalog:
        description = trim_boilerplate(row["description"])
        key = extract_cache.cache_key(row["sku_id"], description, PROMPT_VERSION, model_name)
        cached = None if force else (extract_cache.get(key) if use_cache else None)
        if cached is None:
            to_process.append((row, description, key))
        elif _self_verify_stale(cached):
            to_reverify.append((row, description, key))
            results[row["sku_id"]] = _cache_entry_to_result(row["sku_id"], cached)  # placeholder, overwritten below
        elif verify_two_fields and not cached.get("self_verification", {}).get("extra_check"):
            to_add_second.append((row, description, key))
            results[row["sku_id"]] = _cache_entry_to_result(row["sku_id"], cached)  # placeholder, overwritten below
        else:
            results[row["sku_id"]] = _cache_entry_to_result(row["sku_id"], cached)

    fully_cached = len(catalog) - len(to_process) - len(to_reverify) - len(to_add_second)
    if fully_cached:
        print(f"{fully_cached}/{len(catalog)} SKUs served from cache (zero quota spent)", flush=True)
    if to_reverify:
        print(
            f"{len(to_reverify)}/{len(catalog)} SKUs have valid cached attrs but stale self-verification "
            f"(logic changed since cached) -- re-verifying only, no primary extraction spent",
            flush=True,
        )
    if to_add_second:
        print(
            f"{len(to_add_second)}/{len(catalog)} SKUs have a valid primary check but no second-field check yet "
            f"-- adding only the second check, primary check not re-spent",
            flush=True,
        )
    print(f"{len(to_process)}/{len(catalog)} SKUs to extract", flush=True)

    if batching and to_process:
        batch_rows = [(row["sku_id"], row["product_name"], description) for row, description, _ in to_process]
        print(
            f"  batching {len(batch_rows)} SKUs, {batch_size} per request "
            f"({-(-len(batch_rows) // batch_size)} requests instead of {len(batch_rows)})",
            flush=True,
        )
        primary = extract_primary_batch(batch_rows, batch_size=batch_size)
        print(f"  primary batch extraction done -- running self-verification on {len(to_process)} SKUs (1 call each)", flush=True)
        for i, (row, description, key) in enumerate(to_process):
            sku_id = row["sku_id"]
            print(f"  [self-verify {i + 1}/{len(to_process)}] {sku_id}", flush=True)
            result = finish_with_self_verification(
                sku_id, row["product_name"], description, primary.get(sku_id), verify_second_field=verify_two_fields
            )
            if result.error:
                print(f"    ERROR {sku_id}: {result.error}", flush=True)
            results[sku_id] = result
            if use_cache and not result.error:
                extract_cache.put(key, _result_to_cache_entry(result))
    else:
        for i, (row, description, key) in enumerate(to_process):
            print(f"[{i + 1}/{len(to_process)}] {row['sku_id']}: {row['product_name'][:60]}", flush=True)
            result = extract_sku(row["sku_id"], row["product_name"], description, verify_second_field=verify_two_fields)
            if result.error:
                print(f"    ERROR: {result.error}", flush=True)
            results[row["sku_id"]] = result
            if use_cache and not result.error:
                extract_cache.put(key, _result_to_cache_entry(result))
            if i < len(to_process) - 1:
                time.sleep(PACING_DELAY_S)

    for i, (row, description, key) in enumerate(to_reverify):
        sku_id = row["sku_id"]
        print(f"  [re-verify {i + 1}/{len(to_reverify)}] {sku_id}", flush=True)
        cached_attrs = results[sku_id].attributes  # trusted, unchanged -- only self_verification is being redone
        result = finish_with_self_verification(
            sku_id, row["product_name"], description, cached_attrs, verify_second_field=verify_two_fields
        )
        if result.error:
            print(f"    ERROR {sku_id}: {result.error}", flush=True)
            continue  # keep the stale-but-valid-attrs cached result rather than losing it
        results[sku_id] = result
        if use_cache:
            extract_cache.put(key, _result_to_cache_entry(result))

    for i, (row, description, key) in enumerate(to_add_second):
        sku_id = row["sku_id"]
        print(f"  [add-second-check {i + 1}/{len(to_add_second)}] {sku_id}", flush=True)
        cached_result = results[sku_id]
        try:
            sv = add_second_verification(
                sku_id, row["product_name"], description, cached_result.attributes, cached_result.self_verification
            )
        except Exception as e:  # noqa: BLE001 -- keep the still-valid primary check rather than losing it
            print(f"    ERROR {sku_id}: second-field verification failed: {e}", flush=True)
            continue
        result = ExtractionResult(sku_id=sku_id, attributes=cached_result.attributes, self_verification=sv)
        results[sku_id] = result
        if use_cache:
            extract_cache.put(key, _result_to_cache_entry(result))

    return [results[row["sku_id"]] for row in catalog]  # preserve catalog order


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
        print(f"\nSelf-verification (primary, lowest-confidence field): checked on {len(verified)}/{len(ok)} SKUs, disagreed on {len(disagreements)}")
        if disagreements:
            by_field: dict[str, int] = {}
            for r in disagreements:
                by_field[r.self_verification.field_checked] = by_field.get(r.self_verification.field_checked, 0) + 1
            print(f"  Disagreements by field: {by_field}")

    second_checked = [r for r in ok if r.self_verification.extra_check]
    second_disagreements = [r for r in second_checked if r.self_verification.extra_check.agreed is False]
    if second_checked:
        print(f"\nSelf-verification (second, random field): checked on {len(second_checked)}/{len(ok)} SKUs, disagreed on {len(second_disagreements)}")
        if second_disagreements:
            by_field = {}
            for r in second_disagreements:
                fname = r.self_verification.extra_check.field_checked
                by_field[fname] = by_field.get(fname, 0) + 1
            print(f"  Disagreements by field: {by_field}")

    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N catalog rows.")
    parser.add_argument("--sku-id", action="append", dest="sku_ids", help="Only process specific SKU id(s). Repeatable.")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "extraction_results.json")
    parser.add_argument("--no-cache", action="store_true", help="Don't read or write the disk cache.")
    parser.add_argument("--force", action="store_true", help="Ignore cache hits and re-extract every requested SKU.")
    parser.add_argument("--no-batch", action="store_true", help="Disable batched primary extraction; one call per SKU.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--verify-two-fields",
        action="store_true",
        help=(
            "Also spot-check a random second field per SKU, in addition to the "
            "lowest-confidence one. Whole-SKU quarantine only fires on "
            "accessory_type, which is essentially never the lowest-confidence "
            "field -- use this if a run comes back with a suspiciously low "
            "quarantine rate despite real self-verification disagreements."
        ),
    )
    args = parser.parse_args()
    out_path = args.out.resolve()

    results = run_batch(
        limit=args.limit,
        sku_ids=args.sku_ids,
        use_cache=not args.no_cache,
        force=args.force,
        batching=not args.no_batch,
        batch_size=args.batch_size,
        verify_two_fields=args.verify_two_fields,
    )
    decisions = {r.sku_id: quarantine_evaluate(r.sku_id, r.attributes) for r in results if not r.error}

    output = [_result_to_dict(r, decisions.get(r.sku_id)) for r in results]
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(output)} results to {out_path}")

    print_report(results, decisions)


if __name__ == "__main__":
    main()
