"""Agno orchestration soft-fail integration."""

from __future__ import annotations

from typing import Any

from event_seo_mcp.settings import Settings


class AgnoIntegration:
    name = "agno"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self) -> dict[str, Any]:
        installed = False
        error = None
        try:
            import agno  # noqa: F401

            installed = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        enabled = self.settings.agno_enabled
        return {
            "integration": self.name,
            "enabled": enabled,
            "installed": installed,
            "configured": enabled and installed,
            "healthy": (not enabled) or installed,
            "soft_fail": True,
            "notes": (
                "Optional workflow coordinator. Core orchestrator does not depend on Agno. "
                "When unavailable, built-in CapabilityRegistry + Orchestrator are used."
            ),
            "error": error,
        }

    def coordinate(self, plan: dict[str, Any]) -> dict[str, Any]:
        status = self.health()
        if not status["enabled"] or not status["installed"]:
            return {
                "ok": False,
                "used_builtin_orchestrator": True,
                "error": "agno_unavailable",
                **status,
            }
        return {
            "ok": False,
            "error": "not_live_tested",
            "message": "Agno is installed but nested-agent coordination is not live-tested.",
            "plan_keys": sorted(plan.keys()),
            **status,
        }
