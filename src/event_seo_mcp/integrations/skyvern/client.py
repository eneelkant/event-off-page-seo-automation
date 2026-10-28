"""Skyvern external API soft-fail integration."""

from __future__ import annotations

from typing import Any

import httpx

from event_seo_mcp.settings import Settings


class SkyvernIntegration:
    name = "skyvern"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self) -> dict[str, Any]:
        enabled = self.settings.skyvern_enabled
        configured = bool(self.settings.skyvern_api_url and self.settings.skyvern_api_key)
        return {
            "integration": self.name,
            "enabled": enabled,
            "installed": True,  # HTTP client based; no local package required
            "configured": configured,
            "healthy": (not enabled) or configured,
            "soft_fail": True,
            "notes": (
                "Optional external Skyvern service/API. No local install assumed. "
                "Requires SKYVERN_API_URL and SKYVERN_API_KEY when enabled."
            ),
            "api_url_set": bool(self.settings.skyvern_api_url),
        }

    def create_workflow_stub(self, goal: str) -> dict[str, Any]:
        status = self.health()
        if not status["enabled"]:
            return {"ok": False, "error": "skyvern_disabled", **status}
        if not status["configured"]:
            return {"ok": False, "error": "skyvern_not_configured", **status}
        # Do not call a guessed endpoint shape; document boundary only.
        return {
            "ok": False,
            "error": "endpoint_not_verified",
            "message": (
                "Skyvern credentials present but request schema is NEEDS_VERIFICATION; "
                f"refusing to invent an API call for goal={goal!r}."
            ),
            **status,
        }

    def ping(self) -> dict[str, Any]:
        status = self.health()
        if not status["configured"]:
            return {"ok": False, **status}
        assert self.settings.skyvern_api_url
        try:
            with httpx.Client(timeout=10.0) as client:
                # Only a GET to the configured base URL; do not invent paths.
                response = client.get(
                    self.settings.skyvern_api_url,
                    headers={"Authorization": f"Bearer {self.settings.skyvern_api_key}"},
                )
            return {
                "ok": response.status_code < 500,
                "http_status": response.status_code,
                **status,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), **status}
