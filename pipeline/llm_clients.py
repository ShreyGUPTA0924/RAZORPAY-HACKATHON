"""
LLM client factory -- the only place pipeline code should construct a chat
model. Reads pipeline.llm_config for which provider/model a named component
uses and returns a LangChain Runnable, so call sites use the same
.invoke() / .ainvoke() interface regardless of which provider is actually
behind it. Pass output_schema to get a structured-output-bound Runnable
instead of a plain chat model -- see _build_model()'s docstring for why
that has to be applied before, not after, retry-wrapping.

Gemini's free tier has a noticeably tighter requests-per-minute ceiling than
Groq's, so Gemini clients are returned wrapped in Runnable.with_retry() --
exponential backoff with jitter -- while Groq clients get a lighter retry
(transient-error insurance; a quota 429 wants a different model, not a
retry, which is what get_chat_model_with_fallback is for).

Never import this module from surface/gate.py, surface/mandate.py, or
pipeline/verify.py -- those stay LLM-free per CLAUDE.md.
"""


from dotenv import load_dotenv
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from pipeline.llm_config import (
    LLMComponentConfig,
    Provider,
    get_component_config,
    get_fallback_chain,
)

# Gemini free-tier RPM limits are the whole reason this wrapper exists;
# these numbers are a starting point, not tuned against real traffic yet.
GEMINI_RETRY_ATTEMPTS = 5
FALLBACK_RETRY_ATTEMPTS = 2  # lighter: transient-error insurance per model, not a substitute for the chain itself


def _build_model(config: LLMComponentConfig, output_schema: type[BaseModel] | None, retry_attempts: int) -> Runnable:
    """Build one (provider, model) into a Runnable, structured-output bound
    if requested, retry-wrapped. output_schema is applied BEFORE
    retry-wrapping, not after: Runnable.with_retry() returns a generic
    RunnableRetry, which does not expose with_structured_output; calling
    that method has to happen on the real chat model first, then retry
    wraps the already-structured runnable. Getting this order backwards
    fails silently at the type level (RunnableRetry just doesn't have the
    method) rather than at the call it actually breaks.
    """
    if config.provider is Provider.GEMINI:
        # Imported lazily so a Groq-only environment doesn't need the
        # google-genai package installed just to import this module.
        from langchain_google_genai import ChatGoogleGenerativeAI

        model: Runnable = ChatGoogleGenerativeAI(model=config.model)
    elif config.provider is Provider.GROQ:
        from langchain_groq import ChatGroq

        model = ChatGroq(model=config.model)
    else:
        raise ValueError(f"Unhandled provider {config.provider!r}")

    if output_schema is not None:
        model = model.with_structured_output(output_schema)
    return model.with_retry(stop_after_attempt=retry_attempts, wait_exponential_jitter=True)


def get_chat_model(component: str, output_schema: type[BaseModel] | None = None) -> Runnable:
    """Build the chat model for a named pipeline component, using only its
    single configured (provider, model) -- no fallback. See
    get_chat_model_with_fallback() for a version that tries the next model
    in pipeline.llm_config.FALLBACK_CHAINS on failure.

    component: one of the keys in pipeline.llm_config's default map
    (extractor, canonicalizer, compat_proposer, intent_parser,
    adversarial_generator, explainer).
    """
    load_dotenv(override=False)
    config = get_component_config(component)
    attempts = GEMINI_RETRY_ATTEMPTS if config.provider is Provider.GEMINI else FALLBACK_RETRY_ATTEMPTS
    return _build_model(config, output_schema, attempts)


def get_chat_model_with_fallback(component: str, output_schema: type[BaseModel] | None = None) -> Runnable:
    """Like get_chat_model(), but tries every (provider, model) in
    pipeline.llm_config.get_fallback_chain(component) in order, falling
    through to the next on any exception from the previous one -- built on
    Runnable.with_fallbacks(), not a hand-rolled try/except loop. Each
    individual model still gets its own light retry first (transient-error
    insurance); a 429 that doesn't clear within that moves on to the next
    model rather than continuing to hammer an exhausted daily quota.
    """
    load_dotenv(override=False)
    chain = get_fallback_chain(component)
    attempts = [GEMINI_RETRY_ATTEMPTS if cfg.provider is Provider.GEMINI else FALLBACK_RETRY_ATTEMPTS for cfg in chain]
    models = [_build_model(cfg, output_schema, n) for cfg, n in zip(chain, attempts, strict=True)]
    primary, *rest = models
    return primary.with_fallbacks(rest) if rest else primary
