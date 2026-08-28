from pipeline.schema import AttrValue, ConnectorType, ProductAttributes
from pipeline.verify import CompatibilityProposal, verify_proposal


def make_attrs(**overrides) -> ProductAttributes:
    attrs = ProductAttributes()
    for field_name, attr_value in overrides.items():
        setattr(attrs, field_name, attr_value)
    return attrs


# ---------------------------------------------------------------------------
# model_compat_match
# ---------------------------------------------------------------------------


def test_verified_when_claimed_model_is_in_model_compat():
    attrs = make_attrs(model_compat=AttrValue(value=["samsung_galaxy_j7"], confidence=0.99))
    proposal = CompatibilityProposal(sku_id="SKU-021", claimed_model="Samsung Galaxy J7", claimed_basis="model_compat_match")
    result = verify_proposal(proposal, attrs)
    assert result.verified
    assert result.proof == {"model_compat_match": "Samsung Galaxy J7"}


def test_verified_case_and_spacing_insensitive():
    attrs = make_attrs(model_compat=AttrValue(value=["Samsung Galaxy J7"], confidence=0.99))
    proposal = CompatibilityProposal(sku_id="SKU-021", claimed_model="samsung-galaxy j7", claimed_basis="model_compat_match")
    assert verify_proposal(proposal, attrs).verified


def test_rejected_when_claimed_model_not_in_model_compat():
    attrs = make_attrs(model_compat=AttrValue(value=["samsung_galaxy_j7"], confidence=0.99))
    proposal = CompatibilityProposal(sku_id="SKU-021", claimed_model="iPhone 12", claimed_basis="model_compat_match")
    result = verify_proposal(proposal, attrs)
    assert not result.verified
    assert "not found" in result.reason


def test_empty_list_model_compat_verifies_any_claimed_model():
    """[] means confidently universal per pipeline.schema's own semantics."""
    attrs = make_attrs(model_compat=AttrValue(value=[], confidence=0.9))
    proposal = CompatibilityProposal(sku_id="SKU-1", claimed_model="Literally Any Phone", claimed_basis="model_compat_match")
    result = verify_proposal(proposal, attrs)
    assert result.verified
    assert "universal" in result.proof["model_compat_match"]


def test_null_model_compat_never_verifies_a_claim():
    """None means unknown, not universal -- must not be treated as if it
    were an empty (universal) list."""
    attrs = make_attrs(model_compat=AttrValue(value=None, confidence=0.0))
    proposal = CompatibilityProposal(sku_id="SKU-1", claimed_model="Any Phone", claimed_basis="model_compat_match")
    result = verify_proposal(proposal, attrs)
    assert not result.verified
    assert "unknown" in result.reason


# ---------------------------------------------------------------------------
# wattage_sufficient
# ---------------------------------------------------------------------------


def test_wattage_verified_when_sufficient():
    attrs = make_attrs(wattage_w=AttrValue(value=65.0, confidence=0.9))
    proposal = CompatibilityProposal(sku_id="SKU-1", claimed_model="x", claimed_basis="wattage_sufficient", required_wattage_w=45.0)
    result = verify_proposal(proposal, attrs)
    assert result.verified
    assert result.proof == {"wattage_sufficient": {"required": 45.0, "actual": 65.0}}


def test_wattage_verified_at_exact_boundary():
    attrs = make_attrs(wattage_w=AttrValue(value=45.0, confidence=0.9))
    proposal = CompatibilityProposal(sku_id="SKU-1", claimed_model="x", claimed_basis="wattage_sufficient", required_wattage_w=45.0)
    assert verify_proposal(proposal, attrs).verified


def test_wattage_rejected_when_insufficient():
    attrs = make_attrs(wattage_w=AttrValue(value=18.0, confidence=0.9))
    proposal = CompatibilityProposal(sku_id="SKU-1", claimed_model="x", claimed_basis="wattage_sufficient", required_wattage_w=45.0)
    result = verify_proposal(proposal, attrs)
    assert not result.verified
    assert "18.0W < required 45.0W" in result.reason


def test_wattage_rejected_when_unknown():
    attrs = make_attrs(wattage_w=AttrValue(value=None, confidence=0.0))
    proposal = CompatibilityProposal(sku_id="SKU-1", claimed_model="x", claimed_basis="wattage_sufficient", required_wattage_w=45.0)
    result = verify_proposal(proposal, attrs)
    assert not result.verified
    assert "unknown" in result.reason


def test_wattage_rejected_when_proposal_missing_requirement():
    attrs = make_attrs(wattage_w=AttrValue(value=65.0, confidence=0.9))
    proposal = CompatibilityProposal(sku_id="SKU-1", claimed_model="x", claimed_basis="wattage_sufficient", required_wattage_w=None)
    result = verify_proposal(proposal, attrs)
    assert not result.verified


# ---------------------------------------------------------------------------
# Unrecognized basis -- never gets the benefit of the doubt.
# ---------------------------------------------------------------------------


def test_unrecognized_basis_always_rejected_even_with_supporting_data():
    attrs = make_attrs(
        model_compat=AttrValue(value=["samsung_galaxy_j7"], confidence=0.99),
        connector_type=AttrValue(value=ConnectorType.USB_C, confidence=0.9),
    )
    proposal = CompatibilityProposal(sku_id="SKU-1", claimed_model="Samsung Galaxy J7", claimed_basis="the_llm_says_so")
    result = verify_proposal(proposal, attrs)
    assert not result.verified
    assert "unrecognized claimed_basis" in result.reason
