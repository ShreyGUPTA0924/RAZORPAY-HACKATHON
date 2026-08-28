import pytest

from pipeline.llm_config import (
    FALLBACK_CHAINS,
    LLMComponentConfig,
    Provider,
    get_component_config,
    get_fallback_chain,
)


def test_get_component_config_default():
    cfg = get_component_config("extractor")
    assert cfg.provider is Provider.GEMINI
    assert cfg.model == "gemini-2.5-flash"


def test_get_component_config_unknown_raises():
    with pytest.raises(ValueError, match="Unknown LLM component"):
        get_component_config("not-a-real-component")


def test_env_override_provider_and_model(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_LLM_PROVIDER", "groq")
    monkeypatch.setenv("EXTRACTOR_LLM_MODEL", "openai/gpt-oss-120b")
    cfg = get_component_config("extractor")
    assert cfg.provider is Provider.GROQ
    assert cfg.model == "openai/gpt-oss-120b"


def test_env_override_provider_only_keeps_default_model(monkeypatch):
    """Documented gap, not a bug: overriding only the provider does NOT pick
    a sensible model for that provider -- the model default is per-component,
    not per-provider, so it stays whatever the component's original default
    was. Confirmed this the hard way switching extractor to Groq while
    Gemini's model name was still configured."""
    monkeypatch.setenv("EXTRACTOR_LLM_PROVIDER", "groq")
    monkeypatch.delenv("EXTRACTOR_LLM_MODEL", raising=False)
    cfg = get_component_config("extractor")
    assert cfg.provider is Provider.GROQ
    assert cfg.model == "gemini-2.5-flash"  # still the Gemini default -- caller must also override the model


def test_fallback_chain_for_extractor_matches_configured_chain():
    chain = get_fallback_chain("extractor")
    assert chain == FALLBACK_CHAINS["extractor"]
    assert len(chain) >= 2
    assert chain[0].provider is Provider.GEMINI


def test_fallback_chain_falls_back_to_single_entry_for_unconfigured_component():
    chain = get_fallback_chain("canonicalizer")  # has a default, no explicit FALLBACK_CHAINS entry
    assert chain == [get_component_config("canonicalizer")]


def test_fallback_chain_entries_are_distinct_provider_model_pairs():
    chain = FALLBACK_CHAINS["extractor"]
    pairs = [(cfg.provider, cfg.model) for cfg in chain]
    assert len(pairs) == len(set(pairs)), "duplicate (provider, model) in the chain defeats the point of a fallback"


def test_llm_component_config_is_hashable_and_comparable():
    a = LLMComponentConfig(Provider.GEMINI, "gemini-2.5-flash")
    b = LLMComponentConfig(Provider.GEMINI, "gemini-2.5-flash")
    assert a == b
    assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# Regression coverage for a real bug: get_fallback_chain() used to ignore
# env var overrides entirely whenever a component had an explicit
# FALLBACK_CHAINS entry -- EXTRACTOR_LLM_PROVIDER=groq had NO effect, the
# chain still tried gemini-2.5-flash first (and retried it to exhaustion)
# before ever reaching Groq. Caught by actually running a real extraction
# with the override set and watching it still hit Gemini first.
# ---------------------------------------------------------------------------


def test_fallback_chain_honors_provider_override_even_with_a_fixed_chain(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_LLM_PROVIDER", "groq")
    monkeypatch.setenv("EXTRACTOR_LLM_MODEL", "openai/gpt-oss-120b")
    chain = get_fallback_chain("extractor")
    assert chain[0] == LLMComponentConfig(Provider.GROQ, "openai/gpt-oss-120b")


def test_fallback_chain_keeps_rest_of_default_chain_as_safety_net_behind_override(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_LLM_PROVIDER", "groq")
    monkeypatch.setenv("EXTRACTOR_LLM_MODEL", "openai/gpt-oss-120b")
    chain = get_fallback_chain("extractor")
    # the override is first, but Gemini options are still available further
    # down the chain rather than being dropped entirely
    assert any(cfg.provider is Provider.GEMINI for cfg in chain[1:])


def test_fallback_chain_override_matching_an_existing_chain_entry_is_not_duplicated(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_LLM_PROVIDER", "groq")
    monkeypatch.setenv("EXTRACTOR_LLM_MODEL", "openai/gpt-oss-120b")  # already the 3rd entry in the default chain
    chain = get_fallback_chain("extractor")
    pairs = [(cfg.provider, cfg.model) for cfg in chain]
    assert len(pairs) == len(set(pairs))


def test_fallback_chain_without_override_is_unaffected():
    chain = get_fallback_chain("extractor")
    assert chain == FALLBACK_CHAINS["extractor"]
