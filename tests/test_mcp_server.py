import json
import time

import nacl.signing
import pytest

from pipeline.schema import AccessoryType, AttrValue, ProductAttributes
from surface import mcp_server
from surface.mandate import _signable_payload, sign_payload
from surface.mcp_server import (
    PublishedProduct,
    check_availability,
    create_cart_mandate,
    get_capability_manifest,
    get_order_status,
    get_product,
    load_published_catalog,
    search_catalog,
)

REDIS_URL = "redis://localhost:6379/0"


def _write_fixture(tmp_path, catalog_rows, extraction_rows):
    catalog_path = tmp_path / "catalog.json"
    extraction_path = tmp_path / "extraction_results.json"
    catalog_path.write_text(json.dumps(catalog_rows), encoding="utf-8")
    extraction_path.write_text(json.dumps(extraction_rows), encoding="utf-8")
    return catalog_path, extraction_path


def _catalog_row(sku_id="SKU-1", product_name="Test Cable", retail_price="199", discounted_price="149"):
    return {"sku_id": sku_id, "product_name": product_name, "retail_price": retail_price, "discounted_price": discounted_price}


def _extraction_row(sku_id="SKU-1", error=None, accessory_type="cable", confidence=0.95):
    return {
        "sku_id": sku_id,
        "error": error,
        "attributes": {
            "accessory_type": {"value": accessory_type, "confidence": confidence},
            "model_compat": {"value": None, "confidence": 0.0},
            "connector_type": {"value": "usb_c", "confidence": 0.9},
            "wattage_w": {"value": None, "confidence": 0.0},
            "capacity_mah": {"value": None, "confidence": 0.0},
            "screen_size_in": {"value": None, "confidence": 0.0},
            "wireless_charging": {"value": None, "confidence": 0.0},
            "material": {"value": None, "confidence": 0.0},
        },
    }


# ---------------------------------------------------------------------------
# load_published_catalog
# ---------------------------------------------------------------------------


def test_load_published_catalog_includes_clean_high_confidence_sku(tmp_path):
    catalog_path, extraction_path = _write_fixture(tmp_path, [_catalog_row()], [_extraction_row()])
    published = load_published_catalog(catalog_path, extraction_path)
    assert "SKU-1" in published
    assert published["SKU-1"].category == "cable"
    assert published["SKU-1"].price_paise == 14900  # discounted_price wins


def test_load_published_catalog_excludes_quarantined_sku(tmp_path):
    """accessory_type below threshold -- pipeline.quarantine.evaluate()
    quarantines the whole SKU."""
    catalog_path, extraction_path = _write_fixture(
        tmp_path, [_catalog_row()], [_extraction_row(accessory_type="cable", confidence=0.1)]
    )
    published = load_published_catalog(catalog_path, extraction_path)
    assert "SKU-1" not in published


def test_load_published_catalog_excludes_errored_extraction(tmp_path):
    catalog_path, extraction_path = _write_fixture(tmp_path, [_catalog_row()], [_extraction_row(error="rate limited")])
    published = load_published_catalog(catalog_path, extraction_path)
    assert "SKU-1" not in published


def test_load_published_catalog_missing_extraction_file_returns_empty(tmp_path):
    catalog_path, _ = _write_fixture(tmp_path, [_catalog_row()], [])
    published = load_published_catalog(catalog_path, tmp_path / "does-not-exist.json")
    assert published == {}


def test_redacted_fields_are_none_even_if_extraction_claimed_a_value(tmp_path):
    """A low-confidence NON-gating field gets redacted (nulled) even though
    the SKU itself is still published -- confirms mcp_server actually uses
    pipeline.quarantine.redact(), not the raw extraction."""
    row = _extraction_row()
    row["attributes"]["connector_type"] = {"value": "usb_c", "confidence": 0.1}  # below threshold
    catalog_path, extraction_path = _write_fixture(tmp_path, [_catalog_row()], [row])
    published = load_published_catalog(catalog_path, extraction_path)
    assert published["SKU-1"].attributes.connector_type.value is None


# ---------------------------------------------------------------------------
# search_catalog / get_product / check_availability / get_capability_manifest
# -- load_published_catalog patched so these test tool logic in isolation.
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_catalog(monkeypatch):
    catalog = {
        "SKU-1": PublishedProduct(
            sku_id="SKU-1", title="USB-C Fast Charging Cable", category="cable",
            attributes=ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9)),
            price_paise=14900,
        ),
        "SKU-2": PublishedProduct(
            sku_id="SKU-2", title="Leather Flip Case", category="case",
            attributes=ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CASE, confidence=0.9)),
            price_paise=59900,
        ),
    }
    monkeypatch.setattr(mcp_server, "load_published_catalog", lambda: catalog)
    return catalog


def test_search_catalog_keyword_match(fixture_catalog):
    results = search_catalog(query="cable")
    assert [r["sku_id"] for r in results] == ["SKU-1"]


def test_search_catalog_category_filter(fixture_catalog):
    results = search_catalog(category="case")
    assert [r["sku_id"] for r in results] == ["SKU-2"]


def test_search_catalog_no_filters_returns_everything(fixture_catalog):
    results = search_catalog()
    assert len(results) == 2


