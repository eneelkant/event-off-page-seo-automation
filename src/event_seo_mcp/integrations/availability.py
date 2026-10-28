"""Aggregate optional integration health."""

from __future__ import annotations

from typing import Any

from event_seo_mcp.integrations.agno import AgnoIntegration
from event_seo_mcp.integrations.browser_use import BrowserUseIntegration
from event_seo_mcp.integrations.crawl4ai import Crawl4AIIntegration
from event_seo_mcp.integrations.skyvern import SkyvernIntegration
from event_seo_mcp.settings import Settings, get_settings


def check_all_integrations(settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    return [
        BrowserUseIntegration(settings).health(),
        Crawl4AIIntegration(settings).health(),
        AgnoIntegration(settings).health(),
        SkyvernIntegration(settings).health(),
    ]
