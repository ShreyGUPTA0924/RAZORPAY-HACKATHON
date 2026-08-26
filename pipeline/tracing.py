"""
LangSmith tracing configuration -- wired in Tier 0 so every LLM call in every
later tier is traced from the moment it's written, instead of bolting
tracing on after the extraction/canonicalization/compat agents already exist.

configure_tracing() only sets process environment variables that LangChain's
tracer reads (LANGCHAIN_TRACING_V2 / LANGCHAIN_API_KEY / LANGCHAIN_PROJECT).
It makes no network call and imports no LLM client -- importing and calling
this module does not touch LangSmith. Call it once, at process start, before
any LangGraph/LangChain code runs (api/main.py and any pipeline entrypoint
script should call it first thing).

Tier 0 deliberately stops at "configuration wired correctly" -- no live trace
has been run against this yet. That happens once LANGCHAIN_API_KEY is filled
in and Tier 1 makes its first real LLM call.
"""

import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = ("LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT")


def configure_tracing(env_file: str | None = None) -> bool:
    """Load .env and set up LangSmith tracing env vars for this process.

    Returns True if tracing is fully configured (key present), False if it
    was left disabled because LANGCHAIN_API_KEY is missing -- that's a normal,
    non-fatal state for Tier 0 (no key has been issued yet), not an error.
    """
    load_dotenv(dotenv_path=env_file, override=False)

    api_key = os.environ.get("LANGCHAIN_API_KEY", "").strip()
    if not api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.warning(
            "LANGCHAIN_API_KEY not set -- tracing disabled. "
            "Fill it in .env once a LangSmith key exists; no code change needed."
        )
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = os.environ.get("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", "agentfront")
    logger.info(
        "LangSmith tracing configured for project=%s", os.environ["LANGCHAIN_PROJECT"]
    )
    return True


def tracing_status() -> dict:
    """Report current tracing configuration without making any network call."""
    return {
        "tracing_enabled": os.environ.get("LANGCHAIN_TRACING_V2", "false").lower() == "true",
        "project": os.environ.get("LANGCHAIN_PROJECT"),
        "api_key_present": bool(os.environ.get("LANGCHAIN_API_KEY", "").strip()),
    }
