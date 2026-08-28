import time

import nacl.signing
import pytest

from surface.mandate import (
    CartLineItem,
    IntentMandate,
    _signable_payload,
    issue_cart_mandate,
    sign_payload,
    verify_cart_mandate,
    verify_intent_mandate,
    verify_signature,
)
from surface.refusal import RefusalCode


def _signed_intent(buyer_key, **overrides):
    defaults = {
        "intent_mandate_id": "intent-1",
        "buyer_agent_id": "agent-1",
        "buyer_public_key_hex": buyer_key.verify_key.encode().hex(),
        "max_amount": 100_000,
        "allowed_categories": ["case", "screen_protector"],
        "expiry": int(time.time()) + 3600,
        "nonce": "nonce-1",
    }
    defaults.update(overrides)
    intent = IntentMandate(**defaults)
    sig = sign_payload(_signable_payload(intent), buyer_key)
    return intent.model_copy(update={"signature_hex": sig})


@pytest.fixture
def buyer_key():
    return nacl.signing.SigningKey.generate()


@pytest.fixture
def merchant_key():
    return nacl.signing.SigningKey.generate()


# ---------------------------------------------------------------------------
# verify_intent_mandate
# ---------------------------------------------------------------------------


def test_valid_intent_passes(redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    result = verify_intent_mandate(intent, redis_client)
    assert result.valid
    assert result.refusal is None


def test_tampered_field_fails_signature(redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    tampered = intent.model_copy(update={"max_amount": 999_999_999})  # signature no longer matches
    result = verify_intent_mandate(tampered, redis_client)
    assert not result.valid
    assert result.refusal.code is RefusalCode.INVALID_SIGNATURE


def test_wrong_signer_fails_signature(redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    attacker_key = nacl.signing.SigningKey.generate()
    forged = intent.model_copy(update={"buyer_public_key_hex": attacker_key.verify_key.encode().hex()})
    result = verify_intent_mandate(forged, redis_client)
    assert not result.valid
    assert result.refusal.code is RefusalCode.INVALID_SIGNATURE


def test_expired_intent_refused(redis_client, buyer_key):
    intent = _signed_intent(buyer_key, expiry=int(time.time()) - 10)
    result = verify_intent_mandate(intent, redis_client)
    assert not result.valid
    assert result.refusal.code is RefusalCode.MANDATE_EXPIRED


def test_expiry_boundary_is_exclusive(redis_client, buyer_key):
    """now == expiry counts as expired -- the mandate is valid strictly
    before its expiry, not through it."""
    now = int(time.time())
    intent = _signed_intent(buyer_key, expiry=now)
    result = verify_intent_mandate(intent, redis_client, now=now)
    assert not result.valid
    assert result.refusal.code is RefusalCode.MANDATE_EXPIRED


def test_nonce_replay_refused_on_second_use(redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    first = verify_intent_mandate(intent, redis_client)
    second = verify_intent_mandate(intent, redis_client)
    assert first.valid
    assert not second.valid
    assert second.refusal.code is RefusalCode.NONCE_REPLAYED


def test_same_nonce_different_intent_id_is_not_a_replay(redis_client, buyer_key):
    """The nonce key is scoped to intent_mandate_id -- two different
    intents reusing the same nonce string are not the same replay."""
    intent_a = _signed_intent(buyer_key, intent_mandate_id="intent-A", nonce="shared-nonce")
    intent_b = _signed_intent(buyer_key, intent_mandate_id="intent-B", nonce="shared-nonce")
    result_a = verify_intent_mandate(intent_a, redis_client)
    result_b = verify_intent_mandate(intent_b, redis_client)
    assert result_a.valid
    assert result_b.valid


def test_signature_checked_before_nonce_is_claimed(redis_client, buyer_key):
    """An invalid-signature mandate must not consume the nonce -- otherwise
    an attacker could burn a legitimate future nonce just by forging a
    signature on it."""
    intent = _signed_intent(buyer_key)
    forged = intent.model_copy(update={"max_amount": 1})  # breaks the signature
    verify_intent_mandate(forged, redis_client)  # expected to fail on signature

    real = _signed_intent(buyer_key, nonce=intent.nonce, intent_mandate_id=intent.intent_mandate_id)
    result = verify_intent_mandate(real, redis_client)
    assert result.valid  # nonce was never claimed by the forged attempt


# ---------------------------------------------------------------------------
# Cart Mandate issuance / verification
# ---------------------------------------------------------------------------


def test_issue_cart_mandate_binds_intent_and_sums_total(buyer_key, merchant_key):
    intent = _signed_intent(buyer_key)
    items = [
        CartLineItem(sku_id="SKU-021", quantity=2, unit_amount=500),
        CartLineItem(sku_id="SKU-032", quantity=1, unit_amount=250),
    ]
    cart = issue_cart_mandate(intent, items, "cart-1", signing_key=merchant_key)
    assert cart.intent_mandate_id == intent.intent_mandate_id
    assert cart.total_amount == 1250
    assert cart.signature_hex


def test_issued_cart_mandate_verifies_against_merchant_key(buyer_key, merchant_key):
    intent = _signed_intent(buyer_key)
    cart = issue_cart_mandate(intent, [CartLineItem(sku_id="SKU-021", quantity=1, unit_amount=999)], "cart-1", signing_key=merchant_key)
    assert verify_cart_mandate(cart, merchant_key.verify_key.encode().hex())


def test_issued_cart_mandate_fails_against_wrong_key(buyer_key, merchant_key):
    intent = _signed_intent(buyer_key)
    cart = issue_cart_mandate(intent, [CartLineItem(sku_id="SKU-021", quantity=1, unit_amount=999)], "cart-1", signing_key=merchant_key)
    attacker_key = nacl.signing.SigningKey.generate()
    assert not verify_cart_mandate(cart, attacker_key.verify_key.encode().hex())


def test_tampered_cart_mandate_fails_verification(buyer_key, merchant_key):
    intent = _signed_intent(buyer_key)
    cart = issue_cart_mandate(intent, [CartLineItem(sku_id="SKU-021", quantity=1, unit_amount=999)], "cart-1", signing_key=merchant_key)
    tampered = cart.model_copy(update={"total_amount": 1})
    assert not verify_cart_mandate(tampered, merchant_key.verify_key.encode().hex())


def test_verify_signature_helper_directly():
    key = nacl.signing.SigningKey.generate()
    payload = {"a": 1, "b": "two"}
    sig = sign_payload(payload, key)
    assert verify_signature(payload, sig, key.verify_key.encode().hex())
    assert not verify_signature({**payload, "a": 2}, sig, key.verify_key.encode().hex())


def test_merchant_signing_key_missing_env_raises_clear_error(monkeypatch):
    from surface.mandate import merchant_signing_key

    # load_dotenv(override=False) would otherwise reload the real .env's
    # MANDATE_SIGNING_SEED right back after delenv -- stub it out so this
    # test actually exercises the "not set anywhere" path.
    monkeypatch.setattr("surface.mandate.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("MANDATE_SIGNING_SEED", raising=False)
    with pytest.raises(RuntimeError, match="MANDATE_SIGNING_SEED"):
        merchant_signing_key()
