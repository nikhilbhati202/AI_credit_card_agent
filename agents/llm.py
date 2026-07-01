"""Shared LLM client construction. The only place ChatAnthropic is instantiated, so model
choice / retry policy is a one-line change (Section 17 risk: vendor lock-in mitigated by
keeping LLM calls behind one interface).
"""

from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from backend.config import get_settings


class LLMUnavailableError(Exception):
    """Raised when the LLM API fails after retries (Section 14.1: 2 retries with backoff,
    then fail the request with a 503 - never silently default to a guessed output).
    """


class LLMNotConfiguredError(Exception):
    """Raised when ANTHROPIC_API_KEY is missing - a configuration error, distinct from a
    runtime API failure, and one that should never be masked by a confusing auth error deep
    inside the Anthropic SDK.
    """


def _require_api_key() -> SecretStr:
    settings = get_settings()
    # An empty string (e.g. `ANTHROPIC_API_KEY=` left blank in .env) is as unconfigured as a
    # missing key - both should fail fast here with a clear message, never reach the
    # Anthropic SDK and surface as an opaque auth error three layers down.
    if settings.anthropic_api_key is None or not settings.anthropic_api_key.get_secret_value():
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY is not set - required from Phase 2 onward (see .env.example)."
        )
    return settings.anthropic_api_key


@lru_cache
def get_intent_llm() -> ChatAnthropic:
    settings = get_settings()
    return ChatAnthropic(
        model_name=settings.llm_intent_model,
        api_key=_require_api_key(),
        max_retries=settings.llm_max_retries,
        temperature=0,
        timeout=30,
        stop=None,
    )


@lru_cache
def get_final_answer_llm() -> ChatAnthropic:
    settings = get_settings()
    return ChatAnthropic(
        model_name=settings.llm_final_answer_model,
        api_key=_require_api_key(),
        max_retries=settings.llm_max_retries,
        temperature=0.3,
        timeout=30,
        stop=None,
    )
