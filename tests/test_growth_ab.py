"""
Mocked unit tests for eval/growth_ab.py. No network calls -- Target A's
LLM call is patched via pipeline.extract.get_chat_model_with_fallback (the
same fixture growth_ab.py itself imports).
"""

from unittest.mock import patch

from eval import growth_ab
from pipeline.schema import AccessoryType, AttrValue, ConnectorType, ProductAttributes
from surface.mcp_server import PublishedProduct

# ---------------------------------------------------------------------------
# Fixture catalog -- deliberately includes a universal-compat SKU, a
# model-specific SKU, a redacted/null-connector SKU, and a plain
# category-only SKU, so every branch of resolve_intent_structured is
# exercised.
# ---------------------------------------------------------------------------


def _published(**overrides) -> dict[str, PublishedProduct]:
    catalog = {
        "SKU-CABLE-UNIVERSAL": PublishedProduct(
            sku_id="SKU-CABLE-UNIVERSAL", title="Universal USB-C Cable", category="cable",
            attributes=ProductAttributes(
                accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9),
                model_compat=AttrValue(value=[], confidence=0.9),  # explicit universal
                connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.9),
            ),
            price_paise=19900,
        ),
        "SKU-CABLE-SPECIFIC": PublishedProduct(
            sku_id="SKU-CABLE-SPECIFIC", title="Samsung J7 Cable", category="cable",
            attributes=ProductAttributes(
                accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9),
                model_compat=AttrValue(value=["samsung_galaxy_j7"], confidence=0.9),
                connector_type=AttrValue(value=ConnectorType.MICRO_USB, confidence=0.9),
            ),
            price_paise=14900,
        ),
        "SKU-CHARGER-40W": PublishedProduct(
            sku_id="SKU-CHARGER-40W", title="40W Fast Charger", category="charger",
            attributes=ProductAttributes(
                accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.9),
                wattage_w=AttrValue(value=40.0, confidence=0.9),
            ),
            price_paise=99900,
        ),
        "SKU-CASE-PLAIN": PublishedProduct(
            sku_id="SKU-CASE-PLAIN", title="Plain Phone Case", category="case",
            attributes=ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CASE, confidence=0.9)),
            price_paise=29900,
        ),
    }
    catalog.update(overrides)
    return catalog


def _intent(**kwargs) -> growth_ab.PurchaseIntent:
    defaults = {"intent_id": "intent-001", "text": "test intent", "source_sku_id": "SKU-X", "category": "cable"}
    defaults.update(kwargs)
    return growth_ab.PurchaseIntent(**defaults)


# ---------------------------------------------------------------------------
# resolve_intent_structured
# ---------------------------------------------------------------------------


def test_category_only_matches_every_sku_in_that_category():
    published = _published()
    matches = growth_ab.resolve_intent_structured(_intent(category="cable"), published)
    assert set(matches) == {"SKU-CABLE-UNIVERSAL", "SKU-CABLE-SPECIFIC"}


def test_universal_model_compat_matches_any_claimed_model():
    published = _published()
    matches = growth_ab.resolve_intent_structured(_intent(category="cable", model="oneplus_two"), published)
    assert "SKU-CABLE-UNIVERSAL" in matches
    assert "SKU-CABLE-SPECIFIC" not in matches  # doesn't support this specific model


def test_model_specific_only_matches_its_own_model():
    published = _published()
    matches = growth_ab.resolve_intent_structured(_intent(category="cable", model="samsung_galaxy_j7"), published)
    assert set(matches) == {"SKU-CABLE-UNIVERSAL", "SKU-CABLE-SPECIFIC"}


def test_wattage_constraint_excludes_insufficient_and_unknown():
    published = _published()
    matches = growth_ab.resolve_intent_structured(_intent(category="charger", min_wattage=25.0), published)
    assert matches == ["SKU-CHARGER-40W"]

    matches_too_high = growth_ab.resolve_intent_structured(_intent(category="charger", min_wattage=65.0), published)
    assert matches_too_high == []  # 40W doesn't meet 65W


def test_connector_constraint_excludes_null_connector_skus():
    """A SKU with connector_type redacted/unknown (None) must never satisfy
    a connector-specific intent -- fail closed, same as everywhere else in
    this project."""
    published = _published()
    matches = growth_ab.resolve_intent_structured(_intent(category="cable", connector="usb_c"), published)
    assert matches == ["SKU-CABLE-UNIVERSAL"]


def test_no_matching_category_returns_empty():
    published = _published()
    matches = growth_ab.resolve_intent_structured(_intent(category="power_bank"), published)
    assert matches == []


# ---------------------------------------------------------------------------
# build_intents
# ---------------------------------------------------------------------------


def test_build_intents_is_deterministic_given_a_seed():
    published = _published()
    a = growth_ab.build_intents(published, seed=42, n=3)
    b = growth_ab.build_intents(published, seed=42, n=3)
    assert a == b


