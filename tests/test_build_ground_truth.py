"""
Unit tests for the Block A suggester-rule fixes in eval/build_ground_truth.py.
Pure functions, no catalog/network dependency.
"""

from eval.build_ground_truth import (
    has_structured_signal,
    suggest_model_compat,
    suggest_wireless_charging,
)

# ---------------------------------------------------------------------------
# A1: wireless_charging never infers False from absence.
# ---------------------------------------------------------------------------


def test_wireless_charging_none_when_nothing_indicates_it():
    specs = {"connectors": "micro, mini", "battery capacity": "10000 mah"}
    assert suggest_wireless_charging(specs, "power_bank") is None


def test_wireless_charging_true_on_dedicated_key():
    specs = {"wireless charging": "yes"}
    assert suggest_wireless_charging(specs, "charger") is True


def test_wireless_charging_true_on_value_mention():
    specs = {"model name": "Wireless 10000mAh Power bank"}
    assert suggest_wireless_charging(specs, "power_bank") is True


def test_wireless_charging_not_applicable_outside_relevant_types():
    specs = {"wireless charging": "yes"}  # even with a real signal
    assert suggest_wireless_charging(specs, "headphone") is None
    assert suggest_wireless_charging(specs, None) is None


# ---------------------------------------------------------------------------
# A2 + A3: model_compat rejects category words and falls through keys.
# ---------------------------------------------------------------------------


def test_model_compat_rejects_pure_category_value():
    specs = {"compatible devices": "Mobile"}
    accepted, rejected = suggest_model_compat(specs)
    assert accepted is None
    assert rejected == ["Mobile"]


def test_model_compat_accepts_a_real_model():
    specs = {"designed for": "Samsung Galaxy J7"}
    accepted, rejected = suggest_model_compat(specs)
    assert accepted == ["Samsung Galaxy J7"]
    assert rejected == []


def test_model_compat_prefers_specific_key_over_generic_one_present_together():
    """SKU-053's real shape: reordering alone resolves it -- "suitable for"
    is checked before "compatible devices" in DESIGNED_FOR_KEYS, so the
    specific value wins outright and "compatible devices" is never even
    reached (not a fall-through case)."""
    specs = {"compatible devices": "Mobile", "suitable for": "One Plus Two"}
    accepted, rejected = suggest_model_compat(specs)
    assert accepted == ["One Plus Two"]
    assert rejected == []  # "compatible devices" never examined -- resolved before reaching it


def test_model_compat_falls_through_when_the_first_key_in_order_is_category_only():
    """Real fall-through case: "designed for" is earlier in DESIGNED_FOR_KEYS
    than "compatible devices" but yields only a category word here, so the
    suggester must continue past it instead of giving up."""
    specs = {"designed for": "Mobile", "compatible devices": "Xiaomi Redmi Note 5"}
    accepted, rejected = suggest_model_compat(specs)
    assert accepted == ["Xiaomi Redmi Note 5"]
    assert rejected == ["Mobile"]


def test_model_compat_splits_and_filters_mixed_list():
    specs = {"designed for": "Samsung Galaxy J7, Mobile"}
    accepted, rejected = suggest_model_compat(specs)
    assert accepted == ["Samsung Galaxy J7"]
    assert rejected == ["Mobile"]


def test_model_compat_none_when_key_absent():
    assert suggest_model_compat({}) == (None, [])


# ---------------------------------------------------------------------------
# A4: has_structured_signal drives the scorable flag.
# ---------------------------------------------------------------------------


def test_has_structured_signal_true_when_a_mapped_key_present():
    assert has_structured_signal({"connector": "Micro USB"})


def test_has_structured_signal_false_for_unmapped_keys_only():
    # Brand/Model ID/Color are real spec keys in the raw data but not ones
    # this suggester maps to any schema field.
    assert not has_structured_signal({"brand": "Sound Logic", "model id": "X", "color": "Black"})


def test_has_structured_signal_false_when_no_specs_at_all():
    assert not has_structured_signal({})
