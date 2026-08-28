"""
Fast, mocked unit tests for pipeline/extract.py's logic -- prompt
construction, self-verification comparison, error handling. No network
calls, no API key required; these must run in any environment.

Real-LLM sanity checks against synthetic obvious-answer listings live
separately in tests/test_extract_llm.py (skipped without an API key).
"""

from unittest.mock import patch

import pytest

from pipeline import extract
from pipeline.schema import AccessoryType, AttrValue, ConnectorType, ProductAttributes

# ---------------------------------------------------------------------------
# strip_spec_block
# ---------------------------------------------------------------------------


def test_strip_spec_block_truncates_at_marker():
    text = "Great cable for your phone. Specifications of Foo General Brand Foo"
    assert extract.strip_spec_block(text) == "Great cable for your phone."


def test_strip_spec_block_is_a_no_op_without_marker():
    text = "Great cable for your phone, no spec dump here."
    assert extract.strip_spec_block(text) == text


# ---------------------------------------------------------------------------
# _values_match
# ---------------------------------------------------------------------------


def test_values_match_case_insensitive_strings():
    assert extract._values_match("USB-C", "usb-c")


def test_values_match_set_based_lists():
    assert extract._values_match(["A", "b"], ["B", "a"])
    assert not extract._values_match(["A"], ["B"])


def test_values_match_enum_by_value():
    assert extract._values_match(ConnectorType.USB_C, "usb_c")


# ---------------------------------------------------------------------------
# _pick_field_to_verify
# ---------------------------------------------------------------------------


def test_pick_field_to_verify_chooses_highest_confidence():
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.6),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.95),
    )
    assert extract._pick_field_to_verify(attrs) == "connector_type"


def test_pick_field_to_verify_ignores_null_fields():
    attrs = ProductAttributes(accessory_type=AttrValue(value=None, confidence=0.9))
    assert extract._pick_field_to_verify(attrs) is None


def test_pick_field_to_verify_returns_none_when_everything_null():
    assert extract._pick_field_to_verify(ProductAttributes()) is None


# ---------------------------------------------------------------------------
# run_self_verification -- self_verify_field is mocked, no network.
# ---------------------------------------------------------------------------


def test_self_verification_lowers_confidence_on_disagreement():
    attrs = ProductAttributes(connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.9))
    with patch("pipeline.extract.self_verify_field", return_value=ConnectorType.MICRO_USB):
        sv = extract.run_self_verification("SKU-X", "title", "desc", attrs)

    assert sv.field_checked == "connector_type"
    assert sv.agreed is False
    assert attrs.connector_type.confidence == pytest.approx(0.9 * extract.DISAGREEMENT_CONFIDENCE_FACTOR)
    assert sv.confidence_after == attrs.connector_type.confidence


def test_self_verification_leaves_confidence_unchanged_on_agreement():
    attrs = ProductAttributes(connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.9))
    with patch("pipeline.extract.self_verify_field", return_value=ConnectorType.USB_C):
        sv = extract.run_self_verification("SKU-X", "title", "desc", attrs)

    assert sv.agreed is True
    assert attrs.connector_type.confidence == 0.9


def test_self_verification_skipped_when_nothing_to_check():
    sv = extract.run_self_verification("SKU-X", "title", "desc", ProductAttributes())
    assert sv.field_checked is None
    assert sv.agreed is None


# ---------------------------------------------------------------------------
# extract_sku -- get_chat_model is mocked, no network.
# ---------------------------------------------------------------------------


class _FakeModel:
    def __init__(self, return_value=None, exc=None):
        self._return_value = return_value
        self._exc = exc

    def invoke(self, *args, **kwargs):
        if self._exc:
            raise self._exc
        return self._return_value


def test_extract_sku_handles_primary_call_failure_without_raising():
    with patch("pipeline.extract.get_chat_model", return_value=_FakeModel(exc=RuntimeError("boom"))):
        result = extract.extract_sku("SKU-X", "title", "desc")

    assert result.error is not None
    assert "extraction call failed" in result.error
    assert result.attributes == ProductAttributes()


def test_extract_sku_keeps_primary_result_if_self_verification_fails():
    primary_attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9))

    def fake_get_chat_model(component, output_schema=None):
        if output_schema is ProductAttributes:
            return _FakeModel(return_value=primary_attrs)
        return _FakeModel(exc=RuntimeError("self-verify boom"))

    with patch("pipeline.extract.get_chat_model", side_effect=fake_get_chat_model):
        result = extract.extract_sku("SKU-X", "title", "desc")

    assert result.error is not None
    assert "self-verification call failed" in result.error
    assert result.attributes is primary_attrs  # not discarded


def test_extract_sku_success_runs_self_verification():
    primary_attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9))

    def fake_get_chat_model(component, output_schema=None):
        if output_schema is ProductAttributes:
            return _FakeModel(return_value=primary_attrs)
        return _FakeModel(return_value=AttrValue(value=AccessoryType.CABLE, confidence=0.9))

    with patch("pipeline.extract.get_chat_model", side_effect=fake_get_chat_model):
        result = extract.extract_sku("SKU-X", "title", "desc")

    assert result.error is None
    assert result.self_verification.field_checked == "accessory_type"
    assert result.self_verification.agreed is True


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_system_prompt_mentions_every_field_and_its_enum_values():
    from pipeline.schema import ATTRIBUTE_FIELDS

    prompt = extract.build_system_prompt()
    for field_name in ATTRIBUTE_FIELDS:
        assert field_name in prompt
    assert "usb_c" in prompt
    assert "tempered_glass" in prompt


def test_user_message_includes_title_and_description():
    msg = extract.build_user_message("My Title", "My Description")
    assert "My Title" in msg
    assert "My Description" in msg
