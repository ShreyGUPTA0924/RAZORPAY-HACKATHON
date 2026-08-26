import pytest
from pydantic import ValidationError

from pipeline.schema import (
    AccessoryType,
    AttrValue,
    ConnectorType,
    GroundTruthAttributes,
    Material,
    ProductAttributes,
)


def test_product_attributes_defaults_to_all_unknown():
    attrs = ProductAttributes()
    for field_name in ProductAttributes.model_fields:
        field_value = getattr(attrs, field_name)
        assert isinstance(field_value, AttrValue)
        assert field_value.value is None
        assert field_value.confidence == 0.0


def test_attr_value_confidence_is_bounded():
    attrs = ProductAttributes()
    attrs.connector_type.value = ConnectorType.USB_C
    attrs.connector_type.confidence = 1.0
    assert attrs.connector_type.value is ConnectorType.USB_C

    with pytest.raises(ValidationError):
        AttrValue(value=ConnectorType.USB_C, confidence=1.5)


def test_model_compat_empty_list_differs_from_none():
    universal = ProductAttributes(
        model_compat=AttrValue(value=[], confidence=0.9),
        accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9),
    )
    unknown = ProductAttributes()
    assert universal.model_compat.value == []
    assert unknown.model_compat.value is None


def test_ground_truth_has_no_confidence_field():
    gt = GroundTruthAttributes(accessory_type=AccessoryType.CHARGER, material=Material.PLASTIC)
    dumped = gt.model_dump()
    assert "confidence" not in dumped
    assert dumped["accessory_type"] == AccessoryType.CHARGER
    assert dumped["wattage_w"] is None
