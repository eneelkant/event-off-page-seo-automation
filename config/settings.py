"""Thin re-export for documentation paths that reference config/settings.py."""

from event_seo_mcp.settings import Settings, get_settings, reset_settings_cache

__all__ = ["Settings", "get_settings", "reset_settings_cache"]
