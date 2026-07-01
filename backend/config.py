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
    anthropic_api_key: SecretStr | None = None
    llm_intent_model: str = "claude-haiku-4-5"
    llm_final_answer_model: str = "claude-sonnet-5"
    llm_max_retries: int = 2  # Section 14.1: 2 retries with backoff, then fail as 503

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
