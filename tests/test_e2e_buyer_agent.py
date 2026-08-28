"""
Headless end-to-end test: a scripted buyer agent walks the full AP2
mandate chain against the real surface stack -- real Redis, real Ed25519
crypto, real deterministic gate logic -- with a synthetic catalog. No LLM
call anywhere in this file, by design: this proves the SURFACE (mandate
verify -> gate -> cart issue -> payment -> receipt), not the extraction
pipeline, which is exactly what "needs zero LLM quota" means here.

Razorpay itself is faked in this file (a scripted client, not the real
API) so the E2E flow is fast, deterministic, and doesn't depend on network
availability or a completed browser checkout -- real Razorpay connectivity
is separately proven by scripts/razorpay_smoke.py and
tests/test_payments.py's live order-creation test. What this file actually
verifies is the ORCHESTRATION: that mandate verification, the gate,
idempotency, and payment execution compose correctly and refuse for the
right reasons.

Scenarios covered:
  - happy path: search -> get_product -> create Cart Mandate -> pay -> receipt
  - REFUSE: over price ceiling
  - REFUSE: expired mandate
  - REFUSE: replayed nonce (mandate-level)
  - REFUSE: category out of scope
  - retry storm hitting the PAYMENT-level idempotency guard specifically --
    a different layer from mandate-level nonce replay (see the docstring on
    test_retry_storm_only_one_payment_executes for why both exist).
"""

import time

import nacl.signing
import pytest

from surface.gate import GateDecision, GateResult, RequestedItem, SkuAvailability
from surface.gate import evaluate as gate_evaluate
from surface.idempotency import cart_hash, claim, record_receipt
from surface.mandate import (
    CartLineItem,
    IntentMandate,
    _signable_payload,
    issue_cart_mandate,
    sign_payload,
    verify_intent_mandate,
)
from surface.payments import ReconciliationError, execute_payment_behind_gate
from surface.refusal import RefusalCode

REDIS_URL = "redis://localhost:6379/0"

# ---------------------------------------------------------------------------
# Synthetic catalog + a fake Razorpay client -- see module docstring for why.
# ---------------------------------------------------------------------------

CATALOG: dict[str, SkuAvailability] = {
    "SKU-CASE": SkuAvailability(sku_id="SKU-CASE", published=True, in_stock=True, category="case", unit_amount=59_900),
    "SKU-SCREEN": SkuAvailability(sku_id="SKU-SCREEN", published=True, in_stock=True, category="screen_protector", unit_amount=29_900),
    "SKU-CHARGER": SkuAvailability(sku_id="SKU-CHARGER", published=True, in_stock=True, category="charger", unit_amount=149_900),
}


class _FakeOrders:
    def __init__(self):
        self.created = []

    def create(self, data):
        order_id = f"order_fake_{len(self.created)}"
        self.created.append(data)
        return {"id": order_id, "amount": data["amount"], "currency": data["currency"], "status": "created"}

    def fetch(self, order_id):
        for i, data in enumerate(self.created):
            if f"order_fake_{i}" == order_id:
                return {"id": order_id, "amount": data["amount"], "currency": data["currency"], "status": "created"}
        raise ValueError(f"no such fake order {order_id}")


class _FakePayments:
    def capture(self, payment_id, amount, data):
        return {"id": payment_id, "amount": amount, "currency": data["currency"], "status": "captured"}


class _FakeRazorpayClient:
    def __init__(self):
        self.order = _FakeOrders()
        self.payment = _FakePayments()


class ScriptedBuyerAgent:
    """A buyer agent that holds its own keypair and can produce signed
    Intent Mandates on demand -- stands in for a real AP2 buyer agent."""

    def __init__(self):
        self.key = nacl.signing.SigningKey.generate()

    def sign_intent(self, **overrides) -> IntentMandate:
        defaults = {
            "intent_mandate_id": f"intent-{time.time_ns()}",
            "buyer_agent_id": "scripted-agent-1",
            "buyer_public_key_hex": self.key.verify_key.encode().hex(),
            "max_amount": 200_000,
            "allowed_categories": ["case", "screen_protector", "charger"],
            "expiry": int(time.time()) + 3600,
            "nonce": f"nonce-{time.time_ns()}",
        }
        defaults.update(overrides)
        intent = IntentMandate(**defaults)
        signature = sign_payload(_signable_payload(intent), self.key)
        return intent.model_copy(update={"signature_hex": signature})


def _run_gate(intent, redis_client, items):
    verification = verify_intent_mandate(intent, redis_client)
    return gate_evaluate(intent, verification, items, CATALOG)


# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


def test_happy_path_search_to_receipt(redis_client):
    agent = ScriptedBuyerAgent()
    intent = agent.sign_intent()
    items = [RequestedItem(sku_id="SKU-CASE", quantity=1), RequestedItem(sku_id="SKU-SCREEN", quantity=1)]

    # search / get_product step: confirm both requested SKUs are actually
    # in the published catalog before even proposing a cart.
    assert all(sku_id in CATALOG and CATALOG[sku_id].published for sku_id in ("SKU-CASE", "SKU-SCREEN"))

    gate_result = _run_gate(intent, redis_client, items)
    assert gate_result.decision is GateDecision.ALLOW
    assert gate_result.cart_total == 59_900 + 29_900

    line_items = [CartLineItem(sku_id=i.sku_id, quantity=i.quantity, unit_amount=CATALOG[i.sku_id].unit_amount) for i in items]
    cart = issue_cart_mandate(intent, line_items, cart_mandate_id=f"cart-{intent.intent_mandate_id}")
    assert cart.total_amount == gate_result.cart_total

    razorpay_client = _FakeRazorpayClient()
    order = razorpay_client.order.create(
        {"amount": cart.total_amount, "currency": cart.currency, "receipt": cart.cart_mandate_id, "payment_capture": 0}
    )

    claim_result = claim(redis_client, cart.intent_mandate_id, cart_hash(cart.model_dump(mode="json")))
    assert claim_result.claimed

    receipt = execute_payment_behind_gate(razorpay_client, cart, gate_result, order["id"], "pay_fake_1")
    assert receipt.status == "captured"
    assert receipt.amount == cart.total_amount

    record_receipt(redis_client, cart.intent_mandate_id, cart_hash(cart.model_dump(mode="json")), receipt.__dict__)

    # get_order_status equivalent: the receipt is now retrievable and a
    # second claim attempt for the same intent+cart returns it instead of
    # re-executing.
    retry_claim = claim(redis_client, cart.intent_mandate_id, cart_hash(cart.model_dump(mode="json")))
    assert not retry_claim.claimed
    assert retry_claim.existing_receipt["status"] == "captured"


