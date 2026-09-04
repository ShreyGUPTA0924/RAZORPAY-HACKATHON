"""
Real refusal scenarios for the /api/refusals/{scenario} endpoint.

Each one builds a real, signed (or deliberately tampered) IntentMandate --
using a fresh Ed25519 keypair the "attacker" fully controls, exactly what a
real buyer agent holds -- and runs it through the REAL
surface.mandate.verify_intent_mandate -> surface.gate.evaluate ->
surface.idempotency stack, against real Redis. Nothing here is a mocked or
pre-baked decision; every RefusalCode returned is whatever the real gate
actually produced for these specific inputs, computed fresh on every call
(a new random intent_mandate_id per call, so repeated demo runs don't
collide with earlier Redis state).
"""

import time
import uuid
from dataclasses import dataclass, field

import nacl.signing

from surface.gate import GateDecision, RequestedItem, SkuAvailability
from surface.gate import evaluate as gate_evaluate
from surface.idempotency import (
    cart_hash,
    claim,
    get_cumulative_spent,
    record_receipt,
    record_spend,
)
from surface.mandate import (
    CartLineItem,
    IntentMandate,
    _signable_payload,
    issue_cart_mandate,
    sign_payload,
    verify_intent_mandate,
)

# Real catalog SKUs (same data used throughout eval/ and the frontend's
# agent-session.ts fixture) -- not invented numbers.
DEMO_SKUS: dict[str, SkuAvailability] = {
    "SKU-001": SkuAvailability(sku_id="SKU-001", published=True, in_stock=True, category="cable", unit_amount=19900),
    "SKU-018": SkuAvailability(sku_id="SKU-018", published=True, in_stock=True, category="charger", unit_amount=29900),
    "SKU-021": SkuAvailability(sku_id="SKU-021", published=True, in_stock=True, category="case", unit_amount=59900),
}

SCENARIOS = [
    "over_ceiling",
    "cumulative_ceiling",
    "expired_mandate",
    "replayed_nonce",
    "out_of_category",
    "retry_storm",
    "invalid_signature",
]


@dataclass
class DecisionStep:
    label: str
    decision: str  # "allow" | "refuse" | "escalate" | "claimed" | "blocked"
    refusal_code: str | None = None
    refusal_detail: str | None = None
    cart_total: int | None = None


@dataclass
class ScenarioResult:
    scenario: str
    description: str
    steps: list[DecisionStep] = field(default_factory=list)


class UnknownScenarioError(ValueError):
    pass


def _new_agent() -> nacl.signing.SigningKey:
    return nacl.signing.SigningKey.generate()


def _sign(intent: IntentMandate, key: nacl.signing.SigningKey) -> IntentMandate:
    sig = sign_payload(_signable_payload(intent), key)
    return intent.model_copy(update={"signature_hex": sig})


def _make_intent(key: nacl.signing.SigningKey | None = None, **overrides) -> IntentMandate:
    key = key or _new_agent()
    now = int(time.time())
    defaults = {
        "intent_mandate_id": f"demo-{uuid.uuid4().hex[:10]}",
        "buyer_agent_id": "refusal-gallery-demo",
        "buyer_public_key_hex": key.verify_key.encode().hex(),
        "max_amount": 50000,
        "allowed_categories": ["charger", "cable", "case"],
        "expiry": now + 3600,
        "nonce": f"nonce-{uuid.uuid4().hex[:10]}",
    }
    defaults.update(overrides)
    intent = IntentMandate(**defaults)
    return _sign(intent, key)


def _step_from_gate(label: str, result) -> DecisionStep:
    return DecisionStep(
        label=label,
        decision=result.decision.value,
        refusal_code=result.refusal.code.value if result.refusal else None,
        refusal_detail=result.refusal.detail if result.refusal else None,
        cart_total=result.cart_total,
    )


