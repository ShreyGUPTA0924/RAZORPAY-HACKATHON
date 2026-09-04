from surface.idempotency import (
    cart_hash,
    claim,
    cumulative_spend_key,
    get_cumulative_spent,
    idempotency_key,
    record_receipt,
    record_spend,
)


def test_first_claim_succeeds(redis_client):
    result = claim(redis_client, "intent-1", "cart-hash-1")
    assert result.claimed
    assert result.existing_receipt is None


def test_second_claim_before_receipt_is_pending_not_a_receipt(redis_client):
    claim(redis_client, "intent-1", "cart-hash-1")
    second = claim(redis_client, "intent-1", "cart-hash-1")
    assert not second.claimed
    assert second.pending
    assert second.existing_receipt is None


def test_second_claim_after_receipt_returns_original_receipt_not_a_new_charge(redis_client):
    claim(redis_client, "intent-1", "cart-hash-1")
    receipt = {"razorpay_order_id": "order_abc", "status": "captured", "amount": 999}
    record_receipt(redis_client, "intent-1", "cart-hash-1", receipt)

    retry = claim(redis_client, "intent-1", "cart-hash-1")
    assert not retry.claimed
    assert retry.existing_receipt == receipt


def test_retry_storm_only_one_caller_gets_claimed_true(redis_client):
    """Simulates N near-simultaneous retries of the same mandate+cart --
    exactly one should be told to execute the payment."""
    results = [claim(redis_client, "intent-1", "cart-hash-1") for _ in range(10)]
    assert sum(1 for r in results if r.claimed) == 1


def test_different_cart_same_intent_is_a_different_key(redis_client):
    a = claim(redis_client, "intent-1", "cart-hash-A")
    b = claim(redis_client, "intent-1", "cart-hash-B")
    assert a.claimed
    assert b.claimed  # different cart content -- not the same idempotency key


def test_same_cart_different_intent_is_a_different_key(redis_client):
    a = claim(redis_client, "intent-A", "cart-hash-1")
    b = claim(redis_client, "intent-B", "cart-hash-1")
    assert a.claimed
    assert b.claimed


def test_cart_hash_is_stable_regardless_of_key_order():
    cart1 = {"sku_id": "SKU-1", "total": 999, "qty": 1}
    cart2 = {"qty": 1, "total": 999, "sku_id": "SKU-1"}
    assert cart_hash(cart1) == cart_hash(cart2)


def test_cart_hash_changes_with_content():
    assert cart_hash({"total": 999}) != cart_hash({"total": 1000})


def test_idempotency_key_is_namespaced():
    key = idempotency_key("intent-1", "hash-1")
    assert key.startswith("agentfront:idempotency:")


# ---------------------------------------------------------------------------
# Cumulative spend -- closes the bypass documented in docs/what-broke.md:
# nonce replay and per-cart idempotency each guard the transaction they were
# built to guard, but neither tracked running spend across several distinct
# transactions under one intent_mandate_id.
# ---------------------------------------------------------------------------


def test_cumulative_spend_key_is_namespaced():
    assert cumulative_spend_key("intent-1").startswith("agentfront:cumulative_spend:")


def test_get_cumulative_spent_is_zero_before_any_spend(redis_client):
    assert get_cumulative_spent(redis_client, "intent-1") == 0


def test_record_spend_accumulates_across_calls(redis_client):
    record_spend(redis_client, "intent-1", 3_000)
    record_spend(redis_client, "intent-1", 2_000)
    assert get_cumulative_spent(redis_client, "intent-1") == 5_000


def test_record_spend_returns_the_new_total(redis_client):
    record_spend(redis_client, "intent-1", 3_000)
    assert record_spend(redis_client, "intent-1", 2_000) == 5_000


def test_cumulative_spend_is_isolated_per_intent_mandate_id(redis_client):
    record_spend(redis_client, "intent-A", 3_000)
    record_spend(redis_client, "intent-B", 7_000)
    assert get_cumulative_spent(redis_client, "intent-A") == 3_000
    assert get_cumulative_spent(redis_client, "intent-B") == 7_000


def test_record_spend_sets_an_expiry_not_a_permanent_key(redis_client):
    record_spend(redis_client, "intent-1", 1_000)
    ttl = redis_client.ttl(cumulative_spend_key("intent-1"))
    assert ttl > 0
