"""
Mocked unit tests for pipeline/extract.py's Block B additions: batching,
disk-cache integration, and the shared self-verification tail. No network.
"""

import json
from unittest.mock import patch

from pipeline import extract, extract_cache
from pipeline.schema import AccessoryType, AttrValue, ConnectorType, ProductAttributes


def test_chunks_splits_evenly():
    assert list(extract._chunks([1, 2, 3, 4, 5, 6], 2)) == [[1, 2], [3, 4], [5, 6]]


def test_chunks_last_chunk_can_be_smaller():
    assert list(extract._chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_chunks_empty_input():
    assert list(extract._chunks([], 3)) == []


def test_build_batch_user_message_includes_every_sku_with_its_own_id():
    rows = [("SKU-1", "Title One", "Desc one"), ("SKU-2", "Title Two", "Desc two")]
    msg = extract.build_batch_user_message(rows)
    assert "SKU: SKU-1" in msg
    assert "SKU: SKU-2" in msg
    assert "Title One" in msg
    assert "Desc two" in msg


def test_batch_system_prompt_includes_independence_instruction():
    prompt = extract.build_batch_system_prompt()
    assert "independently" in prompt.lower()
    assert "leak" in prompt.lower()


class _FakeBatchModel:
    def __init__(self, response):
        self._response = response

    def invoke(self, *args, **kwargs):
        return self._response


def test_extract_primary_batch_maps_results_by_sku_id():
    attrs1 = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9))
    attrs2 = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CASE, confidence=0.8))
    response = extract.BatchExtractionResponse(
        items=[
            extract.BatchItem(sku_id="SKU-1", attributes=attrs1),
            extract.BatchItem(sku_id="SKU-2", attributes=attrs2),
        ]
    )
    rows = [("SKU-1", "t1", "d1"), ("SKU-2", "t2", "d2")]
    with patch("pipeline.extract.get_chat_model_with_fallback", return_value=_FakeBatchModel(response)):
        results = extract.extract_primary_batch(rows, batch_size=8)

    assert results["SKU-1"].accessory_type.value == AccessoryType.CABLE
    assert results["SKU-2"].accessory_type.value == AccessoryType.CASE


def test_extract_primary_batch_missing_sku_maps_to_none():
    """A SKU the model just didn't return is a batch-level miss, not
    silently defaulted to empty attributes."""
    response = extract.BatchExtractionResponse(items=[])
    rows = [("SKU-1", "t1", "d1")]
    with patch("pipeline.extract.get_chat_model_with_fallback", return_value=_FakeBatchModel(response)):
        results = extract.extract_primary_batch(rows, batch_size=8)
    assert results["SKU-1"] is None


def test_extract_primary_batch_splits_into_multiple_requests():
    call_count = 0

    def fake_get_chat_model(component, output_schema=None):
        nonlocal call_count
        call_count += 1
        return _FakeBatchModel(extract.BatchExtractionResponse(items=[]))

    rows = [(f"SKU-{i}", f"t{i}", f"d{i}") for i in range(5)]
    with patch("pipeline.extract.get_chat_model_with_fallback", side_effect=fake_get_chat_model):
        extract.extract_primary_batch(rows, batch_size=2)
    assert call_count == 3  # ceil(5/2)


def test_finish_with_self_verification_none_attrs_is_an_error():
    result = extract.finish_with_self_verification("SKU-1", "t", "d", None)
    assert result.error is not None
    assert "missing from batch response" in result.error


def test_finish_with_self_verification_runs_verification_on_real_attrs():
    attrs = ProductAttributes(connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.9))
    with patch("pipeline.extract.self_verify_field", return_value=ConnectorType.USB_C):
        result = extract.finish_with_self_verification("SKU-1", "t", "d", attrs)
    assert result.error is None
    assert result.self_verification.field_checked == "connector_type"
    assert result.self_verification.agreed is True


# ---------------------------------------------------------------------------
# run_batch cache integration
# ---------------------------------------------------------------------------


def _write_catalog(tmp_path, rows):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_run_batch_skips_llm_entirely_on_full_cache_hit(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path / "cache")
    catalog_path = _write_catalog(
        tmp_path, [{"sku_id": "SKU-1", "product_name": "Title", "description": "Desc"}]
    )

    cached_attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9))
    key = extract_cache.cache_key("SKU-1", extract.trim_boilerplate("Desc"), extract.PROMPT_VERSION, "gemini-2.5-flash")
    extract_cache.put(
        key,
        {
            "attributes": cached_attrs.model_dump(mode="json"),
            "self_verification": {"field_checked": None, "first_value": None, "second_value": None, "agreed": None, "confidence_before": None, "confidence_after": None},
            "self_verify_version": extract.SELF_VERIFY_VERSION,
        },
    )

    with patch("pipeline.extract.extract_primary_batch") as mock_batch, patch("pipeline.extract.configure_tracing"):
        results = extract.run_batch(catalog_path=catalog_path)

    mock_batch.assert_not_called()
    assert results[0].attributes.accessory_type.value == AccessoryType.CABLE


