import pytest

from surface.gate import (
    ESCALATE_MARGIN_FRACTION,
    GateDecision,
    RequestedItem,
    SkuAvailability,
    evaluate,
)
from surface.mandate import IntentMandate, IntentVerificationResult
from surface.refusal import Refusal, RefusalCode


def make_intent(**overrides) -> IntentMandate:
    defaults = {
        "intent_mandate_id": "intent-1",
        "buyer_agent_id": "agent-1",
        "buyer_public_key_hex": "00" * 32,
        "max_amount": 10_000,
        "allowed_categories": ["case", "screen_protector"],
        "expiry": 9_999_999_999,
        "nonce": "n1",
        "signature_hex": "ab" * 64,
    }
    defaults.update(overrides)
    return IntentMandate(**defaults)


VALID = IntentVerificationResult(valid=True)


def make_sku(sku_id="SKU-1", published=True, in_stock=True, category="case", unit_amount=1_000) -> SkuAvailability:
    return SkuAvailability(sku_id=sku_id, published=published, in_stock=in_stock, category=category, unit_amount=unit_amount)


ITEM = RequestedItem(sku_id="SKU-1", quantity=1)


def test_refuses_on_invalid_intent_verification_passthrough():
    refusal = Refusal(code=RefusalCode.INVALID_SIGNATURE, detail="bad sig")
    result = evaluate(make_intent(), IntentVerificationResult(valid=False, refusal=refusal), [ITEM], {"SKU-1": make_sku()})
    assert result.decision is GateDecision.REFUSE
    assert result.refusal is refusal  # passed through unchanged, not re-derived


def test_refuses_empty_cart():
    result = evaluate(make_intent(), VALID, [], {"SKU-1": make_sku()})
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.INTERNAL_ERROR


@pytest.mark.parametrize("quantity", [0, -1, -100])
def test_refuses_non_positive_quantity(quantity):
    result = evaluate(make_intent(), VALID, [RequestedItem(sku_id="SKU-1", quantity=quantity)], {"SKU-1": make_sku()})
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.INTERNAL_ERROR


def test_refuses_unknown_sku_not_in_availability_data():
    result = evaluate(make_intent(), VALID, [ITEM], {})
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.SKU_NOT_PUBLISHED


def test_refuses_quarantined_sku():
    result = evaluate(make_intent(), VALID, [ITEM], {"SKU-1": make_sku(published=False)})
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.SKU_NOT_PUBLISHED


def test_refuses_category_outside_allowed_scope():
    result = evaluate(
        make_intent(allowed_categories=["case"]), VALID, [ITEM], {"SKU-1": make_sku(category="charger")}
    )
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.CATEGORY_NOT_ALLOWED


def test_refuses_out_of_stock():
    result = evaluate(make_intent(), VALID, [ITEM], {"SKU-1": make_sku(in_stock=False)})
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.OUT_OF_STOCK


def test_refuses_over_price_ceiling():
    result = evaluate(make_intent(max_amount=500), VALID, [ITEM], {"SKU-1": make_sku(unit_amount=1_000)})
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.OVER_PRICE_CEILING
    assert result.cart_total == 1_000


def test_escalates_when_total_within_margin_of_ceiling():
    ceiling = 10_000
    total = int(ceiling * (1 - ESCALATE_MARGIN_FRACTION / 2))  # inside the margin, under the ceiling
    result = evaluate(make_intent(max_amount=ceiling), VALID, [ITEM], {"SKU-1": make_sku(unit_amount=total)})
    assert result.decision is GateDecision.ESCALATE
    assert result.cart_total == total


def test_escalates_when_total_exactly_equals_ceiling():
    ceiling = 10_000
    result = evaluate(make_intent(max_amount=ceiling), VALID, [ITEM], {"SKU-1": make_sku(unit_amount=ceiling)})
    assert result.decision is GateDecision.ESCALATE  # not a silent ALLOW just because it's not OVER


def test_allows_comfortably_under_ceiling():
    result = evaluate(make_intent(max_amount=10_000), VALID, [ITEM], {"SKU-1": make_sku(unit_amount=100)})
    assert result.decision is GateDecision.ALLOW
    assert result.refusal is None
    assert result.escalation_reason is None
    assert result.cart_total == 100


def test_multi_item_cart_sums_total_correctly():
    items = [RequestedItem(sku_id="SKU-1", quantity=2), RequestedItem(sku_id="SKU-2", quantity=3)]
    skus = {"SKU-1": make_sku("SKU-1", unit_amount=100), "SKU-2": make_sku("SKU-2", unit_amount=50)}
    result = evaluate(make_intent(max_amount=10_000), VALID, items, skus)
    assert result.decision is GateDecision.ALLOW
    assert result.cart_total == 2 * 100 + 3 * 50


def test_multi_item_cart_second_item_failure_is_still_caught():
    """A failure isn't only checked on the first item -- every item in the
    cart gets every check."""
    items = [RequestedItem(sku_id="SKU-1", quantity=1), RequestedItem(sku_id="SKU-2", quantity=1)]
    skus = {"SKU-1": make_sku("SKU-1"), "SKU-2": make_sku("SKU-2", in_stock=False)}
    result = evaluate(make_intent(), VALID, items, skus)
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.OUT_OF_STOCK
    assert result.refusal.context["sku_id"] == "SKU-2"


def test_checks_run_in_documented_order_sku_not_published_before_category():
    """A SKU that's both quarantined AND outside allowed_categories should
    surface as SKU_NOT_PUBLISHED (checked first), not CATEGORY_NOT_ALLOWED --
    documents which check wins, since callers may reasonably assume order."""
    sku = make_sku(published=False, category="not_allowed_category")
    result = evaluate(make_intent(allowed_categories=["case"]), VALID, [ITEM], {"SKU-1": sku})
    assert result.refusal.code is RefusalCode.SKU_NOT_PUBLISHED
