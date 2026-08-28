"""
AP2-aligned mandate handling -- the merchant side of AP2's mandate chain.

NO LLM IMPORTS IN THIS FILE (see CLAUDE.md).

AgentFront is the merchant: a buyer agent holds a signed Intent Mandate
(price ceiling, category scope, expiry, nonce) and presents it as
UNTRUSTED INPUT. verify_intent_mandate() checks it -- signature, expiry,
nonce replay -- against nothing but its own internal consistency; policy
checks that depend on the actual proposed cart (price ceiling vs cart
total, category scope vs requested SKUs) belong to surface/gate.py, which
receives this module's verification result as a plain argument rather than
re-deriving it (gate.py does no I/O of its own).

Once a cart is assembled and allowed, issue_cart_mandate() signs it with
our own merchant key, binding specific SKUs and a total to that intent.

Ed25519 via PyNaCl throughout. Never hand-rolled crypto (CLAUDE.md).
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

import nacl.exceptions
import nacl.signing
from dotenv import load_dotenv
from pydantic import BaseModel

from surface.refusal import Refusal, RefusalCode


class RedisLike(Protocol):
    """The one Redis method this module needs, as a protocol -- so a fake
    can stand in for tests without importing the real redis client."""

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> Any: ...


# ---------------------------------------------------------------------------
# Mandate shapes.
# ---------------------------------------------------------------------------


class IntentMandate(BaseModel):
    """Buyer-agent-issued: what the agent is authorized to do. Every field
    is untrusted until verify_intent_mandate() passes."""

    intent_mandate_id: str
    buyer_agent_id: str
    buyer_public_key_hex: str  # Ed25519 public key, hex -- who signed this
    max_amount: int  # smallest currency unit (paise), matching Razorpay
    currency: str = "INR"
    allowed_categories: list[str]
    expiry: int  # unix timestamp
    nonce: str
    signature_hex: str = ""  # excluded from the signed payload itself


class CartLineItem(BaseModel):
    sku_id: str
    quantity: int
    unit_amount: int  # paise


class CartMandate(BaseModel):
    """Merchant-issued, signed with our own key -- binds SKUs + total to a
    specific, already-verified Intent Mandate."""

    cart_mandate_id: str
    intent_mandate_id: str
    line_items: list[CartLineItem]
    total_amount: int
    currency: str
    issued_at: int
    signature_hex: str = ""


# ---------------------------------------------------------------------------
# Signing primitives.
# ---------------------------------------------------------------------------


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON -- sorted keys, no whitespace ambiguity -- so
    signer and verifier hash identical bytes for identical logical content."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _signable_payload(mandate: BaseModel) -> dict[str, Any]:
    return mandate.model_dump(exclude={"signature_hex"}, mode="json")


def verify_signature(payload: dict[str, Any], signature_hex: str, public_key_hex: str) -> bool:
    try:
        verify_key = nacl.signing.VerifyKey(bytes.fromhex(public_key_hex))
        verify_key.verify(_canonical_bytes(payload), bytes.fromhex(signature_hex))
        return True
    except (nacl.exceptions.BadSignatureError, ValueError):
        return False


def sign_payload(payload: dict[str, Any], signing_key: nacl.signing.SigningKey) -> str:
    return signing_key.sign(_canonical_bytes(payload)).signature.hex()


def merchant_signing_key() -> nacl.signing.SigningKey:
    """Loads MANDATE_SIGNING_SEED (32-byte hex) lazily, at call time, not at
    import time -- so importing this module never fails just because the
    env var isn't set yet (e.g. in a test that never issues a mandate)."""
    load_dotenv(override=False)
    seed_hex = os.environ.get("MANDATE_SIGNING_SEED", "").strip()
    if not seed_hex:
        raise RuntimeError(
            "MANDATE_SIGNING_SEED is not set. Generate one: "
            'python -c "import nacl.signing,binascii; '
            'print(binascii.hexlify(nacl.signing.SigningKey.generate()._seed).decode())"'
        )
    return nacl.signing.SigningKey(bytes.fromhex(seed_hex))