# ---------------------------------------------------------------------------
# Refusal paths.
# ---------------------------------------------------------------------------


def test_refusal_over_price_ceiling(redis_client):
    agent = ScriptedBuyerAgent()
    intent = agent.sign_intent(max_amount=10_000)  # SKU-CHARGER alone is 149_900
    result = _run_gate(intent, redis_client, [RequestedItem(sku_id="SKU-CHARGER", quantity=1)])
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.OVER_PRICE_CEILING


def test_refusal_expired_mandate(redis_client):
    agent = ScriptedBuyerAgent()
    intent = agent.sign_intent(expiry=int(time.time()) - 1)
    result = _run_gate(intent, redis_client, [RequestedItem(sku_id="SKU-CASE", quantity=1)])
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.MANDATE_EXPIRED


def test_refusal_replayed_nonce(redis_client):
    agent = ScriptedBuyerAgent()
    intent = agent.sign_intent()
    items = [RequestedItem(sku_id="SKU-CASE", quantity=1)]
    first = _run_gate(intent, redis_client, items)
    second = _run_gate(intent, redis_client, items)
    assert first.decision is GateDecision.ALLOW
    assert second.decision is GateDecision.REFUSE
    assert second.refusal.code is RefusalCode.NONCE_REPLAYED


def test_refusal_category_out_of_scope(redis_client):
    agent = ScriptedBuyerAgent()
    intent = agent.sign_intent(allowed_categories=["case"])  # charger not in scope
    result = _run_gate(intent, redis_client, [RequestedItem(sku_id="SKU-CHARGER", quantity=1)])
    assert result.decision is GateDecision.REFUSE
    assert result.refusal.code is RefusalCode.CATEGORY_NOT_ALLOWED


# ---------------------------------------------------------------------------
# Retry storm -- payment-level idempotency, deliberately distinct from
# mandate-level nonce replay above.
# ---------------------------------------------------------------------------


def test_retry_storm_only_one_payment_executes(redis_client):
    """Nonce replay (test_refusal_replayed_nonce) blocks re-verifying the
    SAME Intent Mandate twice -- that's a mandate-level guard. This test is
    a different failure mode: the mandate was verified and the cart
    mandate already issued ONCE (nonce already consumed, no second
    verification involved at all), and the buyer agent's own retry logic
    fires N near-simultaneous attempts to submit the SAME cart for payment
    (e.g. it never got a response to its first submission and doesn't know
    whether the charge went through). surface/idempotency.py, keyed on
    hash(intent_mandate_id + cart_hash), is what stops that from becoming N
    charges instead of one -- exactly the scenario CLAUDE.md's idempotency
    framing describes ("LLM agents retry non-deterministically").
    """
    agent = ScriptedBuyerAgent()
    intent = agent.sign_intent()
    items = [RequestedItem(sku_id="SKU-CASE", quantity=1)]
    gate_result = _run_gate(intent, redis_client, items)
    assert gate_result.decision is GateDecision.ALLOW

    line_items = [CartLineItem(sku_id="SKU-CASE", quantity=1, unit_amount=CATALOG["SKU-CASE"].unit_amount)]
    cart = issue_cart_mandate(intent, line_items, cart_mandate_id=f"cart-{intent.intent_mandate_id}")
    key_hash = cart_hash(cart.model_dump(mode="json"))

    claims = [claim(redis_client, cart.intent_mandate_id, key_hash) for _ in range(10)]
    assert sum(1 for c in claims if c.claimed) == 1

    executions = 0
    for c in claims:
        if c.claimed:
            razorpay_client = _FakeRazorpayClient()
            order = razorpay_client.order.create(
                {"amount": cart.total_amount, "currency": cart.currency, "receipt": cart.cart_mandate_id, "payment_capture": 0}
            )
            execute_payment_behind_gate(razorpay_client, cart, gate_result, order["id"], "pay_fake_storm")
            executions += 1
    assert executions == 1


def test_reconciliation_error_on_amount_mismatch_halts_rather_than_records():
    """If Razorpay's own recorded order amount ever disagreed with our cart
    total, capture must raise, not proceed -- fail closed."""
    agent = ScriptedBuyerAgent()
    intent = agent.sign_intent()
    cart = issue_cart_mandate(
        intent,
        [CartLineItem(sku_id="SKU-CASE", quantity=1, unit_amount=CATALOG["SKU-CASE"].unit_amount)],
        cart_mandate_id="cart-mismatch-test",
    )

    class _TamperedOrders:
        def fetch(self, order_id):
            return {"amount": cart.total_amount + 1}  # deliberately wrong

    class _TamperedClient:
        order = _TamperedOrders()

    allow_result = GateResult(decision=GateDecision.ALLOW)
    with pytest.raises(ReconciliationError):
        execute_payment_behind_gate(_TamperedClient(), cart, allow_result, "order_x", "pay_x")
