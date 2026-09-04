"""
FastAPI app -- an ADDITIVE, optional live layer on top of the frontend's
default cached-replay demo (see frontend/README quickstart and
docs/architecture.md). The frontend works fully without this process
running at all; every endpoint here exists to let it show REAL results
when the backend is reachable, with an honest fallback when it isn't.

Every endpoint is read-only / demo-scoped: nothing here creates a real
Razorpay charge, nothing mutates the committed catalog. Real Redis
(mandate nonce, idempotency, cumulative spend), real
surface.gate/surface.mandate logic, and -- quota permitting -- real LLM
calls via pipeline.extract.

CORS is scoped to the Vite dev server origins only -- this is a local
demo API, not a public service.

Run with: uvicorn api.main:app --reload --port 8000
"""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.injection_demo import get_injection_demo_result
from api.scenarios import SCENARIOS, UnknownScenarioError, run_scenario
from pipeline.extract import extract_sku
from pipeline.schema import ATTRIBUTE_FIELDS

# Defaults to localhost for a bare `uvicorn api.main:app` run; docker-compose
# overrides this to the `redis` service hostname.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_state: dict[str, redis_lib.Redis | None] = {"redis": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Short connect/socket timeouts -- if Redis is down, callers should
    # find out in ~1s, not hang. The frontend's own apiClient timeout
    # (Part B) is the second layer of the same "fail fast, fall back"
    # requirement; this is the first.
    _state["redis"] = redis_lib.Redis.from_url(
        REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=2
    )
    yield


app = FastAPI(title="AgentFront demo API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _redis_ok() -> bool:
    client = _state["redis"]
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:  # noqa: BLE001 -- any connectivity failure means "not ok", not a 500
        return False


@app.get("/api/health")
def health():
    """The frontend calls this on load to decide live vs. cached mode.
    Deliberately fast and side-effect-free."""
    return {"status": "ok", "redis": _redis_ok()}


@app.post("/api/refusals/{scenario}")
def refusals(scenario: str):
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{scenario}'. Known: {SCENARIOS}")
    if not _redis_ok():
        raise HTTPException(status_code=503, detail="Redis unreachable -- cannot run a real gate evaluation")
    try:
        result = run_scenario(scenario, _state["redis"])
    except UnknownScenarioError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return asdict(result)


@app.post("/api/extract/injection-demo")
async def injection_demo():
    return await get_injection_demo_result()


class ExtractLiveRequest(BaseModel):
    sku_id: str = "SKU-001"
    title: str = "Generix OTG for Sony Xperia M5 OTG Cable"
    description: str = (
        "Buy Generix OTG for Sony Xperia M5 OTG Cable only for Rs. 199 from Flipkart.com. "
        "Only Genuine Products. 30 Day Replacement Guarantee. Free Shipping. Cash On Delivery!"
    )


# A real, previously-captured extraction of the default SKU above (see
# eval/extraction_results.json) -- the fallback if live extraction fails.
_EXTRACT_LIVE_CACHED_FIELDS = [
    {"field": "accessory_type", "value": "cable", "confidence": 0.95},
    {"field": "model_compat", "value": ["sony_xperia_m5"], "confidence": 0.95},
    {"field": "connector_type", "value": None, "confidence": 0.0},
    {"field": "wattage_w", "value": None, "confidence": 0.0},
    {"field": "capacity_mah", "value": None, "confidence": 0.0},
    {"field": "screen_size_in", "value": None, "confidence": 0.0},
    {"field": "wireless_charging", "value": None, "confidence": 0.0},
    {"field": "material", "value": None, "confidence": 0.0},
]


@app.post("/api/extract/live")
async def extract_live(req: ExtractLiveRequest):
    """One SKU, one real extraction call. Not true field-by-field
    streaming from the model (a single structured-output call fills every
    field at once; there's nothing to stream from the LLM side) -- returns
    the full per-field result in one response, which the frontend can
    still reveal progressively client-side, the same way the cached
    Extraction screen already does. Falls back to a real, previously-
    captured result (cached: true) on any failure."""

    def _run():
        result = extract_sku(req.sku_id, req.title, req.description)
        if result.error:
            raise RuntimeError(result.error)
        fields = []
        for field_name in ATTRIBUTE_FIELDS:
            attr = getattr(result.attributes, field_name)
            value = attr.value
            fields.append({"field": field_name, "value": value.value if hasattr(value, "value") else value, "confidence": attr.confidence})
        return fields

    try:
        fields = await asyncio.wait_for(asyncio.to_thread(_run), timeout=25)
        return {"cached": False, "sku_id": req.sku_id, "fields": fields}
    except Exception:  # noqa: BLE001 -- any failure falls back to a real, previously-captured result
        return {"cached": True, "sku_id": "SKU-001", "fields": _EXTRACT_LIVE_CACHED_FIELDS}
