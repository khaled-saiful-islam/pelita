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
    # Search results, with the passages read from their pages. Paid on every
    # round of a turn that searched.
    tools_token_budget: int = 4096
    history_token_budget: int = 4096
    documents_token_budget: int = 8192

    # ---- Database -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://pelita:pelita@db:5432/pelita"

    # ---- Auth -----------------------------------------------------------
    # Long enough for HS256, and obviously a placeholder. `verify_deployment`
    # refuses to start with this value when APP_ENV=production.
    jwt_secret: str = "pelita-insecure-development-secret-change-me"  # noqa: S105
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Secure cookies require HTTPS; leave off for local http:// development.
    auth_cookie_secure: bool = False

    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin"  # noqa: S105 - documented dev seed; README warns
    seed_admin_email: str = "admin@test.com"

    # ---- Tools ----------------------------------------------------------
    serpapi_key: str = ""
    serpapi_base_url: str = "https://serpapi.com/search"
    search_max_results: int = 8
    image_max_results: int = 6
    # Pages opened per search, for the paragraph that answers and the date it
    # was written. 0 keeps to Google's snippets.
    search_read_pages: int = 3
    search_read_timeout_seconds: float = 6.0
    # Google's `gl` country code ("my"), so prices, weather and news are local.
    search_country: str = ""
    # The zone a turn is dated in when the browser does not say.
    default_timezone: str = "UTC"

    mcp_news_command: str = "/opt/mcp-news/bin/google-news-mcp"
    mcp_news_args: str = ""
    mcp_news_tool: str = "get_top_headlines"
    mcp_news_language: str = "en"
    mcp_news_country: str = "MY"
    mcp_news_ttl_seconds: int = 1800
    mcp_news_timeout_seconds: float = 20.0
    mcp_news_max_items: int = 6

    # ---- Documents ------------------------------------------------------
    document_max_bytes: int = 5 * 1024 * 1024
    document_max_per_conversation: int = 3

    # ---- Sharing ----------------------------------------------------------
    # Where a shared link points. Behind a proxy the request's own host is
    # whatever the proxy forwarded, and a link built from it can point somewhere
    # nobody else can reach. Empty falls back to the request, which is right for
    # a local clone and wrong for a deployment.
    public_base_url: str = ""

    # ---- Rate limiting ----------------------------------------------------
    # Per minute. 0 disables an individual limit; rate_limit_enabled=false
    # disables all of them. Chat and upload are counted per user, auth per
    # client address — the point of the auth limit is the requests made before
    # anyone is signed in.
    rate_limit_enabled: bool = True
    rate_limit_chat_per_minute: int = 20
    rate_limit_upload_per_minute: int = 10
    rate_limit_auth_per_minute: int = 10
    # The only unauthenticated endpoint that returns content. Counted per
    # address, and generous — a shared link doing the rounds in a group chat is
    # a burst of real readers, not an attack.
    rate_limit_share_per_minute: int = 60
    # nginx appends the real peer to any X-Forwarded-For the client sent, so the
    # LAST entry is the trustworthy one. Set false when the API is exposed
    # directly: then the header is entirely client-controlled and believing it
    # lets anyone reset their own limit by inventing an address.
    trust_proxy_headers: bool = True

    # ---- Tool calling -----------------------------------------------------
    # When true and the provider supports it, the model is handed the tool list
    # and chooses. False falls back to choosing from the question with patterns,
    # which is also what happens automatically when a provider rejects `tools`.
    tool_calling_enabled: bool = True
    # How many rounds of tool calls one turn may make. Each round is another
    # model call, so this is the cost ceiling as much as the loop guard.
    tool_max_iterations: int = 3

    # ---- Artifacts -------------------------------------------------------
    # An artifact is one self-contained HTML document — a poster today, a deck
    # or a small app later. Composing one needs a much larger output budget
    # than a chat reply and benefits from a different model, so it gets its own
    # settings, with the URL and key falling back to the chat provider's.
    #
    # Empty `artifact_model` turns the feature off: no tool is offered and the
    # UI says nothing about it.
    artifacts_enabled: bool = True
    artifact_model: str = ""
    artifact_base_url: str = ""
    artifact_api_key: str = ""
    artifact_max_tokens: int = 16384
    artifact_timeout_seconds: float = 300.0
    # The refinement pass roughly doubles the wall clock. Worth it on a fast
    # provider, the first thing to switch off on a slow one.
    artifact_refine_pass: bool = True
    # A document larger than this is a runaway, not a richer poster. Generous
    # because a poster may carry a photograph inside it: the picture is
    # embedded rather than linked, so the document stays one file that prints,
    # downloads and shares without reaching for anything.
    artifact_max_bytes: int = 1_500_000
    artifact_max_per_conversation: int = 10
    # A game is run in a real browser before anybody sees it, and what the
    # console said goes back to the model as the next thing to fix. Costs a
    # few seconds per build and needs the same Chromium the PNG export does.
    # Off, and a game is shipped unplayed, with the person told so.
    artifact_playtest: bool = True
    # Exporting a poster as a picture needs a real browser in the image. Off,
    # and the download gives the document instead of a picture.
    artifact_export_png: bool = True

    @property
    def artifacts_available(self) -> bool:
        return self.artifacts_enabled and bool(self.artifact_model.strip())

    @property
    def resolved_artifact_base_url(self) -> str:
        return (self.artifact_base_url or self.llm_base_url).rstrip("/")

    @property
    def resolved_artifact_api_key(self) -> str:
        return self.artifact_api_key or self.llm_api_key

    # ---- Vision ----------------------------------------------------------
    # Reading an uploaded image needs a model that can see, which is rarely the
    # same one that writes the answers. Empty `vision_model` turns the feature
    # off and images are refused, so the template still runs on one provider.
    #
    # The URL and key fall back to the chat provider's, because the common case
    # is one gateway serving both.
    vision_model: str = ""
    vision_base_url: str = ""
    vision_api_key: str = ""
    vision_timeout_seconds: float = 90.0
    vision_max_tokens: int = 4096
    # Downscaled before sending: a phone photo is 12MP, and a vision model
    # charges for tiles it gains nothing from.
    vision_max_pixels: int = 2_500_000
    vision_jpeg_quality: int = 82

    @property
    def vision_enabled(self) -> bool:
        return bool(self.vision_model.strip())

    @property
    def resolved_vision_base_url(self) -> str:
        return (self.vision_base_url or self.llm_base_url).rstrip("/")

    @property
    def resolved_vision_api_key(self) -> str:
        return self.vision_api_key or self.llm_api_key

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


INSECURE_JWT_SECRET = "pelita-insecure-development-secret-change-me"  # noqa: S105
INSECURE_PASSWORDS = frozenset({"admin", "password", "changeme"})
MIN_JWT_SECRET_LENGTH = 32


def deployment_warnings(settings: Settings) -> list[str]:
    """Configuration that is fine locally and dangerous in production."""
    problems: list[str] = []
    if settings.jwt_secret == INSECURE_JWT_SECRET:
        problems.append("JWT_SECRET is still the shipped default (openssl rand -hex 32)")
    if len(settings.jwt_secret) < MIN_JWT_SECRET_LENGTH:
        problems.append(f"JWT_SECRET is shorter than {MIN_JWT_SECRET_LENGTH} characters")
    if settings.seed_admin_password.lower() in INSECURE_PASSWORDS:
        problems.append("SEED_ADMIN_PASSWORD is a well-known default")
    if not settings.auth_cookie_secure:
        problems.append("AUTH_COOKIE_SECURE is off, so session cookies may travel over http")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
