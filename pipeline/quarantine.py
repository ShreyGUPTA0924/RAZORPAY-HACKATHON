"""
Deterministic confidence gate -- Tier 1.

NO LLM IMPORTS IN THIS FILE. This is a non-negotiable architectural rule
(see CLAUDE.md): pipeline/extract.py proposes attribute values with
confidence; this module decides what's safe to publish using nothing but
that confidence, deterministically.

"Fail closed, never open" applies per attribute, not just per SKU: any
field whose confidence falls below CONFIDENCE_THRESHOLD is redacted --
treated as unpublished, regardless of what value the LLM proposed for it.
A SKU can still be published with some fields redacted.

accessory_type is different: it's the one field pipeline/schema.py's own
docstring says "gates which other fields are expected." If we don't
confidently know what kind of product this is, nothing else about it is
safe to expose either -- so a SKU is quarantined outright (not
agent-purchasable at all) when accessory_type is missing or below
threshold, independent of how confident every other field is.
"""

from dataclasses import dataclass, field

from pipeline.schema import ATTRIBUTE_FIELDS, ProductAttributes

CONFIDENCE_THRESHOLD = 0.5


@dataclass
class QuarantineDecision:
    sku_id: str
    published: bool  # False = whole SKU quarantined, not agent-purchasable
    redacted_fields: list[str] = field(default_factory=list)  # fields hidden even if published
    reasons: list[str] = field(default_factory=list)  # human-readable, one per redaction/quarantine cause


def evaluate(sku_id: str, attrs: ProductAttributes, threshold: float = CONFIDENCE_THRESHOLD) -> QuarantineDecision:
    redacted: list[str] = []
    reasons: list[str] = []

    for field_name in ATTRIBUTE_FIELDS:
        attr_value = getattr(attrs, field_name)
        if attr_value.value is not None and attr_value.confidence < threshold:
            redacted.append(field_name)
            reasons.append(
                f"{field_name}: confidence {attr_value.confidence:.2f} < {threshold} "
                f"(proposed {attr_value.value!r}, not published)"
            )

    gate_field = attrs.accessory_type
    sku_quarantined = gate_field.value is None or gate_field.confidence < threshold
    if sku_quarantined:
        reason = (
            "accessory_type is null" if gate_field.value is None else f"accessory_type confidence {gate_field.confidence:.2f} < {threshold}"
        )
        reasons.insert(0, f"SKU quarantined: {reason} -- accessory_type gates every other field, nothing is safe to publish")

    return QuarantineDecision(
        sku_id=sku_id,
        published=not sku_quarantined,
        redacted_fields=redacted,
        reasons=reasons,
    )


def redact(attrs: ProductAttributes, decision: QuarantineDecision) -> ProductAttributes:
    """Return a copy of attrs with quarantined/redacted fields nulled out --
    what actually gets surfaced to a buyer agent, as opposed to what the
    extractor internally proposed."""
    if not decision.published:
        return ProductAttributes()  # whole SKU withheld: nothing published

    published = attrs.model_copy(deep=True)
    for field_name in decision.redacted_fields:
        setattr(published, field_name, type(getattr(published, field_name))())
    return published
