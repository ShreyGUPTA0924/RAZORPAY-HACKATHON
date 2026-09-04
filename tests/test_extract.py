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


def test_pick_field_to_verify_chooses_lowest_confidence():
    """Not the highest -- a field the model is already very sure of gets
    the same answer again on a second independent pass almost every time,
    so disagreement (the only thing that can trigger quarantine) never
    fires there. See _pick_field_to_verify's docstring."""
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.6),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.95),
    )
    assert extract._pick_field_to_verify(attrs) == "accessory_type"


def test_pick_field_to_verify_ignores_null_fields():
    attrs = ProductAttributes(accessory_type=AttrValue(value=None, confidence=0.9))
    assert extract._pick_field_to_verify(attrs) is None


def test_pick_field_to_verify_returns_none_when_everything_null():
    assert extract._pick_field_to_verify(ProductAttributes()) is None


# ---------------------------------------------------------------------------
# _pick_second_field_to_verify
# ---------------------------------------------------------------------------


def test_pick_second_field_to_verify_excludes_the_given_field():
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.6),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.95),
    )
    picked = extract._pick_second_field_to_verify(attrs, exclude="connector_type")
    assert picked == "accessory_type"


def test_pick_second_field_to_verify_none_when_no_other_candidates():
    attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.6))
    assert extract._pick_second_field_to_verify(attrs, exclude="accessory_type") is None


def test_pick_second_field_to_verify_ignores_null_fields():
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.6),
        connector_type=AttrValue(value=None, confidence=0.0),
    )
    assert extract._pick_second_field_to_verify(attrs, exclude="accessory_type") is None


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
# run_self_verification(verify_second_field=True) / add_second_verification
# -- the fallback for when quarantine stays 0 despite real disagreements,
# because accessory_type (the only field quarantine looks at) is essentially
# never the lowest-confidence field.
# ---------------------------------------------------------------------------


def test_verify_second_field_checks_a_different_field_from_the_primary():
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.95),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.6),  # lowest -- primary pick
    )
    with patch("pipeline.extract.self_verify_field", side_effect=[ConnectorType.USB_C, AccessoryType.CHARGER]):
        sv = extract.run_self_verification("SKU-X", "title", "desc", attrs, verify_second_field=True)

    assert sv.field_checked == "connector_type"
    assert sv.extra_check is not None
    assert sv.extra_check.field_checked == "accessory_type"


def test_verify_second_field_disagreement_lowers_that_fields_confidence_independently():
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.95),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.6),
    )
    with patch("pipeline.extract.self_verify_field", side_effect=[ConnectorType.USB_C, AccessoryType.CASE]):
        sv = extract.run_self_verification("SKU-X", "title", "desc", attrs, verify_second_field=True)

    assert sv.agreed is True  # primary (connector_type) still agreed
    assert attrs.connector_type.confidence == 0.6  # unchanged
    assert sv.extra_check.agreed is False
    assert attrs.accessory_type.confidence == pytest.approx(0.95 * extract.DISAGREEMENT_CONFIDENCE_FACTOR)


def test_verify_second_field_skipped_when_no_other_non_null_field_exists():
    attrs = ProductAttributes(connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.6))
    with patch("pipeline.extract.self_verify_field", return_value=ConnectorType.USB_C):
        sv = extract.run_self_verification("SKU-X", "title", "desc", attrs, verify_second_field=True)
    assert sv.extra_check is None


def test_verify_second_field_defaults_to_off():
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.95),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.6),
    )
    with patch("pipeline.extract.self_verify_field", return_value=ConnectorType.USB_C):
        sv = extract.run_self_verification("SKU-X", "title", "desc", attrs)
    assert sv.extra_check is None


def test_add_second_verification_upgrades_an_existing_primary_check():
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.95),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.6),
    )
    sv = extract.SelfVerification(field_checked="connector_type", first_value="usb_c", agreed=True, confidence_before=0.6, confidence_after=0.6)
    with patch("pipeline.extract.self_verify_field", return_value=AccessoryType.CHARGER) as mock_verify:
        updated = extract.add_second_verification("SKU-X", "title", "desc", attrs, sv)

    mock_verify.assert_called_once()
    assert updated.extra_check.field_checked == "accessory_type"
    assert updated.extra_check.agreed is True


def test_add_second_verification_is_a_no_op_if_already_has_extra_check():
    """Guards against re-spending quota on a re-run: an entry that already
    has a second check must not be checked again."""
    existing = extract.FieldCheck(
        field_checked="accessory_type", first_value="charger", second_value="charger",
        agreed=True, confidence_before=0.95, confidence_after=0.95,
    )
    sv = extract.SelfVerification(field_checked="connector_type", agreed=True, extra_check=existing)
    attrs = ProductAttributes(connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.6))
    with patch("pipeline.extract.self_verify_field") as mock_verify:
        updated = extract.add_second_verification("SKU-X", "title", "desc", attrs, sv)

    mock_verify.assert_not_called()
    assert updated.extra_check is existing


def test_add_second_verification_is_a_no_op_if_nothing_was_ever_checked():
    sv = extract.SelfVerification()  # field_checked is None -- nothing to upgrade
    with patch("pipeline.extract.self_verify_field") as mock_verify:
        updated = extract.add_second_verification("SKU-X", "title", "desc", ProductAttributes(), sv)
    mock_verify.assert_not_called()
    assert updated.extra_check is None


