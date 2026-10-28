"""Crawl4AI soft-fail discovery integration."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from event_seo_mcp.settings import Settings


class Crawl4AIIntegration:
    name = "crawl4ai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self) -> dict[str, Any]:
        installed = False
        error = None
        try:
            import crawl4ai  # noqa: F401

            installed = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        enabled = self.settings.crawl4ai_enabled
        return {
            "integration": self.name,
            "enabled": enabled,
            "installed": installed,
            "configured": enabled,
            "healthy": (not enabled) or True,
            "soft_fail": True,
            "notes": (
                "Optional crawler for public submission-page discovery. "
                "Respects robots.txt. Core discovery falls back to HTTP+heuristics when unavailable."
            ),
            "error": error,
        }

    def robots_allowed(self, url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                resp = client.get(robots_url)
                if resp.status_code >= 400:
                    return True  # no robots file => allow cautious fetch of public pages
                rp.parse(resp.text.splitlines())
            return rp.can_fetch(user_agent, url)
        except Exception:  # noqa: BLE001
            return False

    async def discover_submission_hints(self, homepage: str) -> dict[str, Any]:
        status = self.health()
        if not homepage:
            return {"ok": False, "error": "missing_homepage", **status}
        ua = self.settings.backlink_user_agent
        if not self.robots_allowed(homepage, ua):
            return {
                "ok": False,
                "error": "robots_disallow",
                "homepage": homepage,
                **status,
            }
        if status["enabled"] and status["installed"]:
            return {
                "ok": False,
                "error": "crawl4ai_not_live_tested",
                "message": "Crawl4AI installed but extraction workflow is NEEDS_VERIFICATION.",
                "homepage": homepage,
                **status,
            }
        # Soft fallback: fetch homepage only and look for obvious submit links by href text.
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": ua}) as client:
                resp = client.get(homepage)
            html = resp.text.lower()
            hints = []
            for token in ("submit", "add event", "create event", "post event", "list your event"):
                if token in html:
                    hints.append(token)
            return {
                "ok": True,
                "method": "http_heuristic",
                "http_status": resp.status_code,
                "homepage": homepage,
                "hint_tokens_found": hints,
                "verified_submission_url": None,
                "notes": "Heuristics only; does not invent submission URLs.",
                **status,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "homepage": homepage, **status}
