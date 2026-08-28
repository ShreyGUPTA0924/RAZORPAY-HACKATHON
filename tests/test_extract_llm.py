"""
Real-LLM sanity checks: fabricated product listings with one obvious,
unambiguous correct answer per field being tested. These are NOT drawn from
data/catalog.json or eval/ground_truth/ -- mixing them in would contaminate
either the real catalog or the held-out eval set. Their only job is "does
the extractor get the easy cases right and abstain on the impossible one,"
not precision/recall -- that's what eval/extraction_eval.py against the real
held-out set is for.

Skipped automatically without GOOGLE_API_KEY. Run explicitly with:
    pytest tests/test_extract_llm.py -v
Excluded from a fast default loop with:
    pytest -m "not llm"
"""

import os

import pytest
from dotenv import load_dotenv

from pipeline.extract import extract_sku
from pipeline.quarantine import evaluate as quarantine_evaluate

load_dotenv()  # so the skipif below sees GOOGLE_API_KEY from .env, not just a real env var

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not os.environ.get("GOOGLE_API_KEY"), reason="GOOGLE_API_KEY not set"),
]


def _model_compat_text(attrs) -> str:
    """model_compat's own schema description asks for a snake_case-ish
    canonical form (e.g. 'samsung_galaxy_j7'), not free text -- normalize
    underscores to spaces so assertions don't depend on which the model
    picked."""
    return " ".join(attrs.model_compat.value or []).lower().replace("_", " ")


def test_screen_protector_obvious_case():
    result = extract_sku(
        "SYN-1",
        "Nillkin Tempered Glass Screen Protector for Samsung Galaxy S10",
        "This tempered glass screen protector is precision-cut for the Samsung Galaxy S10. "
        "9H hardness, scratch resistant, easy bubble-free installation.",
    )
    assert result.error is None
    assert result.attributes.accessory_type.value == "screen_protector"
    assert result.attributes.material.value == "tempered_glass"
    assert "samsung" in _model_compat_text(result.attributes)


def test_usb_c_cable_obvious_case():
    result = extract_sku(
        "SYN-2",
        "FastCharge USB Type-C Braided Cable, 1 Meter",
        "A durable braided USB Type-C charging and data cable. Plug the USB Type-C end into "
        "your device for fast charging up to 3A.",
    )
    assert result.error is None
    assert result.attributes.accessory_type.value == "cable"
    assert result.attributes.connector_type.value == "usb_c"


def test_wireless_power_bank_obvious_case():
    result = extract_sku(
        "SYN-3",
        "PowerMax 10000mAh Wireless Power Bank",
        "This power bank has a battery capacity of 10000mAh and supports Qi wireless charging -- "
        "just place your phone on top, no cable needed.",
    )
    assert result.error is None
    assert result.attributes.accessory_type.value == "power_bank"
    assert result.attributes.capacity_mah.value == 10000
    assert result.attributes.wireless_charging.value is True


def test_leather_case_with_specific_model_obvious_case():
    result = extract_sku(
        "SYN-4",
        "Premium Leather Flip Case for iPhone 12",
        "Made from genuine leather, this flip case is designed specifically to fit the Apple iPhone 12.",
    )
    assert result.error is None
    assert result.attributes.accessory_type.value == "case"
    assert result.attributes.material.value == "leather"
    assert "iphone 12" in _model_compat_text(result.attributes)


def test_universal_bluetooth_headphones_empty_list_not_null():
    """model_compat=[] (confident 'fits anything') must be distinguishable
    from model_compat=None (unknown) -- see pipeline/schema.py."""
    result = extract_sku(
        "SYN-5",
        "SoundMax Bluetooth Wireless Earphones",
        "These wireless earphones connect via Bluetooth and work with any smartphone on the market.",
    )
    assert result.error is None
    assert result.attributes.accessory_type.value == "headphone"
    assert result.attributes.connector_type.value == "bluetooth"
    assert result.attributes.model_compat.value == []


def test_uninformative_listing_abstains_and_gets_quarantined():
    """The core 'never guess' requirement: a listing with no real content
    must come back mostly null/low-confidence, not plausible-sounding
    fabrications -- and quarantine.evaluate() must refuse to publish it."""
    result = extract_sku(
        "SYN-6",
        "XYZ Product 12345",
        "Good quality. Fast delivery. 100% genuine product. Buy now!",
    )
    assert result.error is None
    assert result.attributes.accessory_type.value is None
    decision = quarantine_evaluate("SYN-6", result.attributes)
    assert not decision.published
