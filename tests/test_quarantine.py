from pipeline.quarantine import evaluate, redact
from pipeline.schema import AccessoryType, AttrValue, ConnectorType, ProductAttributes


def make_attrs(**overrides) -> ProductAttributes:
    attrs = ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CHARGER, confidence=0.9),
        connector_type=AttrValue(value=ConnectorType.MICRO_USB, confidence=0.9),
    )
    for field_name, attr_value in overrides.items():
        setattr(attrs, field_name, attr_value)
    return attrs


def test_high_confidence_sku_is_published_with_nothing_redacted():
    attrs = make_attrs()
    decision = evaluate("SKU-1", attrs)
    assert decision.published
    assert decision.redacted_fields == []


def test_null_accessory_type_quarantines_whole_sku():
    attrs = make_attrs(accessory_type=AttrValue(value=None, confidence=0.0))
    decision = evaluate("SKU-1", attrs)
    assert not decision.published
    assert "accessory_type" in decision.reasons[0]


def test_low_confidence_accessory_type_quarantines_whole_sku_even_with_a_value():
    attrs = make_attrs(accessory_type=AttrValue(value=AccessoryType.CASE, confidence=0.2))
    decision = evaluate("SKU-1", attrs)
    assert not decision.published


def test_low_confidence_non_gating_field_is_redacted_but_sku_still_published():
    attrs = make_attrs(connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.1))
    decision = evaluate("SKU-1", attrs)
    assert decision.published
    assert decision.redacted_fields == ["connector_type"]
    assert any("connector_type" in r for r in decision.reasons)


def test_null_value_field_is_not_flagged_as_redacted():
    """A field the extractor never found (value=None) is already unpublished
    -- it's not a 'redaction' of a claim, there was no claim."""
    attrs = make_attrs(material=AttrValue(value=None, confidence=0.0))
    decision = evaluate("SKU-1", attrs)
    assert "material" not in decision.redacted_fields


def test_redact_zeroes_quarantined_whole_sku():
    attrs = make_attrs(accessory_type=AttrValue(value=None, confidence=0.0))
    decision = evaluate("SKU-1", attrs)
    published = redact(attrs, decision)
    assert published.accessory_type.value is None
    assert published.connector_type.value is None


def test_redact_only_nulls_out_redacted_fields_on_published_sku():
    attrs = make_attrs(connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.1))
    decision = evaluate("SKU-1", attrs)
    published = redact(attrs, decision)
    assert published.connector_type.value is None  # redacted
    assert published.accessory_type.value == AccessoryType.CHARGER  # untouched, high confidence


def test_custom_threshold_is_respected():
    attrs = make_attrs(connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.6))
    assert evaluate("SKU-1", attrs, threshold=0.5).redacted_fields == []
    assert evaluate("SKU-1", attrs, threshold=0.7).redacted_fields == ["connector_type"]
