"""
Generated MCP surface -- agent-readable storefront.

Tools: search_catalog, get_product, check_availability, get_capability_manifest,
create_cart_mandate, get_order_status.

Reads data/catalog.json (raw SKU metadata) + eval/extraction_results.json
(extracted attributes), re-running pipeline.quarantine.evaluate() at LOAD
TIME rather than trusting whatever quarantine decision was stored when
extraction last ran -- current rules, not a frozen snapshot. A quarantined
SKU is invisible here: it never appears in search results, get_product(),
or as a valid target for create_cart_mandate, which is the actual point --
"not published" has to mean not published everywhere, not just "hidden
behind a flag a caller could ignore."

This module imports pipeline.schema / pipeline.quarantine (pure data +
deterministic logic, no LLM -- extraction already happened upstream in
pipeline/extract.py) and surface.mandate / surface.gate / surface.payments
/ surface.idempotency for create_cart_mandate. It never calls an LLM
itself.

Uses mcp 2.x's MCPServer (the FastMCP name was retired in mcp 2.x -- see
https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver,
confirmed against the actually-installed version rather than assumed).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import redis as redis_lib
from mcp.server.mcpserver import MCPServer

from pipeline.quarantine import evaluate as quarantine_evaluate
from pipeline.quarantine import redact
from pipeline.schema import ATTRIBUTE_FIELDS, ProductAttributes
from surface.gate import GateDecision, RequestedItem, SkuAvailability
from surface.gate import evaluate as gate_evaluate
from surface.idempotency import cart_hash
from surface.mandate import (
    CartLineItem,
    IntentMandate,
    issue_cart_mandate,
    verify_intent_mandate,
)

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
EXTRACTION_RESULTS_PATH = ROOT / "eval" / "extraction_results.json"


@dataclass(frozen=True)
class PublishedProduct:
    sku_id: str
    title: str
    category: str
    attributes: ProductAttributes  # REDACTED (published) attributes -- never the raw extraction
    price_paise: int


def _price_to_paise(retail_price: str | None, discounted_price: str | None) -> int:
    raw = discounted_price or retail_price
    try:
        return round(float(raw) * 100)
    except (TypeError, ValueError):
        return 0


def load_published_catalog(
    catalog_path: Path = CATALOG_PATH, extraction_path: Path = EXTRACTION_RESULTS_PATH
) -> dict[str, PublishedProduct]:
    """Loads catalog + extraction results, quarantine-filters, returns ONLY
    published SKUs keyed by sku_id. Skips SKUs the extraction run errored
    on entirely -- an extraction error is not a publishable "no attributes"
    result, it's "we don't know," which quarantine.evaluate() would
    correctly refuse anyway (null accessory_type), but skipping here avoids
    even constructing a misleading all-empty ProductAttributes for it.
    """
    catalog = {row["sku_id"]: row for row in json.loads(catalog_path.read_text(encoding="utf-8"))}
    if not extraction_path.exists():
        return {}
    extraction_results = json.loads(extraction_path.read_text(encoding="utf-8"))

    published: dict[str, PublishedProduct] = {}
    for result in extraction_results:
        if result.get("error"):
            continue
        sku_id = result["sku_id"]
        catalog_row = catalog.get(sku_id)
        if catalog_row is None:
            continue

        attrs = ProductAttributes.model_validate(result["attributes"])
        decision = quarantine_evaluate(sku_id, attrs)
        if not decision.published:
            continue
        published_attrs = redact(attrs, decision)

        category = published_attrs.accessory_type.value.value if published_attrs.accessory_type.value else "unknown"
        published[sku_id] = PublishedProduct(
            sku_id=sku_id,
            title=catalog_row["product_name"],
            category=category,
            attributes=published_attrs,
            price_paise=_price_to_paise(catalog_row.get("retail_price"), catalog_row.get("discounted_price")),
        )
    return published


def _product_to_dict(product: PublishedProduct) -> dict[str, Any]:
    return {
        "sku_id": product.sku_id,
        "title": product.title,
        "category": product.category,
        "price_paise": product.price_paise,
        "attributes": {f: getattr(product.attributes, f).value for f in ATTRIBUTE_FIELDS},
    }


# ---------------------------------------------------------------------------
# Server + tools.
# ---------------------------------------------------------------------------

mcp = MCPServer("agentfront")


@mcp.tool()
def search_catalog(query: str = "", category: str | None = None) -> list[dict[str, Any]]:
    """Search published (non-quarantined) SKUs by keyword in the title,
    optionally filtered to one accessory_type category."""
    catalog = load_published_catalog()
    query_l = query.lower().strip()
    results = []
    for product in catalog.values():
        if category and product.category != category:
            continue
        if query_l and query_l not in product.title.lower():
            continue
        results.append(_product_to_dict(product))
    return results


@mcp.tool()
def get_product(sku_id: str) -> dict[str, Any] | None:
    """Full detail for one published SKU. Returns None for an unknown OR
    quarantined SKU -- the two are indistinguishable from the outside,
    deliberately: a buyer agent gets no signal about WHY something isn't
    purchasable through this tool, only that it isn't."""
    catalog = load_published_catalog()
    product = catalog.get(sku_id)
    return _product_to_dict(product) if product else None


