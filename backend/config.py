"""Typed application configuration. Every environment variable the system reads is declared here."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings, validated at process startup.

    Naming follows the concern-prefixed UPPER_SNAKE_CASE convention from the
    implementation guide (Section 5.1): APP_, DB_, LLM_.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Intelligent Credit Card Rewards Agent"
    app_env: str = "local"
    app_debug: bool = False

    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "credit_card_rewards"

    # Phase 2 introduces the system's first two LLM-touching nodes: Intent Classification
    # and Final Answer composition (Section 13.1/1.2 - every other node stays deterministic).
    # Model tiering (Section 23, Must Have): a cheap/fast model for classification, a
    # stronger one only where prose quality actually matters.
    #
    # The LLM is reached via any OpenAI-compatible chat-completions server at llm_base_url -
    # e.g. Ollama running in a Colab notebook and tunneled out via cloudflared. No paid API
    # key is required; llm_api_key is a free-form placeholder most such servers don't even
    # check.
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_intent_model: str = "qwen2.5:7b-instruct"
    llm_final_answer_model: str = "qwen2.5:7b-instruct"
    llm_max_retries: int = 2  # Section 14.1: 2 retries with backoff, then fail as 503
    # Per-attempt timeout for a single LLM call. 30s (this project's original default, sized
    # for a commercial API) is too tight for a self-hosted/Colab-tunneled model, which can take
    # 50-60s on a cold start (loading into GPU VRAM after a session restart) - a timeout this
    # short would abort a legitimately-in-progress response and force a retry, making total
    # latency worse, not better.
    llm_timeout_seconds: int = 90

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached after first construction)."""
    return Settings()
