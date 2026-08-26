"""
Target attribute schema for the phone-accessories catalog (Mobiles &
Accessories: cases/pouches, screen protectors, cables/chargers, headphones,
power banks).

This is the contract the rest of the pipeline is built against:
- pipeline/extract.py fills a ProductAttributes from a raw catalog row.
- pipeline/canonical.py is what maps messy raw values onto the enums below.
- pipeline/quarantine.py reads AttrValue.confidence to decide publish vs hold.
- eval/ground_truth/labels_template.json uses exactly these field names (see
  scripts/build_eval_template.py, which imports ATTRIBUTE_FIELDS from here so
  the ground-truth keys and the pipeline's output keys can never drift apart).

Two schemas live in this file on purpose:
- ProductAttributes: what the PIPELINE produces. Every field carries its own
  confidence, because a single row can be confident about one attribute
  (e.g. connector_type stated in a spec key) and a pure guess about another
  (e.g. wattage never appearing anywhere in the row).
- GroundTruthAttributes: what the HUMAN LABELS. Plain values, no confidence --
  ground truth is definitionally certain. eval/extraction_eval.py compares
  ProductAttributes.<field>.value against GroundTruthAttributes.<field>.

No accessory in this catalog needs every field. A screen protector has no
wattage; a cable has no wireless_charging. Leaving a field null is normal,
not a sign of a bad extraction -- see accessory_type below for how a
consumer of this schema should decide which fields are even expected.
"""

from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Canonical enum vocabularies.
#
# These are the only values pipeline/canonical.py is allowed to emit. A raw
# value that can't be mapped onto one of these (with the required confidence)
# does not get force-fit into OTHER -- it gets quarantined. OTHER exists for
# cases where the source text is clear but the value is genuinely outside
# this catalog's vocabulary (e.g. a USB-B connector), not as a dumping
# ground for "the extractor gave up."
# ---------------------------------------------------------------------------


class AccessoryType(str, Enum):
    """What kind of product the row is. Determines which of the fields below
    are even applicable -- e.g. wattage only applies to CHARGER/POWER_BANK."""

    CASE = "case"  # rigid/flip/back cover
    POUCH = "pouch"  # soft sleeve/pouch
    SCREEN_PROTECTOR = "screen_protector"  # tempered glass / film guard
    CABLE = "cable"  # data/charging cable, OTG adapter
    CHARGER = "charger"  # wall/car charger, charging pad
    HEADPHONE = "headphone"  # wired or Bluetooth headset/earphone
    POWER_BANK = "power_bank"  # portable battery
    OTHER = "other"


class ConnectorType(str, Enum):
    """Physical (or radio) connection the accessory uses. One vocabulary
    covers both cable/charger connectors and headphone connections, since
    the underlying question -- "what does this plug into" -- is the same."""

    USB_A = "usb_a"
    MICRO_USB = "micro_usb"
    USB_C = "usb_c"
    LIGHTNING = "lightning"
    JACK_3_5MM = "3_5mm_jack"
    BLUETOOTH = "bluetooth"
    OTHER = "other"


class Material(str, Enum):
    """Primary build material, for cases/pouches/screen protectors."""

    PLASTIC = "plastic"
    SILICONE_TPU = "silicone_tpu"
    LEATHER = "leather"
    METAL = "metal"
    TEMPERED_GLASS = "tempered_glass"
    FABRIC_NYLON = "fabric_nylon"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Generic confidence-carrying value.
# ---------------------------------------------------------------------------


class AttrValue(BaseModel, Generic[T]):
    """One extracted field: the value the LLM proposed, and how sure it is.

    confidence is a bare float, not an enum bucket, because the quarantine
    threshold (pipeline/quarantine.py, Tier 1) needs a continuous score to
    threshold against -- collapsing to HIGH/MED/LOW here would just move the
    binning decision into this file instead of removing it.
    """

    value: T | None = None
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="0.0 = not found / pure guess, 1.0 = stated verbatim in the source text.",
    )


# ---------------------------------------------------------------------------
# Pipeline output schema.
# ---------------------------------------------------------------------------


class ProductAttributes(BaseModel):
    """Structured attributes the extraction agent produces for one SKU.

    Field order matters for readability only. Every field is Optional at the
    value level (via AttrValue) -- a field that doesn't apply to this
    accessory_type, or that the source text simply never states, is left
    with value=None and confidence=0.0 rather than a fabricated default.
    """

    accessory_type: AttrValue[AccessoryType] = Field(
        default_factory=AttrValue,
        description="What kind of product this is. Gates which other fields are expected.",
    )
    model_compat: AttrValue[list[str]] = Field(
        default_factory=AttrValue,
        description=(
            "Canonical phone model names this accessory fits, e.g. "
            "['samsung_galaxy_j7']. Empty list is a valid, confident answer "
            "for a genuinely universal accessory -- that is different from "
            "value=None, which means 'could not determine.'"
        ),
    )
    connector_type: AttrValue[ConnectorType] = Field(
        default_factory=AttrValue,
        description="Cable/charger connector, or headphone connection type.",
    )
    wattage_w: AttrValue[float] = Field(
        default_factory=AttrValue,
        description="Charging output in watts. Convert from V/A in source text if both are stated.",
    )
    capacity_mah: AttrValue[int] = Field(
        default_factory=AttrValue,
        description="Battery capacity in mAh. Power banks only.",
    )
    screen_size_in: AttrValue[float] = Field(
        default_factory=AttrValue,
        description="Diagonal screen size (inches) this case/protector is cut for.",
    )
    wireless_charging: AttrValue[bool] = Field(
        default_factory=AttrValue,
        description="Whether the accessory supports Qi/wireless charging.",
    )
    material: AttrValue[Material] = Field(
        default_factory=AttrValue,
        description="Primary build material.",
    )


# Field names, exported for reuse anywhere the same key set is needed without
# duplicating it by hand (currently: scripts/build_eval_template.py).
ATTRIBUTE_FIELDS: list[str] = list(ProductAttributes.model_fields.keys())


# ---------------------------------------------------------------------------
# Ground-truth schema (hand-labelled, held-out -- see eval/ground_truth/).
# ---------------------------------------------------------------------------


class GroundTruthAttributes(BaseModel):
    """What a human labeller fills in from raw text alone. No confidence
    field: ground truth is either a value or explicitly null (unknowable /
    not applicable), never a probability."""

    accessory_type: AccessoryType | None = None
    model_compat: list[str] | None = None
    connector_type: ConnectorType | None = None
    wattage_w: float | None = None
    capacity_mah: int | None = None
    screen_size_in: float | None = None
    wireless_charging: bool | None = None
    material: Material | None = None
