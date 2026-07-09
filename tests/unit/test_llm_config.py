import pytest

from agents.llm import LLMNotConfiguredError, _require_anthropic_api_key, _require_base_url


class _FakeSettings:
    def __init__(self, **overrides):
        self.anthropic_api_key = None
        self.llm_base_url = None
        self.llm_api_key = None
        self.llm_provider = "openai_compatible"
        self.llm_intent_model = "qwen2.5:7b-instruct"
        self.llm_final_answer_model = "qwen2.5:7b-instruct"
        self.llm_max_retries = 2
        self.llm_timeout_seconds = 90
        for key, value in overrides.items():
            setattr(self, key, value)


def test_require_anthropic_api_key_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr("agents.llm.get_settings", lambda: _FakeSettings(anthropic_api_key=None))

    with pytest.raises(LLMNotConfiguredError, match="ANTHROPIC_API_KEY is not set"):
        _require_anthropic_api_key()


def test_require_anthropic_api_key_raises_when_set_to_an_empty_string(monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(
        "agents.llm.get_settings", lambda: _FakeSettings(anthropic_api_key=SecretStr(""))
    )

    with pytest.raises(LLMNotConfiguredError, match="ANTHROPIC_API_KEY is not set"):
        _require_anthropic_api_key()


def test_require_anthropic_api_key_returns_the_key_when_configured(monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(
        "agents.llm.get_settings", lambda: _FakeSettings(anthropic_api_key=SecretStr("test-key"))
    )

    assert _require_anthropic_api_key().get_secret_value() == "test-key"


def test_require_base_url_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr("agents.llm.get_settings", lambda: _FakeSettings(llm_base_url=None))

    with pytest.raises(LLMNotConfiguredError, match="LLM_BASE_URL is not set"):
        _require_base_url()


def test_require_base_url_returns_the_url_when_configured(monkeypatch):
    monkeypatch.setattr(
        "agents.llm.get_settings",
        lambda: _FakeSettings(llm_base_url="https://example.ngrok-free.app/v1"),
    )

    assert _require_base_url() == "https://example.ngrok-free.app/v1"


class TestBuildChatModel:
    def test_openai_compatible_provider_builds_without_error(self, monkeypatch):
        from agents.llm import _build_chat_model

        monkeypatch.setattr(
            "agents.llm.get_settings",
            lambda: _FakeSettings(
                llm_provider="openai_compatible",
                llm_base_url="https://example.ngrok-free.app/v1",
            ),
        )

        model = _build_chat_model("qwen2.5:7b-instruct", temperature=0)

        assert model.model_name == "qwen2.5:7b-instruct"

    def test_openai_compatible_provider_requires_a_base_url(self, monkeypatch):
        from agents.llm import _build_chat_model

        monkeypatch.setattr(
            "agents.llm.get_settings",
            lambda: _FakeSettings(llm_provider="openai_compatible", llm_base_url=None),
        )

        with pytest.raises(LLMNotConfiguredError, match="LLM_BASE_URL is not set"):
            _build_chat_model("qwen2.5:7b-instruct", temperature=0)

    def test_unknown_provider_raises(self, monkeypatch):
        from agents.llm import _build_chat_model

        monkeypatch.setattr(
            "agents.llm.get_settings", lambda: _FakeSettings(llm_provider="made-up-provider")
        )

        with pytest.raises(LLMNotConfiguredError, match="Unknown LLM_PROVIDER"):
            _build_chat_model("some-model", temperature=0)

    def test_openai_compatible_structured_output_defaults_to_function_calling(self, monkeypatch):
        """Ollama's OpenAI-compatibility layer doesn't implement OpenAI's cloud-only
        json_schema Structured Outputs feature (langchain-openai's own default) - this is the
        regression the _OpenAICompatibleChatModel override in agents/llm.py exists to prevent.
        """
        from unittest.mock import MagicMock, patch

        from agents.llm import _build_chat_model

        monkeypatch.setattr(
            "agents.llm.get_settings",
            lambda: _FakeSettings(
                llm_provider="openai_compatible",
                llm_base_url="https://example.ngrok-free.app/v1",
            ),
        )
        model = _build_chat_model("qwen2.5:7b-instruct", temperature=0)

        with patch("langchain_openai.ChatOpenAI.with_structured_output", MagicMock()) as mock_super:
            model.with_structured_output(dict)

        assert mock_super.call_args.kwargs["method"] == "function_calling"
