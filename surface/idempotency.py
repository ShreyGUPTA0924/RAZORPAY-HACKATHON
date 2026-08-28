"""
Idempotency guard -- Tier 1 safety module.

Redis-backed, keyed on hash(intent_mandate_id + cart_hash) -- NOT on the
HTTP request. LLM agents retry non-deterministically; the retry storm is
agent-specific, and the key has to be derived from the mandate + cart it
represents, not whatever transport carried a given attempt, so two
genuinely different HTTP requests for the SAME intent+cart still collide on
the same guard and only one payment ever executes.

Usage is claim-then-record, not a single atomic "process payment" call,
because the actual payment execution (surface/payments.py, Razorpay) has to
happen strictly between the two: claim() tells you whether you're the
caller responsible for executing it; record_receipt() is only ever called
by whichever caller's claim() returned claimed=True.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol


class RedisLike(Protocol):
    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> Any: ...
    def get(self, key: str) -> Any: ...


# A day is generous for a demo; a real deployment would tune this to
# whatever window Razorpay itself guarantees idempotent behavior over.
IDEMPOTENCY_TTL_S = 24 * 3600

_PENDING_SENTINEL = {"status": "pending"}


def cart_hash(cart: dict[str, Any]) -> str:
    """Deterministic hash of a cart's content -- same items+amounts always
    hash the same regardless of key ordering in the input dict."""
    canonical = json.dumps(cart, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def idempotency_key(intent_mandate_id: str, cart_hash_value: str) -> str:
    raw = f"{intent_mandate_id}:{cart_hash_value}"
    return "agentfront:idempotency:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ClaimResult:
    claimed: bool  # True: you're first -- go execute the payment, then call record_receipt()
    existing_receipt: dict[str, Any] | None = None  # set when claimed=False and a receipt already exists
    pending: bool = False  # set when claimed=False and the first caller hasn't recorded a receipt yet (still in flight)


def claim(redis_client: RedisLike, intent_mandate_id: str, cart_hash_value: str) -> ClaimResult:
    """Attempt to claim this (intent, cart) pair for execution. Call BEFORE
    executing payment -- only proceed with payment if claimed=True."""
    key = idempotency_key(intent_mandate_id, cart_hash_value)
    if redis_client.set(key, json.dumps(_PENDING_SENTINEL), nx=True, ex=IDEMPOTENCY_TTL_S):
        return ClaimResult(claimed=True)

    existing_raw = redis_client.get(key)
    existing = json.loads(existing_raw) if existing_raw else None
    if existing == _PENDING_SENTINEL:
        return ClaimResult(claimed=False, pending=True)
    return ClaimResult(claimed=False, existing_receipt=existing)


def record_receipt(redis_client: RedisLike, intent_mandate_id: str, cart_hash_value: str, receipt: dict[str, Any]) -> None:
    """Overwrites the pending placeholder with the real receipt once payment
    completes. Only the caller whose claim() returned claimed=True should
    ever call this."""
    key = idempotency_key(intent_mandate_id, cart_hash_value)
    redis_client.set(key, json.dumps(receipt), ex=IDEMPOTENCY_TTL_S)