def test_run_batch_reverifies_only_on_stale_self_verify_version(monkeypatch, tmp_path):
    """A cache entry from before a self-verification logic change (no
    self_verify_version, or an old one) has trustworthy attrs but a stale
    self_verification -- run_batch must redo ONLY self-verification (no
    primary extraction call) and persist the corrected entry."""
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path / "cache")
    catalog_path = _write_catalog(tmp_path, [{"sku_id": "SKU-1", "product_name": "Title", "description": "Desc"}])

    cached_attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9))
    key = extract_cache.cache_key("SKU-1", extract.trim_boilerplate("Desc"), extract.PROMPT_VERSION, "gemini-2.5-flash")
    extract_cache.put(
        key,
        {
            "attributes": cached_attrs.model_dump(mode="json"),
            "self_verification": {"field_checked": None, "first_value": None, "second_value": None, "agreed": None, "confidence_before": None, "confidence_after": None},
            "self_verify_version": "v1-highest-confidence-stale",
        },
    )

    fresh_sv = extract.SelfVerification(field_checked="accessory_type", agreed=True)
    with (
        patch("pipeline.extract.extract_primary_batch") as mock_batch,
        patch("pipeline.extract.run_self_verification", return_value=fresh_sv) as mock_verify,
        patch("pipeline.extract.configure_tracing"),
    ):
        results = extract.run_batch(catalog_path=catalog_path)

    mock_batch.assert_not_called()  # attrs came from cache, no primary extraction spent
    mock_verify.assert_called_once()
    assert results[0].attributes.accessory_type.value == AccessoryType.CABLE  # attrs preserved
    assert results[0].self_verification.field_checked == "accessory_type"

    updated = extract_cache.get(key)
    assert updated["self_verify_version"] == extract.SELF_VERIFY_VERSION  # re-cached with current version


def test_run_batch_adds_only_second_check_when_primary_already_valid(monkeypatch, tmp_path):
    """verify_two_fields=True against an entry whose primary check is
    already current (matching self_verify_version) must add ONLY the
    second/random check -- no primary re-extraction, no full re-verify."""
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path / "cache")
    catalog_path = _write_catalog(tmp_path, [{"sku_id": "SKU-1", "product_name": "Title", "description": "Desc"}])

    cached_attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.5),
    )
    key = extract_cache.cache_key("SKU-1", extract.trim_boilerplate("Desc"), extract.PROMPT_VERSION, "gemini-2.5-flash")
    extract_cache.put(
        key,
        {
            "attributes": cached_attrs.model_dump(mode="json"),
            "self_verification": {
                "field_checked": "connector_type", "first_value": "usb_c", "second_value": "usb_c",
                "agreed": True, "confidence_before": 0.5, "confidence_after": 0.5, "extra_check": None,
            },
            "self_verify_version": extract.SELF_VERIFY_VERSION,
        },
    )

    extra = extract.FieldCheck(
        field_checked="accessory_type", first_value="cable", second_value="cable",
        agreed=True, confidence_before=0.9, confidence_after=0.9,
    )
    with (
        patch("pipeline.extract.extract_primary_batch") as mock_batch,
        patch("pipeline.extract.run_self_verification") as mock_run_sv,
        patch("pipeline.extract.add_second_verification", return_value=extract.SelfVerification(field_checked="connector_type", agreed=True, extra_check=extra)) as mock_add_second,
        patch("pipeline.extract.configure_tracing"),
    ):
        results = extract.run_batch(catalog_path=catalog_path, verify_two_fields=True)

    mock_batch.assert_not_called()
    mock_run_sv.assert_not_called()
    mock_add_second.assert_called_once()
    assert results[0].self_verification.extra_check.field_checked == "accessory_type"

    updated = extract_cache.get(key)
    assert updated["self_verification"]["extra_check"]["field_checked"] == "accessory_type"


def test_run_batch_caches_successful_new_extractions(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path / "cache")
    catalog_path = _write_catalog(
        tmp_path, [{"sku_id": "SKU-1", "product_name": "Title", "description": "Desc"}]
    )
    attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.HEADPHONE, confidence=0.9))

    def fake_extract_primary_batch(rows, batch_size):
        return {"SKU-1": attrs}

    with (
        patch("pipeline.extract.extract_primary_batch", side_effect=fake_extract_primary_batch),
        patch("pipeline.extract.run_self_verification", return_value=extract.SelfVerification()),
        patch("pipeline.extract.configure_tracing"),
    ):
        extract.run_batch(catalog_path=catalog_path)

    key = extract_cache.cache_key("SKU-1", extract.trim_boilerplate("Desc"), extract.PROMPT_VERSION, "gemini-2.5-flash")
    cached = extract_cache.get(key)
    assert cached is not None
    assert cached["attributes"]["accessory_type"]["value"] == "headphone"


def test_run_batch_force_ignores_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(extract_cache, "CACHE_DIR", tmp_path / "cache")
    catalog_path = _write_catalog(
        tmp_path, [{"sku_id": "SKU-1", "product_name": "Title", "description": "Desc"}]
    )
    key = extract_cache.cache_key("SKU-1", extract.trim_boilerplate("Desc"), extract.PROMPT_VERSION, "gemini-2.5-flash")
    extract_cache.put(key, {"attributes": ProductAttributes().model_dump(mode="json"), "self_verification": {"field_checked": None, "first_value": None, "second_value": None, "agreed": None, "confidence_before": None, "confidence_after": None}})

    with (
        patch("pipeline.extract.extract_primary_batch", return_value={"SKU-1": ProductAttributes()}) as mock_batch,
        patch("pipeline.extract.run_self_verification", return_value=extract.SelfVerification()),
        patch("pipeline.extract.configure_tracing"),
    ):
        extract.run_batch(catalog_path=catalog_path, force=True)

    mock_batch.assert_called_once()