def _execute_if_allowed(redis_client, intent: IntentMandate, items: list[RequestedItem], result) -> None:
    """On ALLOW, actually issues the cart mandate and records spend against
    the real cumulative-spend guard -- so a follow-up step in the same
    scenario sees genuine prior spend, not a simulated number."""
    if result.decision is not GateDecision.ALLOW:
        return
    line_items = [CartLineItem(sku_id=i.sku_id, quantity=i.quantity, unit_amount=DEMO_SKUS[i.sku_id].unit_amount) for i in items]
    cart = issue_cart_mandate(intent, line_items, cart_mandate_id=f"demo-cart-{uuid.uuid4().hex[:10]}")
    key_hash = cart_hash(cart.model_dump(mode="json"))
    claim_result = claim(redis_client, cart.intent_mandate_id, key_hash)
    if claim_result.claimed:
        record_receipt(redis_client, cart.intent_mandate_id, key_hash, {"status": "captured", "amount": cart.total_amount})
        record_spend(redis_client, cart.intent_mandate_id, cart.total_amount)


def scenario_over_ceiling(redis_client) -> ScenarioResult:
    intent = _make_intent(max_amount=50000, allowed_categories=["case"])
    items = [RequestedItem(sku_id="SKU-021", quantity=1)]
    verification = verify_intent_mandate(intent, redis_client)
    result = gate_evaluate(intent, verification, items, DEMO_SKUS)
    return ScenarioResult(
        scenario="over_ceiling",
        description="An agent tries to buy a ₹599 case against a ₹500 mandate ceiling.",
        steps=[_step_from_gate("Purchase attempt", result)],
    )


def scenario_cumulative_ceiling(redis_client) -> ScenarioResult:
    key = _new_agent()
    mandate_id = f"demo-{uuid.uuid4().hex[:10]}"
    common = {"key": key, "intent_mandate_id": mandate_id, "max_amount": 45000, "allowed_categories": ["cable", "charger"]}

    intent1 = _make_intent(nonce=f"nonce-{uuid.uuid4().hex[:10]}", **common)
    items1 = [RequestedItem(sku_id="SKU-001", quantity=1)]  # 19900
    prev1 = get_cumulative_spent(redis_client, mandate_id)
    v1 = verify_intent_mandate(intent1, redis_client)
    r1 = gate_evaluate(intent1, v1, items1, DEMO_SKUS, previously_spent=prev1)
    _execute_if_allowed(redis_client, intent1, items1, r1)

    intent2 = _make_intent(nonce=f"nonce-{uuid.uuid4().hex[:10]}", **common)
    items2 = [RequestedItem(sku_id="SKU-018", quantity=1)]  # 29900 -- alone under 45000, but 19900+29900=49800 > 45000
    prev2 = get_cumulative_spent(redis_client, mandate_id)
    v2 = verify_intent_mandate(intent2, redis_client)
    r2 = gate_evaluate(intent2, v2, items2, DEMO_SKUS, previously_spent=prev2)

    return ScenarioResult(
        scenario="cumulative_ceiling",
        description="One mandate, two transactions: ₹199 then ₹299 against a ₹450 ceiling -- neither alone is over, but together they are.",
        steps=[
            _step_from_gate("First purchase (₹199 cable)", r1),
            _step_from_gate("Second purchase (₹299 charger)", r2),
        ],
    )


def scenario_expired_mandate(redis_client) -> ScenarioResult:
    intent = _make_intent(expiry=int(time.time()) - 10)
    items = [RequestedItem(sku_id="SKU-001", quantity=1)]
    verification = verify_intent_mandate(intent, redis_client)
    result = gate_evaluate(intent, verification, items, DEMO_SKUS)
    return ScenarioResult(
        scenario="expired_mandate",
        description="An agent presents a mandate that already expired before the transaction.",
        steps=[_step_from_gate("Purchase attempt", result)],
    )


