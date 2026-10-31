"""Environment-based application settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RepoRoot = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8000
    mcp_http_path: str = "/mcp"
    mcp_auth_token: str | None = None
    mcp_allow_remote_bind: bool = False

    database_path: Path = Path("data/runtime/event_seo.db")
    platforms_config_path: Path = Path("config/platforms.json")
    repo_root: Path = RepoRoot

    ai_provider: Literal["openai", "anthropic", "gemini", "template"] = "template"
    ai_fallback_provider: Literal["openai", "anthropic", "gemini", "template"] | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    ai_timeout_seconds: int = 60
    ai_max_retries: int = 2

    dry_run_default: bool = True
    require_publication_authorization: bool = True
    # Privileged publication and pricing checks. Off unless an operator turns this on.
    # Ordinary planning inputs cannot set it, and it does not publish.
    live_source_verification_enabled: bool = False
    verification_operator_token: str | None = Field(default=None, repr=False)
    source_verification_timeout_seconds: float = 5.0
    source_verification_max_bytes: int = 262144
    source_verification_max_redirects: int = 3
    max_concurrent_browser_sessions: int = 1
    execution_timeout_seconds: int = 120
    rate_limit_requests_per_minute: int = 30
    log_level: str = "INFO"

    playwright_headless: bool = True
    browser_session_dir: Path = Path("data/browser-sessions")
    evidence_dir: Path = Path("data/evidence")

    browser_use_enabled: bool = False
    crawl4ai_enabled: bool = False
    agno_enabled: bool = False
    skyvern_enabled: bool = False
    skyvern_api_url: str | None = None
    skyvern_api_key: str | None = None

    # Eventbrite API (official v3). Private OAuth token from API Keys page.
    # Docs: https://www.eventbrite.com/platform/docs/authentication
    # Create: POST /v3/organizations/{organization_id}/events/
    eventbrite_api_token: str | None = None
    eventbrite_organization_id: str | None = None
    eventbrite_currency: str = "USD"
    # When true and live submit is authorized, also POST /v3/events/{id}/publish/.
    # Default false: create draft event (+ ticket class) only.
    eventbrite_publish_on_create: bool = False
    eventbrite_api_base_url: str = "https://www.eventbriteapi.com/v3"
    eventbrite_timeout_seconds: float = 30.0

    backlink_max_redirects: int = 5
    backlink_timeout_seconds: int = 20
    backlink_user_agent: str = Field(
        default="EventSeoMCP/0.1 (+https://github.com/eneelkant/event-off-page-seo-automation)"
    )

    # Google Sheets (service account). Never log credential JSON.
    google_sheets_spreadsheet_id: str | None = None
    google_sheets_credentials_json: str | None = Field(default=None, repr=False)
    google_application_credentials: str | None = None
    google_sheets_credentials_tab: str = "Site Login Credentials"
    google_sheets_submissions_tab: str = "Submissions"
    google_sheets_timeout_seconds: float = 20.0

    @field_validator(
        "mcp_auth_token",
        "ai_fallback_provider",
        "openai_api_key",
        "anthropic_api_key",
        "gemini_api_key",
        "skyvern_api_url",
        "skyvern_api_key",
        "eventbrite_api_token",
        "eventbrite_organization_id",
        "verification_operator_token",
        "google_sheets_spreadsheet_id",
        "google_sheets_credentials_json",
        "google_application_credentials",
        mode="before",
    )
    @classmethod
    def _blank_optional_string(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "database_path",
        "platforms_config_path",
        "browser_session_dir",
        "evidence_dir",
        "repo_root",
        mode="before",
    )
    @classmethod
    def _as_path(cls, value: object) -> Path:
        return Path(str(value))

    def resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return (self.repo_root / path).resolve()

    @property
    def resolved_database_path(self) -> Path:
        return self.resolve_path(self.database_path)

    @property
    def resolved_platforms_path(self) -> Path:
        return self.resolve_path(self.platforms_config_path)

    def ensure_runtime_dirs(self) -> None:
        self.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
        self.resolve_path(self.browser_session_dir).mkdir(parents=True, exist_ok=True)
        self.resolve_path(self.evidence_dir).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
