"""Application settings.

Every knob the template exposes lives here and nowhere else. Anything a person
might want to change when adopting the template should be reachable by editing
`.env`, never by editing code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Identity -------------------------------------------------------
    app_name: str = "Pelita"
    app_env: str = "development"
    log_level: str = "INFO"

    # ---- Model access ---------------------------------------------------
    # The whole point of the template: these three lines are the provider.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 120.0
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.7

    system_prompt: str = (
        "You are Pelita, a helpful assistant. Answer clearly and concisely. "
        "If you are unsure about something, say so rather than guessing."
    )

    # ---- Pricing (per 1M tokens, in `llm_price_currency`) ----------------
    llm_price_input_per_1m: float = 0.15
    llm_price_output_per_1m: float = 0.60
    llm_price_currency: str = "USD"

    # ---- Context budgets (tokens) ---------------------------------------
    memory_token_budget: int = 512
    tools_token_budget: int = 2048
    history_token_budget: int = 4096

    # ---- Database -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://pelita:pelita@db:5432/pelita"

    # ---- Auth -----------------------------------------------------------
    jwt_secret: str = "change-me-in-production"  # noqa: S105 - overridden via .env; README warns
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin"  # noqa: S105 - documented dev seed; README warns
    seed_admin_email: str = "admin@test.com"

    # ---- Tools ----------------------------------------------------------
    serpapi_key: str = ""
    serpapi_base_url: str = "https://serpapi.com/search"
    search_max_results: int = 5

    mcp_news_command: str = "/opt/mcp-news/bin/google-news-mcp"
    mcp_news_args: str = ""
    mcp_news_tool: str = "get_top_headlines"
    mcp_news_language: str = "en"
    mcp_news_country: str = "MY"
    mcp_news_ttl_seconds: int = 1800
    mcp_news_timeout_seconds: float = 20.0
    mcp_news_max_items: int = 6

    # ---- Memory ---------------------------------------------------------
    memory_auto_extract: bool = True
    memory_max_per_user: int = 100

    # ---- Suggestions ----------------------------------------------------
    suggestions_enabled: bool = True
    suggestions_count: int = 3

    # ---- Guard ----------------------------------------------------------
    guard_enabled: bool = True
    guard_block_severity: str = "none"  # none | high — "none" sanitises, never blocks

    # ---- Language -------------------------------------------------------
    supported_languages: str = "en,ms,ta,zh,bn"
    default_language: str = "en"

    # ---- CORS -----------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:8080"

    @field_validator("llm_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supported_language_list(self) -> list[str]:
        return [x.strip().lower() for x in self.supported_languages.split(",") if x.strip()]

    @property
    def mcp_news_arg_list(self) -> list[str]:
        return [a for a in self.mcp_news_args.split() if a]

    @property
    def search_enabled(self) -> bool:
        """Web search is only offered when a key is actually present."""
        return bool(self.serpapi_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
