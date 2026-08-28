from surface.idempotency import cart_hash, claim, idempotency_key, record_receipt


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
