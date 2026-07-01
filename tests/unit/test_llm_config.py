import pytest

from agents.llm import LLMNotConfiguredError, _require_api_key


def test_require_api_key_raises_when_not_configured(monkeypatch):
    class _FakeSettings:
        anthropic_api_key = None

    monkeypatch.setattr("agents.llm.get_settings", lambda: _FakeSettings())

    with pytest.raises(LLMNotConfiguredError, match="ANTHROPIC_API_KEY is not set"):
        _require_api_key()


def test_require_api_key_raises_when_set_to_an_empty_string(monkeypatch):
    from pydantic import SecretStr

    class _FakeSettings:
        anthropic_api_key = SecretStr("")

    monkeypatch.setattr("agents.llm.get_settings", lambda: _FakeSettings())

    with pytest.raises(LLMNotConfiguredError, match="ANTHROPIC_API_KEY is not set"):
        _require_api_key()


def test_require_api_key_returns_the_key_when_configured(monkeypatch):
    from pydantic import SecretStr

    class _FakeSettings:
        anthropic_api_key = SecretStr("test-key")

    monkeypatch.setattr("agents.llm.get_settings", lambda: _FakeSettings())

    assert _require_api_key().get_secret_value() == "test-key"
