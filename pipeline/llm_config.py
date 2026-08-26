"""
Per-component LLM provider routing.

Two free-tier providers, split by task shape, not by whim:

- Gemini: careful structured extraction from messy text -- extractor,
  canonicalizer, compat_proposer, intent_parser. This is the work where
  getting the right value out of inconsistent prose matters more than speed.
- Groq: high-volume / speed-sensitive work -- adversarial_generator, and
  optionally explainer when demo latency matters. Llama 3.3 70B on Groq is
  fast and cheap; extraction-quality is a lower bar for "generate 100
  adversarial attack prompts" than for "read this row correctly."

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
    "adversarial_generator": LLMComponentConfig(Provider.GROQ, "llama-3.3-70b-versatile"),
    "explainer": LLMComponentConfig(Provider.GROQ, "llama-3.3-70b-versatile"),
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