@mcp.tool()
def check_availability(sku_id: str) -> dict[str, Any]:
    """published: whether the SKU exists and cleared quarantine. in_stock:
    always True for a published SKU -- this catalog has no real inventory
    data (Tier 0/1 scope), so stock is not modeled; every published SKU is
    treated as available rather than fabricating a stock number."""
    catalog = load_published_catalog()
    product = catalog.get(sku_id)
    return {"sku_id": sku_id, "published": product is not None, "in_stock": product is not None}


@mcp.tool()
def get_capability_manifest() -> dict[str, Any]:
    """What's purchasable, constraints, and policy, as structured data --
    not prose a buyer agent has to parse."""
    catalog = load_published_catalog()
    return {
        "categories": sorted({p.category for p in catalog.values()}),
        "sku_count": len(catalog),
        "currency": "INR",
        "payment_methods": ["upi"],  # card is currently blocked account-side, see scripts/razorpay_smoke.py
        "attribute_fields": list(ATTRIBUTE_FIELDS),
        "mandate_protocol": "AP2 (Intent Mandate -> Cart Mandate), Ed25519-signed",
        "idempotency": "keyed on hash(intent_mandate_id + cart content) -- safe to retry create_cart_mandate with identical inputs",
    }


@mcp.tool()
def create_cart_mandate(
    intent_mandate: dict[str, Any],
    requested_items: list[dict[str, Any]],
    redis_url: str = "redis://localhost:6379/0",
) -> dict[str, Any]:
    """Verifies the (untrusted) Intent Mandate, evaluates the requested cart
    against surface/gate.py, and -- only on ALLOW -- issues a signed Cart
    Mandate. requested_items: [{"sku_id": ..., "quantity": ...}, ...].

    Returns {"decision": "allow", "cart_mandate": {...}} or
    {"decision": "refuse", "refusal": {...}} or
    {"decision": "escalate", "escalation_reason": "..."}.
    """
    redis_client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    intent = IntentMandate.model_validate(intent_mandate)
    verification = verify_intent_mandate(intent, redis_client)

    catalog = load_published_catalog()
    items = [RequestedItem(sku_id=i["sku_id"], quantity=i["quantity"]) for i in requested_items]
    skus = {
        sku_id: SkuAvailability(
            sku_id=sku_id, published=True, in_stock=True, category=p.category, unit_amount=p.price_paise
        )
        for sku_id, p in catalog.items()
    }

    result = gate_evaluate(intent, verification, items, skus)

    if result.decision is GateDecision.REFUSE:
        return {"decision": "refuse", "refusal": result.refusal.to_dict()}
    if result.decision is GateDecision.ESCALATE:
        return {"decision": "escalate", "escalation_reason": result.escalation_reason, "cart_total": result.cart_total}

    line_items = [CartLineItem(sku_id=i.sku_id, quantity=i.quantity, unit_amount=skus[i.sku_id].unit_amount) for i in items]
    cart = issue_cart_mandate(intent, line_items, cart_mandate_id=f"cart-{intent.intent_mandate_id}-{int(time.time())}")

    order_key = f"agentfront:order:{cart.cart_mandate_id}"
    redis_client.set(
        order_key,
        json.dumps({"status": "cart_issued", "cart_hash": cart_hash(cart.model_dump(mode="json")), "cart": cart.model_dump(mode="json")}),
        ex=24 * 3600,
    )

    return {"decision": "allow", "cart_mandate": cart.model_dump(mode="json")}


@mcp.tool()
def get_order_status(cart_mandate_id: str, redis_url: str = "redis://localhost:6379/0") -> dict[str, Any]:
    """Looks up order status by cart_mandate_id -- the identifier a buyer
    agent gets back from create_cart_mandate."""
    redis_client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    raw = redis_client.get(f"agentfront:order:{cart_mandate_id}")
    if raw is None:
        return {"cart_mandate_id": cart_mandate_id, "status": "not_found"}
    record = json.loads(raw)
    return {"cart_mandate_id": cart_mandate_id, "status": record["status"]}


if __name__ == "__main__":
    mcp.run()