def test_get_product_found(fixture_catalog):
    product = get_product("SKU-1")
    assert product["sku_id"] == "SKU-1"
    assert product["category"] == "cable"


def test_get_product_not_found_is_none_not_an_error(fixture_catalog):
    assert get_product("SKU-999") is None


def test_check_availability_published_and_unpublished(fixture_catalog):
    assert check_availability("SKU-1") == {"sku_id": "SKU-1", "published": True, "in_stock": True}
    assert check_availability("SKU-999") == {"sku_id": "SKU-999", "published": False, "in_stock": False}


def test_capability_manifest_reflects_catalog(fixture_catalog):
    manifest = get_capability_manifest()
    assert manifest["sku_count"] == 2
    assert set(manifest["categories"]) == {"cable", "case"}
    assert manifest["payment_methods"] == ["upi"]


# ---------------------------------------------------------------------------
# create_cart_mandate / get_order_status -- real Redis, real crypto.
# ---------------------------------------------------------------------------


def _signed_intent(buyer_key, **overrides):
    from surface.mandate import IntentMandate

    defaults = {
        "intent_mandate_id": f"intent-{time.time_ns()}",
        "buyer_agent_id": "agent-1",
        "buyer_public_key_hex": buyer_key.verify_key.encode().hex(),
        "max_amount": 100_000,
        "allowed_categories": ["cable", "case"],
        "expiry": int(time.time()) + 3600,
        "nonce": f"nonce-{time.time_ns()}",
    }
    defaults.update(overrides)
    intent = IntentMandate(**defaults)
    sig = sign_payload(_signable_payload(intent), buyer_key)
    return intent.model_copy(update={"signature_hex": sig})


@pytest.fixture
def buyer_key():
    return nacl.signing.SigningKey.generate()


def test_create_cart_mandate_allows_valid_request(fixture_catalog, redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    result = create_cart_mandate(
        intent_mandate=intent.model_dump(mode="json"),
        requested_items=[{"sku_id": "SKU-1", "quantity": 1}],
        redis_url=REDIS_URL,
    )
    assert result["decision"] == "allow"
    assert result["cart_mandate"]["total_amount"] == 14900
    assert result["cart_mandate"]["intent_mandate_id"] == intent.intent_mandate_id


def test_create_cart_mandate_refuses_bad_signature(fixture_catalog, redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    tampered = intent.model_dump(mode="json")
    tampered["max_amount"] = 999_999_999
    result = create_cart_mandate(intent_mandate=tampered, requested_items=[{"sku_id": "SKU-1", "quantity": 1}], redis_url=REDIS_URL)
    assert result["decision"] == "refuse"
    assert result["refusal"]["code"] == "invalid_signature"


def test_create_cart_mandate_refuses_over_ceiling(fixture_catalog, redis_client, buyer_key):
    intent = _signed_intent(buyer_key, max_amount=100)
    result = create_cart_mandate(intent_mandate=intent.model_dump(mode="json"), requested_items=[{"sku_id": "SKU-1", "quantity": 1}], redis_url=REDIS_URL)
    assert result["decision"] == "refuse"
    assert result["refusal"]["code"] == "over_price_ceiling"


def test_create_cart_mandate_refuses_category_out_of_scope(fixture_catalog, redis_client, buyer_key):
    intent = _signed_intent(buyer_key, allowed_categories=["case"])  # SKU-1 is a cable
    result = create_cart_mandate(intent_mandate=intent.model_dump(mode="json"), requested_items=[{"sku_id": "SKU-1", "quantity": 1}], redis_url=REDIS_URL)
    assert result["decision"] == "refuse"
    assert result["refusal"]["code"] == "category_not_allowed"


def test_create_cart_mandate_refuses_unknown_sku(fixture_catalog, redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    result = create_cart_mandate(intent_mandate=intent.model_dump(mode="json"), requested_items=[{"sku_id": "SKU-DOES-NOT-EXIST", "quantity": 1}], redis_url=REDIS_URL)
    assert result["decision"] == "refuse"
    assert result["refusal"]["code"] == "sku_not_published"


def test_create_cart_mandate_replay_is_refused(fixture_catalog, redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    items = [{"sku_id": "SKU-1", "quantity": 1}]
    first = create_cart_mandate(intent_mandate=intent.model_dump(mode="json"), requested_items=items, redis_url=REDIS_URL)
    second = create_cart_mandate(intent_mandate=intent.model_dump(mode="json"), requested_items=items, redis_url=REDIS_URL)
    assert first["decision"] == "allow"
    assert second["decision"] == "refuse"
    assert second["refusal"]["code"] == "nonce_replayed"


def test_get_order_status_after_cart_issued(fixture_catalog, redis_client, buyer_key):
    intent = _signed_intent(buyer_key)
    result = create_cart_mandate(intent_mandate=intent.model_dump(mode="json"), requested_items=[{"sku_id": "SKU-1", "quantity": 1}], redis_url=REDIS_URL)
    cart_mandate_id = result["cart_mandate"]["cart_mandate_id"]
    status = get_order_status(cart_mandate_id, redis_url=REDIS_URL)
    assert status["status"] == "cart_issued"


def test_get_order_status_unknown_id_is_not_found(redis_client):
    status = get_order_status("cart-never-existed", redis_url=REDIS_URL)
    assert status["status"] == "not_found"
