"""Shared pytest fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from event_seo_mcp.database.connection import Database, reset_database_singleton
from event_seo_mcp.database.repository import Repository
from event_seo_mcp.discovery.platform_discovery import sync_platforms_to_db
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.settings import Settings, reset_settings_cache
from event_seo_mcp.tools.handlers import ToolService

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    reset_settings_cache()
    reset_database_singleton()
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("AI_PROVIDER", "template")
    monkeypatch.setenv("DRY_RUN_DEFAULT", "true")
    monkeypatch.setenv("PLATFORMS_CONFIG_PATH", str(ROOT / "config/platforms.json"))
    monkeypatch.setenv("MCP_HTTP_HOST", "127.0.0.1")
    reset_settings_cache()
    s = Settings(
        database_path=db_path,
        platforms_config_path=ROOT / "config/platforms.json",
        repo_root=ROOT,
        ai_provider="template",
        dry_run_default=True,
    )
    s.ensure_runtime_dirs()
    return s


@pytest.fixture()
def repo(settings: Settings) -> Repository:
    reset_database_singleton()
    db = Database(settings.resolved_database_path)
    repository = Repository(db)
    sync_platforms_to_db(repository, settings)
    return repository


@pytest.fixture()
def service(repo: Repository, settings: Settings) -> ToolService:
    return ToolService(repo, settings)


@pytest.fixture()
def sample_event() -> EventRecord:
    data = json.loads((FIXTURES / "sample_event.json").read_text(encoding="utf-8"))
    return EventRecord.model_validate(data)
