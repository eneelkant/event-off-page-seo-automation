"""Capability registry for adapters and optional frameworks."""

from __future__ import annotations

from typing import Any

from event_seo_mcp.adapters.registry import get_adapter, list_adapters
from event_seo_mcp.integrations.availability import check_all_integrations
from event_seo_mcp.providers.factory import list_provider_status
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.settings import Settings, get_settings


class CapabilityRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def adapter_health(self) -> list[dict[str, Any]]:
        reports = []
        for adapter in list_adapters():
            report = adapter.check_capabilities()
            reports.append(
                {
                    "adapter_name": report.adapter_name,
                    "installed": report.installed,
                    "configured": report.configured,
                    "healthy": report.healthy,
                    "supported_operations": report.supported_operations,
                    "notes": report.notes,
                    "details": report.details,
                }
            )
        return reports

    def full_health(self) -> dict[str, Any]:
        return {
            "adapters": self.adapter_health(),
            "integrations": check_all_integrations(self.settings),
            "providers": list_provider_status(self.settings),
            "dry_run_default": self.settings.dry_run_default,
        }

    def select_adapter(self, platform: PlatformRecord) -> dict[str, Any]:
        """Prefer official API adapters; fall back to configured browser methods."""
        preferred = platform.adapter_name
        adapter = get_adapter(preferred)
        report = adapter.check_capabilities()
        reason = f"Selected configured adapter '{preferred}' for platform '{platform.platform_id}'."
        if platform.submission_method.startswith("api") and report.configured:
            reason += " Official/API path preferred."
        elif not report.healthy:
            reason += " Adapter unhealthy; submission will soft-fail or dry-run only."
        return {
            "adapter_name": preferred,
            "reason": reason,
            "capability": {
                "installed": report.installed,
                "configured": report.configured,
                "healthy": report.healthy,
                "notes": report.notes,
            },
            "platform_status": platform.automation_status,
        }
