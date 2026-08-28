"""
Per-component LLM provider routing.

Two free-tier providers, split by task shape, not by whim:

- Gemini: careful structured extraction from messy text -- extractor,
  canonicalizer, compat_proposer, intent_parser. This is the work where
  getting the right value out of inconsistent prose matters more than speed.
- Groq: high-volume / speed-sensitive work -- adversarial_generator, and
  optionally explainer when demo latency matters. openai/gpt-oss-120b on
  Groq is fast and cheap; extraction-quality is a lower bar for "generate
  100 adversarial attack prompts" than for "read this row correctly."
  (Originally speced as Llama 3.3 70B -- confirmed removed from Groq's
  catalog as of 2026-08-27, `client.models.list()` no longer returns it.
  Groq rotates models faster than most providers; if this default 404s
  again, re-check `client.models.list()` rather than guessing a new name.)

This module is config only -- it has no LLM SDK imports and makes no network
calls. pipeline/llm_clients.py is what actually constructs a client from this
config. Nothing here, or in llm_clients.py, may be imported from
surface/gate.py, surface/mandate.py, or pipeline/verify.py -- those stay
LLM-free per the architectural rule in CLAUDE.md.
"""

import os
from dataclasses import dataclass
from enum import Enum


class Provider(str, Enum):
    GEMINI = "gemini"
    GROQ = "groq"


@dataclass(frozen=True)
class LLMComponentConfig:
    provider: Provider
    model: str


# Defaults for each pipeline stage that calls an LLM. Component names here
# are the single source of truth for "which provider does X call" -- .env.example
# points back at this file rather than duplicating the mapping.
_DEFAULTS: dict[str, LLMComponentConfig] = {
    "extractor": LLMComponentConfig(Provider.GEMINI, "gemini-2.5-flash"),
    "canonicalizer": LLMComponentConfig(Provider.GEMINI, "gemini-2.5-flash"),
    "compat_proposer": LLMComponentConfig(Provider.GEMINI, "gemini-2.5-flash"),
    "intent_parser": LLMComponentConfig(Provider.GEMINI, "gemini-2.5-flash"),
    "adversarial_generator": LLMComponentConfig(Provider.GROQ, "openai/gpt-oss-120b"),
    "explainer": LLMComponentConfig(Provider.GROQ, "openai/gpt-oss-120b"),
}


def get_component_config(component: str) -> LLMComponentConfig:
    """Resolve provider+model for a named pipeline component.

    Reads <COMPONENT>_LLM_PROVIDER / <COMPONENT>_LLM_MODEL env vars as
    optional overrides (see .env.example) so a specific deploy can move a
    component off Gemini without a code change -- e.g. during a live demo
    that's close to Gemini's free-tier per-minute quota.
    """
    if component not in _DEFAULTS:
        raise ValueError(f"Unknown LLM component '{component}'. Known: {sorted(_DEFAULTS)}")

    default = _DEFAULTS[component]
    env_prefix = component.upper()

    provider_override = os.environ.get(f"{env_prefix}_LLM_PROVIDER")
    provider = Provider(provider_override) if provider_override else default.provider

    model = os.environ.get(f"{env_prefix}_LLM_MODEL", default.model)

    return LLMComponentConfig(provider=provider, model=model)


# ---------------------------------------------------------------------------
# Fallback chains -- free-tier quotas are per (provider, model), not just
# per provider: Gemini's gemini-2.5-flash and gemini-2.5-flash-lite are
# separate daily buckets, and so is every individual Groq model. A chain
# lets one component exhaust its primary bucket and keep working against
# the next one instead of stopping for the day.
#
# Every model name below was confirmed to exist via a live models.list()
# call on 2026-08-27 -- both providers rotate their catalogs faster than
# expected (gemini-2.0-flash and llama-3.3-70b-versatile were both already
# gone by then). Re-verify with client.models.list() before trusting this
# chain again after any gap, rather than assuming it's still accurate.
#
# gemini-2.5-flash-lite: spot-checked (not the full synthetic suite) on
# 3 obvious-answer cases on 2026-08-27 -- correct on all 3, including
# correctly abstaining on the deliberately-uninformative listing. That's a
# positive signal, not a full validation; it stays a fallback link rather
# than replacing gemini-2.5-flash as primary until it's run against the
# full tests/test_extract_llm.py suite.
# ---------------------------------------------------------------------------

FALLBACK_CHAINS: dict[str, list[LLMComponentConfig]] = {
    "extractor": [
        LLMComponentConfig(Provider.GEMINI, "gemini-2.5-flash"),
        LLMComponentConfig(Provider.GEMINI, "gemini-2.5-flash-lite"),
        LLMComponentConfig(Provider.GROQ, "openai/gpt-oss-120b"),
        LLMComponentConfig(Provider.GROQ, "openai/gpt-oss-20b"),
    ],
}


def get_fallback_chain(component: str) -> list[LLMComponentConfig]:
    """The ordered list of (provider, model) to try for `component`. Falls
    back to a single-entry chain of just get_component_config(component)
    for any component without an explicit chain defined above.

    An env var override (<COMPONENT>_LLM_PROVIDER/_MODEL) is NOT ignored
    just because a fixed chain exists for this component -- it's moved to
    the front, with the rest of the configured chain kept behind it as a
    safety net (deduplicated if the override already names an entry in the
    chain). Getting this wrong once meant EXTRACTOR_LLM_PROVIDER=groq had
    no effect at all: the code still tried gemini-2.5-flash first, retried
    it to exhaustion, then gemini-2.5-flash-lite, before ever reaching
    Groq -- exactly the slow dead-provider cycling the override exists to
    skip.
    """
    default_chain = FALLBACK_CHAINS.get(component) or [get_component_config(component)]

    env_prefix = component.upper()
    has_override = f"{env_prefix}_LLM_PROVIDER" in os.environ or f"{env_prefix}_LLM_MODEL" in os.environ
    if not has_override:
        return default_chain

    override = get_component_config(component)
    rest = [cfg for cfg in default_chain if cfg != override]
    return [override, *rest]
