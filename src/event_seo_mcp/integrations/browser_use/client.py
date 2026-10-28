"""browser-use soft-fail integration."""

from __future__ import annotations

from typing import Any

from event_seo_mcp.settings import Settings


class BrowserUseIntegration:
    name = "browser-use"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self) -> dict[str, Any]:
        installed = False
        error = None
        try:
            import browser_use  # noqa: F401

            installed = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        enabled = self.settings.browser_use_enabled
        return {
            "integration": self.name,
            "enabled": enabled,
            "installed": installed,
            "configured": enabled and installed,
            "healthy": (not enabled) or installed,
            "soft_fail": True,
            "notes": (
                "Optional LLM-driven browser workflows. Disabled by default. "
                "When enabled and installed, callers should reuse an authorized browser session."
            ),
            "error": error,
        }

    def run_task(self, task: str) -> dict[str, Any]:
        status = self.health()
        if not status["enabled"]:
            return {"ok": False, "error": "browser_use_disabled", **status}
        if not status["installed"]:
            return {"ok": False, "error": "browser_use_unavailable", **status}
        return {
            "ok": False,
            "error": "not_live_tested",
            "message": f"browser-use is installed but task execution is not live-tested: {task}",
            **status,
        }
