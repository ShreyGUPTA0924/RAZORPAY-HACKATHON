"""
LLM client factory -- the only place pipeline code should construct a chat
model. Reads pipeline.llm_config for which provider/model a named component
uses and returns a LangChain chat model (a Runnable), so call sites use the
same .invoke() / .ainvoke() / .with_structured_output() interface regardless
of which provider is actually behind it.

Gemini's free tier has a noticeably tighter requests-per-minute ceiling than
Groq's, so Gemini clients are returned wrapped in Runnable.with_retry() --
exponential backoff with jitter -- while Groq clients are returned plain.
That retry wrapping is a runtime concern (rate limits), not a per-call
decision, so it lives here rather than at each call site.

Never import this module from surface/gate.py, surface/mandate.py, or
pipeline/verify.py -- those stay LLM-free per CLAUDE.md.
"""

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel

from pipeline.llm_config import Provider, get_component_config

# Gemini free-tier RPM limits are the whole reason this wrapper exists;
# these numbers are a starting point, not tuned against real traffic yet.
GEMINI_RETRY_ATTEMPTS = 5


def get_chat_model(component: str) -> BaseChatModel:
    """Build the chat model for a named pipeline component.

    component: one of the keys in pipeline.llm_config's default map
    (extractor, canonicalizer, compat_proposer, intent_parser,
    adversarial_generator, explainer).
    """
    load_dotenv(override=False)
    config = get_component_config(component)

    if config.provider is Provider.GEMINI:
        # Imported lazily so a Groq-only environment doesn't need the
        # google-genai package installed just to import this module.
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(model=config.model)
        return model.with_retry(
            stop_after_attempt=GEMINI_RETRY_ATTEMPTS,
            wait_exponential_jitter=True,
        )

    if config.provider is Provider.GROQ:
        from langchain_groq import ChatGroq

        return ChatGroq(model=config.model)

    raise ValueError(f"Unhandled provider {config.provider!r} for component '{component}'")
