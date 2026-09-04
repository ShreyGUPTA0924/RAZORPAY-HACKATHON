"""
Deterministic transaction gate -- Tier 1 safety module.

NO LLM IMPORTS IN THIS FILE (see CLAUDE.md).

Pure function: every input arrives as a plain argument -- an already
-verified Intent Mandate + its verification result (surface/mandate.py),
the requested line items, and per-SKU availability facts (published/
in-stock/category/price, computed elsewhere from the catalog +
pipeline/quarantine.py) -- and the output is exactly one of
ALLOW / REFUSE(code) / ESCALATE. No I/O of its own: signature verification,
nonce-replay checks (surface/mandate.py) and idempotency claims
(surface/idempotency.py) all happen BEFORE this is called, not inside it.

Checks run in a fixed order and return on the first failure -- the refusal
you get back is always the first thing that's actually wrong, not
necessarily the "most important" one, which keeps the decision traceable:
given the same inputs, the same code always fires.
"""

from dataclasses import dataclass
from enum import Enum

from surface.mandate import IntentMandate, IntentVerificationResult
from surface.refusal import Refusal, RefusalCode


class GateDecision(str, Enum):
    ALLOW = "allow"
    REFUSE = "refuse"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class SkuAvailability:
    """What the gate needs to know about one requested SKU. Computed
    elsewhere (catalog + pipeline/quarantine.py + inventory) and passed in
    as plain data -- the gate does not look anything up itself."""

    sku_id: str
    published: bool  # False = quarantined/unpublished per pipeline.quarantine.evaluate()
    in_stock: bool
    category: str  # accessory_type value, checked against intent.allowed_categories
    unit_amount: int  # paise


@dataclass(frozen=True)
class RequestedItem:
    sku_id: str
    quantity: int


@dataclass(frozen=True)
class GateResult:
    decision: GateDecision
    refusal: Refusal | None = None  # set iff decision == REFUSE
    escalation_reason: str | None = None  # set iff decision == ESCALATE
    cart_total: int | None = None  # set iff decision in (ALLOW, ESCALATE) -- what gate.py actually computed


# Cart total within this fraction of the ceiling (but not over it) escalates
# rather than auto-allows -- spending nearly the full authorized amount in
# one shot is exactly the kind of borderline case worth a second look
# instead of a silent go-ahead.
ESCALATE_MARGIN_FRACTION = 0.02


def evaluate(
    intent: IntentMandate,
    intent_verification: IntentVerificationResult,
    requested_items: list[RequestedItem],
    skus: dict[str, SkuAvailability],
    previously_spent: int = 0,
) -> GateResult:
    """previously_spent: paise already successfully charged under this same
    intent.intent_mandate_id, across any PRIOR transactions -- a plain int
    the caller fetches from surface/idempotency.py's cumulative-spend
    record before calling evaluate() (gate.py does no I/O of its own, see
    module docstring). Defaults to 0 for a caller that doesn't track it,
    which is exactly the per-transaction-only behavior this parameter is
    additive to -- see the cumulative-ceiling check below and
    docs/what-broke.md for why per-transaction alone isn't enough."""
    if not intent_verification.valid:
        return GateResult(decision=GateDecision.REFUSE, refusal=intent_verification.refusal)

    if not requested_items:
        return GateResult(
            decision=GateDecision.REFUSE,
            refusal=Refusal(code=RefusalCode.INTERNAL_ERROR, detail="empty cart -- nothing requested", context={}),
        )

    for item in requested_items:
        if item.quantity <= 0:
            return GateResult(
                decision=GateDecision.REFUSE,
                refusal=Refusal(
                    code=RefusalCode.INTERNAL_ERROR,
                    detail=f"{item.sku_id}: non-positive quantity {item.quantity}",
                    context={"sku_id": item.sku_id, "quantity": item.quantity},
                ),
            )
        if item.sku_id not in skus:
            return GateResult(
                decision=GateDecision.REFUSE,
                refusal=Refusal(
                    code=RefusalCode.SKU_NOT_PUBLISHED,
                    detail=f"{item.sku_id} unknown to the gate (no availability data provided)",
                    context={"sku_id": item.sku_id},
                ),
            )

    for item in requested_items:
        sku = skus[item.sku_id]
        if not sku.published:
            return GateResult(
                decision=GateDecision.REFUSE,
                refusal=Refusal(
                    code=RefusalCode.SKU_NOT_PUBLISHED,
                    detail=f"{item.sku_id} is quarantined / not published",
                    context={"sku_id": item.sku_id},
                ),
            )

    for item in requested_items:
        sku = skus[item.sku_id]
        if sku.category not in intent.allowed_categories:
            return GateResult(
                decision=GateDecision.REFUSE,
                refusal=Refusal(
                    code=RefusalCode.CATEGORY_NOT_ALLOWED,
                    detail=f"{item.sku_id} category '{sku.category}' not in allowed_categories {intent.allowed_categories}",
                    context={"sku_id": item.sku_id, "category": sku.category, "allowed_categories": intent.allowed_categories},
                ),
            )

    for item in requested_items:
        sku = skus[item.sku_id]
        if not sku.in_stock:
            return GateResult(
                decision=GateDecision.REFUSE,
                refusal=Refusal(code=RefusalCode.OUT_OF_STOCK, detail=f"{item.sku_id} out of stock", context={"sku_id": item.sku_id}),
            )

    total = sum(skus[item.sku_id].unit_amount * item.quantity for item in requested_items)

    if total > intent.max_amount:
        return GateResult(
            decision=GateDecision.REFUSE,
            refusal=Refusal(
                code=RefusalCode.OVER_PRICE_CEILING,
                detail=f"cart total {total} > ceiling {intent.max_amount}",
                context={"total": total, "ceiling": intent.max_amount},
            ),
            cart_total=total,
        )

    cumulative_total = previously_spent + total
    if cumulative_total > intent.max_amount:
        return GateResult(
            decision=GateDecision.REFUSE,
            refusal=Refusal(
                code=RefusalCode.CUMULATIVE_CEILING_EXCEEDED,
                detail=(
                    f"cart total {total} + already-spent {previously_spent} = {cumulative_total} "
                    f"> ceiling {intent.max_amount}, even though this cart alone is under it"
                ),
                context={"total": total, "previously_spent": previously_spent, "cumulative_total": cumulative_total, "ceiling": intent.max_amount},
            ),
            cart_total=total,
        )

    if total >= intent.max_amount * (1 - ESCALATE_MARGIN_FRACTION):
        return GateResult(
            decision=GateDecision.ESCALATE,
            escalation_reason=f"cart total {total} is within {ESCALATE_MARGIN_FRACTION:.0%} of the ceiling {intent.max_amount}",
            cart_total=total,
        )

    return GateResult(decision=GateDecision.ALLOW, cart_total=total)