def scenario_replayed_nonce(redis_client) -> ScenarioResult:
    intent = _make_intent()
    items = [RequestedItem(sku_id="SKU-001", quantity=1)]

    v1 = verify_intent_mandate(intent, redis_client)
    r1 = gate_evaluate(intent, v1, items, DEMO_SKUS)
    _execute_if_allowed(redis_client, intent, items, r1)

    v2 = verify_intent_mandate(intent, redis_client)  # same intent, same nonce
    r2 = gate_evaluate(intent, v2, items, DEMO_SKUS)

    return ScenarioResult(
        scenario="replayed_nonce",
        description="An agent resubmits the exact same signed authorization a second time.",
        steps=[
            _step_from_gate("First submission", r1),
            _step_from_gate("Replayed submission", r2),
        ],
    )


def scenario_out_of_category(redis_client) -> ScenarioResult:
    intent = _make_intent(allowed_categories=["case"])
    items = [RequestedItem(sku_id="SKU-018", quantity=1)]  # charger, not in scope
    verification = verify_intent_mandate(intent, redis_client)
    result = gate_evaluate(intent, verification, items, DEMO_SKUS)
    return ScenarioResult(
        scenario="out_of_category",
        description="An agent's mandate only authorizes 'case' purchases; it tries to buy a charger.",
        steps=[_step_from_gate("Purchase attempt", result)],
    )


def scenario_retry_storm(redis_client) -> ScenarioResult:
    intent = _make_intent()
    items = [RequestedItem(sku_id="SKU-001", quantity=1)]
    verification = verify_intent_mandate(intent, redis_client)
    result = gate_evaluate(intent, verification, items, DEMO_SKUS)

    steps = [_step_from_gate("Gate decision (checked once)", result)]

    if result.decision is GateDecision.ALLOW:
        line_items = [CartLineItem(sku_id=i.sku_id, quantity=i.quantity, unit_amount=DEMO_SKUS[i.sku_id].unit_amount) for i in items]
        cart = issue_cart_mandate(intent, line_items, cart_mandate_id=f"demo-cart-{uuid.uuid4().hex[:10]}")
        key_hash = cart_hash(cart.model_dump(mode="json"))
        for i in range(5):
            claim_result = claim(redis_client, cart.intent_mandate_id, key_hash)
            if claim_result.claimed:
                record_receipt(redis_client, cart.intent_mandate_id, key_hash, {"status": "captured", "amount": cart.total_amount})
                record_spend(redis_client, cart.intent_mandate_id, cart.total_amount)
                steps.append(DecisionStep(label=f"Retry attempt {i + 1}/5", decision="claimed", cart_total=cart.total_amount))
            else:
                steps.append(DecisionStep(label=f"Retry attempt {i + 1}/5", decision="blocked", refusal_detail="Idempotency guard: same (intent, cart) already claimed"))

    return ScenarioResult(
        scenario="retry_storm",
        description="An agent retries the same payment 5 times after never receiving a response -- only one may execute.",
        steps=steps,
    )


def scenario_invalid_signature(redis_client) -> ScenarioResult:
    key = _new_agent()
    intent = _make_intent(key=key)
    tampered = intent.model_copy(update={"max_amount": intent.max_amount * 10})  # signature no longer matches
    items = [RequestedItem(sku_id="SKU-001", quantity=1)]
    verification = verify_intent_mandate(tampered, redis_client)
    result = gate_evaluate(tampered, verification, items, DEMO_SKUS)
    return ScenarioResult(
        scenario="invalid_signature",
        description="An agent presents a mandate whose fields were altered after signing -- max_amount raised 10x post-signature.",
        steps=[_step_from_gate("Purchase attempt", result)],
    )


_SCENARIO_FUNCS = {
    "over_ceiling": scenario_over_ceiling,
    "cumulative_ceiling": scenario_cumulative_ceiling,
    "expired_mandate": scenario_expired_mandate,
    "replayed_nonce": scenario_replayed_nonce,
    "out_of_category": scenario_out_of_category,
    "retry_storm": scenario_retry_storm,
    "invalid_signature": scenario_invalid_signature,
}


def run_scenario(scenario: str, redis_client) -> ScenarioResult:
    func = _SCENARIO_FUNCS.get(scenario)
    if func is None:
        raise UnknownScenarioError(f"Unknown scenario '{scenario}'. Known: {SCENARIOS}")
    return func(redis_client)
