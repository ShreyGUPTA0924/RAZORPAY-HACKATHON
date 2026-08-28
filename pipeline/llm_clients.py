"""
LLM client factory -- the only place pipeline code should construct a chat
model. Reads pipeline.llm_config for which provider/model a named component
uses and returns a LangChain Runnable, so call sites use the same
.invoke() / .ainvoke() interface regardless of which provider is actually
behind it. Pass output_schema to get a structured-output-bound Runnable
instead of a plain chat model -- see get_chat_model()'s docstring for why
that has to be applied before, not after, retry-wrapping.

Gemini's free tier has a noticeably tighter requests-per-minute ceiling than
Groq's, so Gemini clients are returned wrapped in Runnable.with_retry() --
exponential backoff with jitter -- while Groq clients are returned plain.
That retry wrapping is a runtime concern (rate limits), not a per-call
decision, so it lives here rather than at each call site.

Never import this module from surface/gate.py, surface/mandate.py, or
pipeline/verify.py -- those stay LLM-free per CLAUDE.md.
"""


from dotenv import load_dotenv
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from pipeline.llm_config import Provider, get_component_config

# Gemini free-tier RPM limits are the whole reason this wrapper exists;
# these numbers are a starting point, not tuned against real traffic yet.
GEMINI_RETRY_ATTEMPTS = 5


def get_chat_model(component: str, output_schema: type[BaseModel] | None = None) -> Runnable:
    """Build the chat model for a named pipeline component.

    component: one of the keys in pipeline.llm_config's default map
    (extractor, canonicalizer, compat_proposer, intent_parser,
    adversarial_generator, explainer).

    output_schema: if given, binds structured output via
    BaseChatModel.with_structured_output(output_schema) -- applied BEFORE
    retry-wrapping, not after. Runnable.with_retry() returns a generic
    RunnableRetry, which does not expose with_structured_output; calling
    that method has to happen on the real chat model first, then retry
    wraps the already-structured runnable. Getting this order backwards
    fails silently at the type level (RunnableRetry just doesn't have the
    method) rather than at the call it actually breaks.
    """
    load_dotenv(override=False)
    config = get_component_config(component)

    if config.provider is Provider.GEMINI:
        # Imported lazily so a Groq-only environment doesn't need the
        # google-genai package installed just to import this module.
        from langchain_google_genai import ChatGoogleGenerativeAI

        model: Runnable = ChatGoogleGenerativeAI(model=config.model)
        if output_schema is not None:
            model = model.with_structured_output(output_schema)
        return model.with_retry(
            stop_after_attempt=GEMINI_RETRY_ATTEMPTS,
            wait_exponential_jitter=True,
        )

    if config.provider is Provider.GROQ:
        from langchain_groq import ChatGroq

        model = ChatGroq(model=config.model)
        if output_schema is not None:
            model = model.with_structured_output(output_schema)
        return model

    raise ValueError(f"Unhandled provider {config.provider!r} for component '{component}'")
