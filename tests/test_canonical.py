"""
Tests for pipeline/canonical.py. Embedding clustering runs for REAL (local
ONNX, zero quota, no network after the one-time model download) -- only
adjudicate_pair (the actual LLM call) is mocked, via patching
pipeline.canonical.get_chat_model_with_fallback.
"""

from unittest.mock import patch

from pipeline import canonical

# ---------------------------------------------------------------------------
# _UnionFind
# ---------------------------------------------------------------------------


def test_union_find_groups_transitively():
    uf = canonical._UnionFind(["a", "b", "c", "d"])
    uf.union("a", "b")
    uf.union("b", "c")
    groups = uf.groups()
    group_sets = [set(g) for g in groups]
    assert {"a", "b", "c"} in group_sets
    assert {"d"} in group_sets


# ---------------------------------------------------------------------------
# _pick_representative
# ---------------------------------------------------------------------------


def test_pick_representative_prefers_canonical_looking_value():
    cluster = ["Samsung Galaxy J7", "samsung_galaxy_j7"]
    counts = {"Samsung Galaxy J7": 1, "samsung_galaxy_j7": 1}
    assert canonical._pick_representative(cluster, counts) == "samsung_galaxy_j7"


def test_pick_representative_prefers_more_frequent_among_canonical_looking():
    cluster = ["iphone_5s", "apple_iphone_5s"]
    counts = {"iphone_5s": 3, "apple_iphone_5s": 1}
    assert canonical._pick_representative(cluster, counts) == "iphone_5s"


# ---------------------------------------------------------------------------
# adjudicate_pair -- caching.
# ---------------------------------------------------------------------------


class _FakeAdjudicationModel:
    def __init__(self, same_device: bool, confident: bool = True):
        self._response = canonical._AdjudicationResponse(same_device=same_device, confident=confident, reason="test")

    def invoke(self, *args, **kwargs):
        return self._response


def test_adjudicate_pair_caches_and_skips_second_llm_call(monkeypatch, tmp_path):
    monkeypatch.setattr(canonical, "ADJUDICATION_CACHE_DIR", tmp_path / "cache")
    with patch("pipeline.canonical.get_chat_model_with_fallback", return_value=_FakeAdjudicationModel(True)) as mock_get_model:
        r1 = canonical.adjudicate_pair("iphone_5", "apple_iphone_5")
    assert r1["same_device"] is True
    mock_get_model.assert_called_once()

    with patch("pipeline.canonical.get_chat_model_with_fallback") as mock_get_model_2:
        r2 = canonical.adjudicate_pair("iphone_5", "apple_iphone_5")
    assert r2 == r1
    mock_get_model_2.assert_not_called()


def test_adjudicate_pair_cache_key_is_order_independent(monkeypatch, tmp_path):
    monkeypatch.setattr(canonical, "ADJUDICATION_CACHE_DIR", tmp_path / "cache")
    with patch("pipeline.canonical.get_chat_model_with_fallback", return_value=_FakeAdjudicationModel(True)):
        canonical.adjudicate_pair("a", "b")
    with patch("pipeline.canonical.get_chat_model_with_fallback") as mock_get_model:
        canonical.adjudicate_pair("b", "a")
    mock_get_model.assert_not_called()


# ---------------------------------------------------------------------------
# canonicalize_model_compat_values -- real local embeddings, mocked LLM.
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_result():
    result = canonical.canonicalize_model_compat_values([])
    assert result.canonical == {}
    assert result.clusters == []


def test_single_value_is_its_own_canonical_form():
    result = canonical.canonicalize_model_compat_values(["samsung_galaxy_j7"])
    assert result.canonical == {"samsung_galaxy_j7": "samsung_galaxy_j7"}


def test_near_identical_values_auto_merge_without_any_llm_call(monkeypatch, tmp_path):
    """Case/whitespace-only differences are exact string matches once
    normalized -- the one case that skips the LLM call entirely (see
    module docstring for why nothing else does, even a near-zero distance).
    Deliberately NOT testing hyphen-vs-underscore or space-vs-underscore
    here: those measure close to 0.15, same ballpark as "iphone_6" vs
    "iphone_6s" (genuinely different devices)."""
    monkeypatch.setattr(canonical, "ADJUDICATION_CACHE_DIR", tmp_path / "cache")
    with patch("pipeline.canonical.get_chat_model_with_fallback") as mock_get_model:
        result = canonical.canonicalize_model_compat_values(["samsung_galaxy_j7", "Samsung_Galaxy_J7"])
    mock_get_model.assert_not_called()
    assert result.canonical["samsung_galaxy_j7"] == result.canonical["Samsung_Galaxy_J7"]