# ---------------------------------------------------------------------------
# run_title_only_cross_check -- the mandatory, unconditional accessory_type
# defense. Unlike SelfVerification, this runs regardless of confidence: it
# exists specifically because a real adversarial attack relabeled a cable
# "power_bank" via the description alone, at HIGH confidence (0.9+) -- a
# case the lowest-confidence self-verification check structurally cannot
# reach, since accessory_type is rarely the lowest-confidence field. See
# docs/what-broke.md.
# ---------------------------------------------------------------------------


def test_title_only_agreement_leaves_confidence_unchanged():
    attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.95))
    with patch("pipeline.extract.self_verify_field", return_value=AccessoryType.CABLE):
        check = extract.run_title_only_cross_check("SKU-X", "title", attrs)
    assert check.agreed is True
    assert attrs.accessory_type.confidence == 0.95
    assert check.confidence_after == 0.95


def test_title_only_disagreement_hard_drops_confidence_regardless_of_how_high_it_was():
    """The exact scenario this check was built to catch: a HIGH-confidence
    claim (0.95) that a title-only read contradicts. A multiplicative
    factor (0.95 * 0.4 = 0.38) would already clear most reasonable
    thresholds by luck; the hard floor doesn't leave that to arithmetic."""
    attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.POWER_BANK, confidence=0.95))
    with patch("pipeline.extract.self_verify_field", return_value=AccessoryType.CABLE):
        check = extract.run_title_only_cross_check("SKU-X", "Generix OTG for Sony Xperia M5 OTG Cable", attrs)
    assert check.agreed is False
    assert attrs.accessory_type.confidence == extract.TITLE_ONLY_HARD_DROP_CONFIDENCE
    assert check.confidence_after == extract.TITLE_ONLY_HARD_DROP_CONFIDENCE
    assert check.confidence_before == 0.95
    assert check.title_only_value == AccessoryType.CABLE
    assert check.full_text_value == AccessoryType.POWER_BANK


def test_title_only_check_skipped_when_accessory_type_is_null():
    attrs = ProductAttributes()  # accessory_type never determined
    with patch("pipeline.extract.self_verify_field") as mock_verify:
        check = extract.run_title_only_cross_check("SKU-X", "title", attrs)
    mock_verify.assert_not_called()
    assert check.agreed is None


def test_title_only_check_uses_title_alone_no_description():
    """Confirms the whole point of the check: self_verify_field is called
    with an empty description, so a poisoned or misleading description
    cannot influence this specific call."""
    attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9))
    with patch("pipeline.extract.self_verify_field", return_value=AccessoryType.CABLE) as mock_verify:
        extract.run_title_only_cross_check("SKU-X", "My Title", attrs)
    mock_verify.assert_called_once_with("SKU-X", "My Title", "", "accessory_type")


def test_finish_with_self_verification_runs_both_checks_and_preserves_both_results():
    attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9))
    with patch("pipeline.extract.self_verify_field", return_value=AccessoryType.CABLE):
        result = extract.finish_with_self_verification("SKU-X", "title", "desc", attrs)
    assert result.error is None
    assert result.self_verification.field_checked == "accessory_type"
    assert result.title_only_check.agreed is True


def test_finish_with_self_verification_title_only_disagreement_quarantine_worthy():
    """End-to-end: a description-driven mislabel survives self-verification
    (which never looks at accessory_type here, since it's the SKU's only
    field and self-verification would pick it too -- so this test forces a
    second, DIFFERENT field to be primary-checked) but gets caught by the
    title-only cross-check and pushed below any reasonable quarantine
    threshold."""
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.POWER_BANK, confidence=0.95),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.5),  # lowest -- self-verification picks this instead
    )

    def fake_self_verify(sku_id, title, description, field_name):
        if field_name == "connector_type":
            return ConnectorType.USB_C  # agrees -- self-verification alone finds nothing wrong
        return AccessoryType.CABLE  # the title-only check's independent read

    with patch("pipeline.extract.self_verify_field", side_effect=fake_self_verify):
        result = extract.finish_with_self_verification("SKU-X", "Generix OTG Cable", "desc", attrs)

    assert result.self_verification.agreed is True  # self-verification alone missed it
    assert result.title_only_check.agreed is False  # title-only check caught it
    assert result.attributes.accessory_type.confidence == extract.TITLE_ONLY_HARD_DROP_CONFIDENCE


def test_title_only_disagreement_actually_quarantines_the_sku():
    """The real, tangible security outcome, not just a confidence number:
    feeding the post-check attributes through the ACTUAL
    pipeline.quarantine.evaluate() must quarantine the whole SKU. This is
    the fix for a confirmed adversarial finding -- a cable relabeled
    power_bank via the description alone survived at 0.9+ confidence
    before this check existed; see docs/what-broke.md."""
    from pipeline.quarantine import evaluate as quarantine_evaluate

    attrs = ProductAttributes(accessory_type=AttrValue(value=AccessoryType.POWER_BANK, confidence=0.95))
    with patch("pipeline.extract.self_verify_field", return_value=AccessoryType.CABLE):
        extract.run_title_only_cross_check("SKU-054", "Generix OTG for Sony Xperia M5 OTG Cable", attrs)

    decision = quarantine_evaluate("SKU-054", attrs)
    assert decision.published is False


# ---------------------------------------------------------------------------
# extract_sku -- get_chat_model_with_fallback is mocked, no network.
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
    with patch("pipeline.extract.get_chat_model_with_fallback", return_value=_FakeModel(exc=RuntimeError("boom"))):
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

    with patch("pipeline.extract.get_chat_model_with_fallback", side_effect=fake_get_chat_model):
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

    with patch("pipeline.extract.get_chat_model_with_fallback", side_effect=fake_get_chat_model):
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