# ---------------------------------------------------------------------------
# Intent Mandate verification.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntentVerificationResult:
    valid: bool
    refusal: Refusal | None = None


def verify_intent_mandate(intent: IntentMandate, redis_client: RedisLike, now: int | None = None) -> IntentVerificationResult:
    """Checks intrinsic to the Intent Mandate itself: signature, expiry,
    nonce replay. Does NOT check price ceiling or category scope -- those
    depend on the proposed cart and are surface/gate.py's job, evaluated
    against this result as a plain argument.
    """
    now = int(time.time()) if now is None else now

    if not verify_signature(_signable_payload(intent), intent.signature_hex, intent.buyer_public_key_hex):
        return IntentVerificationResult(
            valid=False,
            refusal=Refusal(
                code=RefusalCode.INVALID_SIGNATURE,
                detail=f"signature does not verify for intent {intent.intent_mandate_id}",
                context={"intent_mandate_id": intent.intent_mandate_id},
            ),
        )

    if now >= intent.expiry:
        return IntentVerificationResult(
            valid=False,
            refusal=Refusal(
                code=RefusalCode.MANDATE_EXPIRED,
                detail=f"intent {intent.intent_mandate_id} expired at {intent.expiry}, now {now}",
                context={"intent_mandate_id": intent.intent_mandate_id, "expiry": intent.expiry, "now": now},
            ),
        )

    # Atomic claim-if-unclaimed. TTL matches the mandate's own remaining
    # validity window, not a fixed constant -- a nonce can't be replayed
    # after its mandate expires anyway, so there's no reason to remember it
    # in Redis for longer than that, and every entry self-evicts instead of
    # accumulating forever.
    nonce_key = f"agentfront:nonce:{intent.intent_mandate_id}:{intent.nonce}"
    ttl = max(intent.expiry - now, 1)
    claimed = redis_client.set(nonce_key, "1", nx=True, ex=ttl)
    if not claimed:
        return IntentVerificationResult(
            valid=False,
            refusal=Refusal(
                code=RefusalCode.NONCE_REPLAYED,
                detail=f"nonce {intent.nonce} already used for intent {intent.intent_mandate_id}",
                context={"intent_mandate_id": intent.intent_mandate_id, "nonce": intent.nonce},
            ),
        )

    return IntentVerificationResult(valid=True)


# ---------------------------------------------------------------------------
# Cart Mandate issuance.
# ---------------------------------------------------------------------------


def issue_cart_mandate(
    intent: IntentMandate,
    line_items: list[CartLineItem],
    cart_mandate_id: str,
    signing_key: nacl.signing.SigningKey | None = None,
    now: int | None = None,
) -> CartMandate:
    """Binds line_items + their total to intent.intent_mandate_id and signs
    with our merchant key. Caller (surface/gate.py) is responsible for
    having already verified the intent AND checked the total/categories
    against its policy limits -- this function just signs what it's given,
    it does not re-check policy.
    """
    now = int(time.time()) if now is None else now
    signing_key = signing_key if signing_key is not None else merchant_signing_key()

    unsigned = CartMandate(
        cart_mandate_id=cart_mandate_id,
        intent_mandate_id=intent.intent_mandate_id,
        line_items=line_items,
        total_amount=sum(li.quantity * li.unit_amount for li in line_items),
        currency=intent.currency,
        issued_at=now,
    )
    signature_hex = sign_payload(_signable_payload(unsigned), signing_key)
    return unsigned.model_copy(update={"signature_hex": signature_hex})


def verify_cart_mandate(cart: CartMandate, merchant_public_key_hex: str) -> bool:
    """Independently verifies OUR OWN signature on a Cart Mandate -- used by
    reconciliation and by tests, and available to a buyer agent that wants
    to confirm the cart it received is genuinely from us."""
    return verify_signature(_signable_payload(cart), cart.signature_hex, merchant_public_key_hex)
