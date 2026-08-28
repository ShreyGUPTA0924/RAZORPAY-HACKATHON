import os

import pytest
from dotenv import load_dotenv

from surface.gate import GateDecision, GateResult
from surface.mandate import CartLineItem, CartMandate
from surface.payments import (
    ReconciliationError,
    capture_payment,
    create_order_for_cart,
    execute_payment_behind_gate,
    get_client,
)

load_dotenv()


def make_cart(total=1_000, currency="INR") -> CartMandate:
    return CartMandate(
        cart_mandate_id="cart-1",
        intent_mandate_id="intent-1",
        line_items=[CartLineItem(sku_id="SKU-1", quantity=1, unit_amount=total)],
        total_amount=total,
        currency=currency,
        issued_at=0,
        signature_hex="ab" * 64,
    )


class _FakeOrders:
    def __init__(self, order):
        self._order = order

    def fetch(self, order_id):
        return self._order


class _FakePayments:
    def __init__(self, result):
        self._result = result

    def capture(self, payment_id, amount, data):
        return self._result


class _FakeClient:
    def __init__(self, order, payment_result):
        self.order = _FakeOrders(order)
        self.payment = _FakePayments(payment_result)


# ---------------------------------------------------------------------------
# Reconciliation -- mocked client, pure logic.
# ---------------------------------------------------------------------------


def test_capture_succeeds_when_amounts_match():
    cart = make_cart(total=999)
    client = _FakeClient(order={"amount": 999}, payment_result={"amount": 999, "status": "captured"})
    receipt = capture_payment(client, cart, "order_x", "pay_x")
    assert receipt.status == "captured"
    assert receipt.amount == 999
    assert receipt.cart_mandate_id == "cart-1"


def test_capture_raises_when_order_amount_mismatches_cart():
    cart = make_cart(total=999)
    client = _FakeClient(order={"amount": 500}, payment_result={"amount": 999, "status": "captured"})
    with pytest.raises(ReconciliationError, match="order.*amount"):
        capture_payment(client, cart, "order_x", "pay_x")


def test_capture_raises_when_captured_amount_mismatches_cart():
    cart = make_cart(total=999)
    client = _FakeClient(order={"amount": 999}, payment_result={"amount": 500, "status": "captured"})
    with pytest.raises(ReconciliationError, match="captured amount"):
        capture_payment(client, cart, "order_x", "pay_x")


def test_capture_raises_when_status_is_not_captured():
    cart = make_cart(total=999)
    client = _FakeClient(order={"amount": 999}, payment_result={"amount": 999, "status": "authorized"})
    with pytest.raises(ReconciliationError, match="status"):
        capture_payment(client, cart, "order_x", "pay_x")


# ---------------------------------------------------------------------------
# execute_payment_behind_gate -- the enforced trust boundary.
# ---------------------------------------------------------------------------


def test_refuses_to_execute_when_gate_decision_is_refuse():
    cart = make_cart()
    client = _FakeClient(order={"amount": 1_000}, payment_result={"amount": 1_000, "status": "captured"})
    gate_result = GateResult(decision=GateDecision.REFUSE)
    with pytest.raises(RuntimeError, match="not ALLOW"):
        execute_payment_behind_gate(client, cart, gate_result, "order_x", "pay_x")


def test_refuses_to_execute_when_gate_decision_is_escalate():
    cart = make_cart()
    client = _FakeClient(order={"amount": 1_000}, payment_result={"amount": 1_000, "status": "captured"})
    gate_result = GateResult(decision=GateDecision.ESCALATE)
    with pytest.raises(RuntimeError, match="not ALLOW"):
        execute_payment_behind_gate(client, cart, gate_result, "order_x", "pay_x")


def test_executes_when_gate_decision_is_allow():
    cart = make_cart(total=1_000)
    client = _FakeClient(order={"amount": 1_000}, payment_result={"amount": 1_000, "status": "captured"})
    gate_result = GateResult(decision=GateDecision.ALLOW)
    receipt = execute_payment_behind_gate(client, cart, gate_result, "order_x", "pay_x")
    assert receipt.status == "captured"


# ---------------------------------------------------------------------------
# get_client / create_order_for_cart against the REAL Razorpay test-mode API
# -- same connectivity already proven in scripts/razorpay_smoke.py. Skipped
# without real keys.
# ---------------------------------------------------------------------------

pytestmark_live = pytest.mark.skipif(
    not os.environ.get("RAZORPAY_KEY_ID", "").startswith("rzp_test_"),
    reason="RAZORPAY_KEY_ID not set to a test-mode key",
)


@pytestmark_live
def test_create_order_for_cart_against_real_api():
    client = get_client()
    cart = make_cart(total=100)
    order = create_order_for_cart(client, cart)
    assert order["amount"] == 100
    assert order["currency"] == "INR"
    assert order["status"] == "created"


def test_get_client_refuses_live_looking_key(monkeypatch):
    monkeypatch.setattr("surface.payments.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_deadbeef")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "whatever")
    with pytest.raises(RuntimeError, match="REFUSING"):
        get_client()


def test_get_client_raises_when_keys_missing(monkeypatch):
    monkeypatch.setattr("surface.payments.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="not set"):
        get_client()