def test_clearly_unrelated_values_stay_separate_without_any_llm_call(monkeypatch, tmp_path):
    monkeypatch.setattr(canonical, "ADJUDICATION_CACHE_DIR", tmp_path / "cache")
    with patch("pipeline.canonical.get_chat_model_with_fallback") as mock_get_model:
        result = canonical.canonicalize_model_compat_values(["samsung_galaxy_j7", "oneplus_two"])
    mock_get_model.assert_not_called()
    assert result.canonical["samsung_galaxy_j7"] != result.canonical["oneplus_two"]


def test_ambiguous_pair_confidently_same_gets_merged(monkeypatch, tmp_path):
    monkeypatch.setattr(canonical, "ADJUDICATION_CACHE_DIR", tmp_path / "cache")
    with patch("pipeline.canonical.get_chat_model_with_fallback", return_value=_FakeAdjudicationModel(True, confident=True)):
        result = canonical.canonicalize_model_compat_values(["xiaomi_mi4", "xiaomi_redmi_mi4"])
    assert result.canonical["xiaomi_mi4"] == result.canonical["xiaomi_redmi_mi4"]
    assert len(result.llm_adjudications) >= 1


def test_ambiguous_pair_confidently_different_stays_separate(monkeypatch, tmp_path):
    monkeypatch.setattr(canonical, "ADJUDICATION_CACHE_DIR", tmp_path / "cache")
    with patch("pipeline.canonical.get_chat_model_with_fallback", return_value=_FakeAdjudicationModel(False, confident=True)):
        result = canonical.canonicalize_model_compat_values(["htc_desire_526", "htc_desire_vc"])
    assert result.canonical["htc_desire_526"] != result.canonical["htc_desire_vc"]


def test_transitive_merge_never_overrides_a_direct_different_verdict(monkeypatch, tmp_path):
    """Regression test for a real bug caught in a live run: A-B judged
    same, B-C judged different, but A and C were never directly compared
    -- naive union-find would still merge A and C transitively through B.
    Must not happen: the merge that would create the contradiction is
    blocked and recorded, not silently allowed through."""
    monkeypatch.setattr(canonical, "ADJUDICATION_CACHE_DIR", tmp_path / "cache")

    def fake_get_model(component, output_schema=None):
        # xiaomi_mi_4i <-> xiaomi_redmi_mi4i: same. xiaomi_mi_4i <-> xiaomi_redmi_mi4: different.
        # xiaomi_redmi_mi4 <-> xiaomi_redmi_mi4i: whichever gets asked, say same (this is the
        # bridging pair a distance-only auto-merge would have taken for granted).
        class _Model:
            def invoke(self, prompt, **kwargs):
                has = lambda s: s in prompt
                if has("xiaomi_mi_4i") and has("xiaomi_redmi_mi4i"):
                    return canonical._AdjudicationResponse(same_device=True, confident=True, reason="same, redmi is a stray prefix")
                if has("xiaomi_mi_4i") and has("xiaomi_redmi_mi4"):
                    return canonical._AdjudicationResponse(same_device=False, confident=True, reason="mi4 and mi4i are different models")
                return canonical._AdjudicationResponse(same_device=True, confident=True, reason="bridging pair")

        return _Model()

    with patch("pipeline.canonical.get_chat_model_with_fallback", side_effect=fake_get_model):
        result = canonical.canonicalize_model_compat_values(["xiaomi_mi_4i", "xiaomi_redmi_mi4", "xiaomi_redmi_mi4i"])

    assert result.canonical["xiaomi_mi_4i"] != result.canonical["xiaomi_redmi_mi4"]
    assert result.contradictions_prevented, "expected the bridging merge to be blocked and recorded"


def test_ambiguous_pair_llm_not_confident_stays_unmerged_and_flagged(monkeypatch, tmp_path):
    monkeypatch.setattr(canonical, "ADJUDICATION_CACHE_DIR", tmp_path / "cache")
    with patch("pipeline.canonical.get_chat_model_with_fallback", return_value=_FakeAdjudicationModel(True, confident=False)):
        result = canonical.canonicalize_model_compat_values(["xiaomi_mi_4i", "xiaomi_mi_4s"])
    assert result.canonical["xiaomi_mi_4i"] != result.canonical["xiaomi_mi_4s"]
    assert "xiaomi_mi_4i" in result.unmapped_low_confidence
    assert "xiaomi_mi_4s" in result.unmapped_low_confidence
