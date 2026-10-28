#!/usr/bin/env python3
"""Initialize SQLite schema and sync platform registry."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from event_seo_mcp.database.connection import get_database
from event_seo_mcp.database.repository import Repository
from event_seo_mcp.discovery.platform_discovery import sync_platforms_to_db
from event_seo_mcp.settings import get_settings


def main() -> int:
    settings = get_settings()
    settings.ensure_runtime_dirs()
    db = get_database(settings.resolved_database_path)
    repo = Repository(db)
    count = sync_platforms_to_db(repo, settings)
    print(f"Initialized database at {settings.resolved_database_path}")
    print(f"Synced {count} platforms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
