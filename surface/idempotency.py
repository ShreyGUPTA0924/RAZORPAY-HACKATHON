"""Tier 1. Not yet implemented.

Redis-backed idempotency guard, keyed on hash(intent_mandate_id + cart_hash)
-- derived from the mandate, not the HTTP request, because LLM agents retry
non-deterministically.
"""
