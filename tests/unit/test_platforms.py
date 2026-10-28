"""Platform registry validation."""

from __future__ import annotations

from pathlib import Path

from event_seo_mcp.discovery.platform_discovery import load_platforms_file


def test_platforms_file_loads() -> None:
    platforms = load_platforms_file(Path("config/platforms.json"))
    assert len(platforms.platforms) >= 30
    assert all(p.automation_status == "NEEDS_VERIFICATION" for p in platforms.platforms)


def test_no_invented_ready_platforms() -> None:
    platforms = load_platforms_file(Path("config/platforms.json"))
    ready = [p for p in platforms.platforms if p.automation_status == "READY"]
    assert ready == []


def test_eventbrite_has_docs_hint() -> None:
    platforms = load_platforms_file(Path("config/platforms.json"))
    eb = platforms.by_id("eventbrite")
    assert eb is not None
    assert eb.official_homepage is not None