def test_build_intents_source_sku_always_satisfies_its_own_intent():
    """The core ground-truth guarantee this whole harness relies on."""
    published = _published()
    intents = growth_ab.build_intents(published, seed=1, n=len(published))
    for intent in intents:
        matches = growth_ab.resolve_intent_structured(intent, published)
        assert intent.source_sku_id in matches


def test_build_intents_never_asserts_a_constraint_the_source_sku_lacks():
    published = _published()
    intents = growth_ab.build_intents(published, seed=7, n=len(published))
    by_sku = {i.source_sku_id: i for i in intents}
    assert by_sku["SKU-CASE-PLAIN"].model is None
    assert by_sku["SKU-CASE-PLAIN"].min_wattage is None
    assert by_sku["SKU-CASE-PLAIN"].connector is None


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------


def test_score_classifies_all_three_outcomes():
    intents = [_intent(intent_id="i1"), _intent(intent_id="i2"), _intent(intent_id="i3")]
    ground_truth = {"i1": ["SKU-A"], "i2": ["SKU-A"], "i3": ["SKU-A"]}
    picks = {"i1": "SKU-A", "i2": "SKU-WRONG", "i3": None}

    metrics = growth_ab.score(intents, picks, ground_truth)
    assert metrics.completions == 1
    assert metrics.wrong_items == 1
    assert metrics.dead_ends == 1
    assert metrics.completion_rate == metrics.wrong_item_rate == metrics.dead_end_rate == 1 / 3


def test_score_any_ground_truth_member_counts_as_completion():
    intents = [_intent(intent_id="i1")]
    ground_truth = {"i1": ["SKU-A", "SKU-B"]}
    metrics = growth_ab.score(intents, {"i1": "SKU-B"}, ground_truth)
    assert metrics.completions == 1


# ---------------------------------------------------------------------------
# resolve_intents_raw -- cache + batching, no network.
# ---------------------------------------------------------------------------


class _FakeShoppingModel:
    def __init__(self, picks: dict[str, str | None]):
        self._picks = picks

    def invoke(self, prompt, config=None):
        return growth_ab.ShoppingBatchResponse(
            picks=[growth_ab.ShoppingPick(intent_id=iid, sku_id=sku) for iid, sku in self._picks.items()]
        )


def test_resolve_intents_raw_calls_llm_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(growth_ab, "CACHE_DIR", tmp_path / "cache")
    intents = [_intent(intent_id="i1", text="buy a cable")]
    catalog_rows = [{"sku_id": "SKU-A", "product_name": "Cable", "description": "A great cable."}]

    fake_model = _FakeShoppingModel({"i1": "SKU-A"})
    with patch("eval.growth_ab.get_chat_model_with_fallback", return_value=fake_model) as mock_get_model:
        results = growth_ab.resolve_intents_raw(intents, catalog_rows)
    assert results == {"i1": "SKU-A"}
    mock_get_model.assert_called_once()

    # second call: fully cached, LLM never invoked
    with patch("eval.growth_ab.get_chat_model_with_fallback") as mock_get_model_2:
        results_2 = growth_ab.resolve_intents_raw(intents, catalog_rows)
    assert results_2 == {"i1": "SKU-A"}
    mock_get_model_2.assert_not_called()


def test_resolve_intents_raw_batches_across_multiple_requests(monkeypatch, tmp_path):
    monkeypatch.setattr(growth_ab, "CACHE_DIR", tmp_path / "cache")
    intents = [_intent(intent_id=f"i{n}", text=f"intent {n}") for n in range(5)]
    catalog_rows = [{"sku_id": "SKU-A", "product_name": "Cable", "description": "desc"}]

    call_count = 0

    def fake_get_model(component, output_schema=None):
        nonlocal call_count
        call_count += 1
        return _FakeShoppingModel({})  # no picks -- every intent misses, that's fine for counting calls

    with patch("eval.growth_ab.get_chat_model_with_fallback", side_effect=fake_get_model):
        growth_ab.resolve_intents_raw(intents, catalog_rows, batch_size=2)
    assert call_count == 3  # ceil(5/2)


def test_resolve_intents_raw_missing_pick_defaults_to_none(monkeypatch, tmp_path):
    monkeypatch.setattr(growth_ab, "CACHE_DIR", tmp_path / "cache")
    intents = [_intent(intent_id="i1")]
    catalog_rows = [{"sku_id": "SKU-A", "product_name": "Cable", "description": "desc"}]
    with patch("eval.growth_ab.get_chat_model_with_fallback", return_value=_FakeShoppingModel({})):
        results = growth_ab.resolve_intents_raw(intents, catalog_rows)
    assert results == {"i1": None}


# ---------------------------------------------------------------------------
# _catalog_listing_text
# ---------------------------------------------------------------------------


def test_catalog_listing_text_caps_snippet_length():
    long_desc = "x" * 500
    rows = [{"sku_id": "SKU-A", "product_name": "Title", "description": long_desc}]
    text = growth_ab._catalog_listing_text(rows)
    assert "SKU-A: Title" in text
    snippet = text.split("--", 1)[1].strip()
    assert len(snippet) <= growth_ab.RAW_SNIPPET_CHARS
