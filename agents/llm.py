"""Shared LLM client construction. The only place a chat model is instantiated, so model
choice / provider / retry policy is a one-line config change (Section 17 risk: vendor
lock-in mitigated by keeping LLM calls behind one interface).

Two providers are supported via LLM_PROVIDER (backend/config.py):
- "anthropic": ChatAnthropic, needs ANTHROPIC_API_KEY.
- "openai_compatible" (default): ChatOpenAI pointed at LLM_BASE_URL - any server that speaks
  the OpenAI chat-completions API, e.g. Ollama running in a free Colab GPU notebook and
  tunneled out via ngrok/cloudflared (see COLAB_SETUP.md). No paid API key required.

Structured output (agents/nodes/intent.py's `.with_structured_output(...)` call) needs a
provider-aware default: langchain-openai's default method is "json_schema", which uses
OpenAI's cloud-only Structured Outputs feature and is not understood by Ollama's
OpenAI-compatibility layer. Ollama-hosted models that support tool calling (Qwen2.5,
Llama-3.1, etc.) work correctly with method="function_calling" instead, so
_OpenAICompatibleChatModel overrides the default rather than requiring every call site to
know which provider it's talking to.
"""

from functools import lru_cache
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from backend.config import get_settings


class LLMUnavailableError(Exception):
    """Raised when the LLM API fails after retries (Section 14.1: 2 retries with backoff,
    then fail the request with a 503 - never silently default to a guessed output).
    """


class LLMNotConfiguredError(Exception):
    """Raised when the selected provider is missing required configuration - distinct from
    a runtime API failure, and one that should never be masked by a confusing auth error deep
    inside a provider SDK.
    """


class _OpenAICompatibleChatModel(ChatOpenAI):
    """ChatOpenAI with a structured-output default that works against Ollama and similar
    self-hosted OpenAI-compatible servers, which do not implement OpenAI's cloud-only
    "json_schema" Structured Outputs feature but do support tool-calling for compatible
    models (Section 17's vendor-flexibility: this is the one place that difference is known).
    """

    def with_structured_output(
        self,
        schema: Any = None,
        *,
        method: Literal["function_calling", "json_mode", "json_schema"] = "function_calling",
        include_raw: bool = False,
        strict: bool | None = None,
        **kwargs: Any,
    ) -> Any:
        return super().with_structured_output(
            schema, method=method, include_raw=include_raw, strict=strict, **kwargs
        )


def _require_anthropic_api_key() -> SecretStr:
    settings = get_settings()
    # An empty string (e.g. `ANTHROPIC_API_KEY=` left blank in .env) is as unconfigured as a
    # missing key - both should fail fast here with a clear message, never reach the
    # Anthropic SDK and surface as an opaque auth error three layers down.
    if settings.anthropic_api_key is None or not settings.anthropic_api_key.get_secret_value():
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY is not set - required when LLM_PROVIDER=anthropic "
            "(see .env.example)."
        )
    return settings.anthropic_api_key


def _require_base_url() -> str:
    settings = get_settings()
    if not settings.llm_base_url:
        raise LLMNotConfiguredError(
            "LLM_BASE_URL is not set - required when LLM_PROVIDER=openai_compatible. Point "
            "it at any OpenAI-compatible chat-completions server, e.g. a Colab-hosted Ollama "
            "instance tunneled out via ngrok/cloudflared (see COLAB_SETUP.md)."
        )
    return settings.llm_base_url


def _build_chat_model(model_name: str, temperature: float) -> BaseChatModel:
    settings = get_settings()
    if settings.llm_provider == "anthropic":
        return ChatAnthropic(
            model_name=model_name,
            api_key=_require_anthropic_api_key(),
            max_retries=settings.llm_max_retries,
            temperature=temperature,
            timeout=settings.llm_timeout_seconds,
            stop=None,
        )
    if settings.llm_provider == "openai_compatible":
        # Self-hosted OpenAI-compatible servers (Ollama included) generally don't validate
        # the API key at all - it must still be a non-empty string for the OpenAI client to
        # construct itself, so a placeholder is used when the user hasn't set one.
        api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else "not-needed"
        return _OpenAICompatibleChatModel(
            model=model_name,
            base_url=_require_base_url(),
            api_key=SecretStr(api_key),
            max_retries=settings.llm_max_retries,
            temperature=temperature,
            timeout=settings.llm_timeout_seconds,
        )
    raise LLMNotConfiguredError(
        f"Unknown LLM_PROVIDER={settings.llm_provider!r} - must be 'anthropic' or "
        "'openai_compatible'."
    )


@lru_cache
def get_intent_llm() -> BaseChatModel:
    settings = get_settings()
    return _build_chat_model(settings.llm_intent_model, temperature=0)


@lru_cache
def get_final_answer_llm() -> BaseChatModel:
    settings = get_settings()
    # Lowered from 0.3 (then 0.1, then 0.0): smaller/self-hosted models (Section 17's provider
    # flexibility) have been observed live repeatedly ignoring the "never restate arithmetic
    # or mine the citation excerpt for extra numbers" prompt instruction, even at 0.1, still
    # triggering the Guardrail's number-grounding check. This narrative step doesn't need
    # creative variety - matching Intent Classification's temperature=0 trades away sampling
    # diversity entirely for the most consistent instruction-following available.
    return _build_chat_model(settings.llm_final_answer_model, temperature=0.0)
