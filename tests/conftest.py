"""
Shared pytest fixtures. redis_client talks to the real Redis from
docker-compose.yml (docker compose up -d) -- surface/mandate.py and
surface/idempotency.py are tested against real Redis semantics (SET NX EX,
key expiry), not a hand-rolled fake that could silently drift from how
Redis actually behaves.
"""

import pytest
import redis as redis_lib

REDIS_URL = "redis://localhost:6379/0"
REDIS_TEST_KEY_PREFIX = "agentfront:test:"


@pytest.fixture
def redis_client():
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.ConnectionError as e:
        pytest.skip(f"Redis not reachable at {REDIS_URL} (docker compose up -d?): {e}")

    # Scope cleanup to this project's own key prefix -- never flushdb() on a
    # shared local Redis that might have other things in it.
    for key in client.scan_iter(f"{REDIS_TEST_KEY_PREFIX}*"):
        client.delete(key)
    for key in client.scan_iter("agentfront:nonce:*"):
        client.delete(key)
    for key in client.scan_iter("agentfront:idempotency:*"):
        client.delete(key)
    for key in client.scan_iter("agentfront:cumulative_spend:*"):
        client.delete(key)

    yield client
