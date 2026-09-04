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
    def incrby(self, key: str, amount: int) -> Any: ...
    def expire(self, key: str, ttl: int) -> Any: ...


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


# ---------------------------------------------------------------------------
# Cumulative spend per intent_mandate_id.
#
# Nonce replay (surface/mandate.py) blocks reusing the SAME nonce; the
# per-cart key above blocks reusing the SAME cart. Neither stops several
# DIFFERENT successful transactions under one intent_mandate_id -- each
# individually under max_amount -- from summing past it. This is a separate,
# additive guard: surface/gate.py checks the running total against
# max_amount on every call (a plain int argument, fetched by the caller so
# gate.py stays a pure function with no I/O of its own -- see its docstring),
# and the caller records the new total here only after a payment actually,
# successfully completes. Found and reproduced by the independent
# adversarial red-team -- see docs/what-broke.md.
# ---------------------------------------------------------------------------


def cumulative_spend_key(intent_mandate_id: str) -> str:
    return "agentfront:cumulative_spend:" + hashlib.sha256(intent_mandate_id.encode("utf-8")).hexdigest()


def get_cumulative_spent(redis_client: RedisLike, intent_mandate_id: str) -> int:
    """Total paise already successfully charged under this intent_mandate_id
    across all prior transactions. 0 if none yet."""
    raw = redis_client.get(cumulative_spend_key(intent_mandate_id))
    return int(raw) if raw else 0


def record_spend(redis_client: RedisLike, intent_mandate_id: str, amount: int, ttl: int = IDEMPOTENCY_TTL_S) -> int:
    """Atomically adds `amount` to the running total for this
    intent_mandate_id. Only ever called after a payment has ACTUALLY,
    successfully completed -- this is what the next transaction's gate
    check compares against, so recording a charge that didn't really
    happen would create a false ceiling. Returns the new total."""
    key = cumulative_spend_key(intent_mandate_id)
    new_total = redis_client.incrby(key, amount)
    redis_client.expire(key, ttl)
    return new_total
