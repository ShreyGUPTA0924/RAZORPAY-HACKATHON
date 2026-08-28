"""
Razorpay test-mode payment execution -- strictly behind surface/gate.py.

execute_payment_behind_gate() is a real, code-enforced check, not just a
docstring claim: it raises if handed anything but a GateDecision.ALLOW,
exactly the way surface/mandate.py treats an Intent Mandate as untrusted
input rather than a fact. This module has no business creating a real
(even test-mode) charge on its own initiative.

Wraps the same razorpay SDK calls scripts/razorpay_smoke.py already proved
work against real test-mode keys -- Order create/fetch and Payment capture.

Post-payment reconciliation: compare what Razorpay says against our own
recorded cart total at two points (right after fetching the order, and
again after capture). Any mismatch raises ReconciliationError rather than
silently recording a receipt that might be wrong -- drift here means either
a bug or something adversarial happened, and this fails closed either way.
"""

import os
from dataclasses import dataclass

import razorpay
from dotenv import load_dotenv

from surface.gate import GateDecision, GateResult
from surface.mandate import CartMandate


def get_client() -> razorpay.Client:
    load_dotenv(override=False)
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set in .env.")
    if not key_id.startswith("rzp_test_"):
        raise RuntimeError(
            f"REFUSING: RAZORPAY_KEY_ID does not start with 'rzp_test_' (got prefix {key_id[:9]!r}). "
            "This module must never run against a live key."
        )
    return razorpay.Client(auth=(key_id, key_secret))


@dataclass(frozen=True)
class PaymentReceipt:
    cart_mandate_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    status: str
    amount: int
    currency: str


class ReconciliationError(RuntimeError):
    """Razorpay's recorded amount/status doesn't match our own cart total --
    halt and alarm, never silently proceed."""


def create_order_for_cart(client: razorpay.Client, cart: CartMandate) -> dict:
    """Manual capture (payment_capture=0) -- capture_payment() below makes
    the explicit capture call meaningful, same reasoning as
    scripts/razorpay_smoke.py."""
    return client.order.create(
        {
            "amount": cart.total_amount,
            "currency": cart.currency,
            "receipt": cart.cart_mandate_id,
            "payment_capture": 0,
            "notes": {"cart_mandate_id": cart.cart_mandate_id, "intent_mandate_id": cart.intent_mandate_id},
        }
    )


def capture_payment(client: razorpay.Client, cart: CartMandate, razorpay_order_id: str, payment_id: str) -> PaymentReceipt:
    """Captures a payment completed via Razorpay Checkout (the UPI path
    proven in scripts/razorpay_smoke.py) and reconciles it against the cart
    both before and after the capture call."""
    order = client.order.fetch(razorpay_order_id)
    if order["amount"] != cart.total_amount:
        raise ReconciliationError(
            f"order {razorpay_order_id} amount {order['amount']} != cart total {cart.total_amount} for {cart.cart_mandate_id}"
        )

    result = client.payment.capture(payment_id, cart.total_amount, {"currency": cart.currency})

    if result["amount"] != cart.total_amount:
        raise ReconciliationError(
            f"captured amount {result['amount']} != cart total {cart.total_amount} for {cart.cart_mandate_id}"
        )
    if result["status"] != "captured":
        raise ReconciliationError(f"unexpected post-capture status {result['status']!r} for {cart.cart_mandate_id}")

    return PaymentReceipt(
        cart_mandate_id=cart.cart_mandate_id,
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=payment_id,
        status=result["status"],
        amount=result["amount"],
        currency=cart.currency,
    )


def execute_payment_behind_gate(
    client: razorpay.Client,
    cart: CartMandate,
    gate_result: GateResult,
    razorpay_order_id: str,
    payment_id: str,
) -> PaymentReceipt:
    """The only entrypoint anything outside this module should call. Refuses
    outright unless gate_result.decision is exactly ALLOW -- REFUSE and
    ESCALATE both stop here, not just at whatever called the gate."""
    if gate_result.decision is not GateDecision.ALLOW:
        raise RuntimeError(
            f"refusing to execute payment for {cart.cart_mandate_id}: gate decision was "
            f"{gate_result.decision.value!r}, not ALLOW"
        )
    return capture_payment(client, cart, razorpay_order_id, payment_id)
