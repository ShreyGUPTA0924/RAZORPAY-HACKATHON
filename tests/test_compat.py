"""
Mocked unit tests for pipeline/compat.py -- prompt construction, batching,
and verification/precision scoring. No network calls.
"""

from unittest.mock import patch

from pipeline import compat
from pipeline.schema import AccessoryType, AttrValue, ProductAttributes

# ---------------------------------------------------------------------------
# _catalog_listing_text / build_proposal_prompt
# ---------------------------------------------------------------------------


def test_catalog_listing_text_caps_snippet_length():
    rows = [{"sku_id": "SKU-A", "product_name": "Title", "description": "x" * 500}]
    text = compat._catalog_listing_text(rows)
    assert "SKU-A: Title" in text
    snippet = text.split("--", 1)[1].strip()
    assert len(snippet) <= compat.RAW_SNIPPET_CHARS


def test_build_proposal_prompt_includes_target_models_and_catalog():
    prompt = compat.build_proposal_prompt("SKU-A: Cable -- desc", ["samsung_galaxy_j7", "oneplus_two"])
    assert "samsung_galaxy_j7" in prompt
    assert "oneplus_two" in prompt
    assert "SKU-A: Cable" in prompt


# ---------------------------------------------------------------------------
# propose_compat_edges -- batching, mocked LLM.
# ---------------------------------------------------------------------------


class _FakeProposalModel:
    def __init__(self, edges: list[compat.ProposedEdge]):
        self._edges = edges

    def invoke(self, *args, **kwargs):
        return compat.ProposalBatchResponse(proposals=self._edges)


def test_propose_compat_edges_batches_target_models(monkeypatch):
    call_count = 0

    def fake_get_model(component, output_schema=None):
        nonlocal call_count
        call_count += 1
        return _FakeProposalModel([])

    targets = [f"model_{i}" for i in range(10)]
    rows = [{"sku_id": "SKU-A", "product_name": "t", "description": "d"}]
    with patch("pipeline.compat.get_chat_model_with_fallback", side_effect=fake_get_model):
        compat.propose_compat_edges(targets, rows, batch_size=4)
    assert call_count == 3  # ceil(10/4)


def test_propose_compat_edges_collects_all_batches():
    edge = compat.ProposedEdge(target_model="samsung_galaxy_j7", sku_id="SKU-A", claimed_model="Samsung Galaxy J7")
    with patch("pipeline.compat.get_chat_model_with_fallback", return_value=_FakeProposalModel([edge])):
        proposals = compat.propose_compat_edges(["samsung_galaxy_j7"], [{"sku_id": "SKU-A", "product_name": "t", "description": "d"}])
    assert len(proposals) == 1
    assert proposals[0].sku_id == "SKU-A"


# ---------------------------------------------------------------------------
# verify_proposals / precision
# ---------------------------------------------------------------------------


def _attrs_with_compat(models: list[str] | None) -> ProductAttributes:
    return ProductAttributes(
        accessory_type=AttrValue(value=AccessoryType.CABLE, confidence=0.9),
        model_compat=AttrValue(value=models, confidence=0.9),
    )


def test_verify_proposals_confirms_a_real_match():
    proposals = [compat.ProposedEdge(target_model="samsung_galaxy_j7", sku_id="SKU-A", claimed_model="Samsung Galaxy J7")]
    attrs_by_sku = {"SKU-A": _attrs_with_compat(["samsung_galaxy_j7"])}
    scored = compat.verify_proposals(proposals, attrs_by_sku)
    assert scored[0].verified is True
    assert compat.precision(scored) == 1.0


def test_verify_proposals_rejects_an_unsupported_claim():
    proposals = [compat.ProposedEdge(target_model="oneplus_two", sku_id="SKU-A", claimed_model="OnePlus Two")]
    attrs_by_sku = {"SKU-A": _attrs_with_compat(["samsung_galaxy_j7"])}  # doesn't actually list oneplus_two
    scored = compat.verify_proposals(proposals, attrs_by_sku)
    assert scored[0].verified is False
    assert compat.precision(scored) == 0.0


def test_verify_proposals_handles_unknown_sku_without_crashing():
    proposals = [compat.ProposedEdge(target_model="x", sku_id="SKU-DOES-NOT-EXIST", claimed_model="x")]
    scored = compat.verify_proposals(proposals, {})
    assert scored[0].verified is False
    assert "not in the published" in scored[0].reason


def test_precision_empty_list_is_zero_not_a_crash():
    assert compat.precision([]) == 0.0


def test_precision_mixed_results():
    proposals = [
        compat.ProposedEdge(target_model="a", sku_id="SKU-A", claimed_model="a"),
        compat.ProposedEdge(target_model="b", sku_id="SKU-A", claimed_model="b"),
    ]
    attrs_by_sku = {"SKU-A": _attrs_with_compat(["a"])}
    scored = compat.verify_proposals(proposals, attrs_by_sku)
    assert compat.precision(scored) == 0.5


def test_universal_model_compat_verifies_any_claim():
    proposals = [compat.ProposedEdge(target_model="anything", sku_id="SKU-A", claimed_model="anything")]
    attrs_by_sku = {"SKU-A": _attrs_with_compat([])}  # explicit empty list == universal
    scored = compat.verify_proposals(proposals, attrs_by_sku)
    assert scored[0].verified is True
