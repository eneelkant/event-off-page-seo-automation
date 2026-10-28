"""Deterministic Playwright helper with human-verification stops."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from event_seo_mcp.settings import get_settings

HUMAN_CHALLENGE_PATTERNS = [
    re.compile(r"captcha", re.I),
    re.compile(r"verify you are human", re.I),
    re.compile(r"two[- ]factor", re.I),
    re.compile(r"multi[- ]factor", re.I),
    re.compile(r"sign in", re.I),
    re.compile(r"log in", re.I),
]


class HumanVerificationRequired(RuntimeError):
    """Raised when CAPTCHA/MFA/login challenge is detected."""


class PlaywrightBrowser:
    def availability(self) -> dict[str, Any]:
        try:
            import playwright  # noqa: F401

            return {"installed": True, "package": "playwright", "error": None}
        except ImportError as exc:
            return {"installed": False, "package": "playwright", "error": str(exc)}

    def probe_page(self, url: str, *, dry_run: bool = True) -> dict[str, Any]:
        """Open a page, capture basic signals, stop on human verification."""
        avail = self.availability()
        if not avail["installed"]:
            return {
                "ok": False,
                "error": "playwright_not_installed",
                "url": url,
                "evidence_paths": [],
            }
        settings = get_settings()
        evidence_dir = settings.resolve_path(settings.evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot = evidence_dir / f"probe-{uuid4().hex[:10]}.png"

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return {"ok": False, "error": str(exc), "url": url, "evidence_paths": []}

        result: dict[str, Any] = {
            "ok": False,
            "url": url,
            "dry_run": dry_run,
            "evidence_paths": [],
            "human_verification": False,
        }
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=settings.playwright_headless)
                context = browser.new_context()
                page = context.new_page()
                page.set_default_timeout(settings.execution_timeout_seconds * 1000)
                response = page.goto(url, wait_until="domcontentloaded")
                html = page.content()
                title = page.title()
                if any(pat.search(html) or pat.search(title) for pat in HUMAN_CHALLENGE_PATTERNS):
                    page.screenshot(path=str(screenshot))
                    result.update(
                        {
                            "ok": False,
                            "human_verification": True,
                            "error": "human_verification_required",
                            "http_status": response.status if response else None,
                            "title": title,
                            "evidence_paths": [str(screenshot)],
                        }
                    )
                    context.close()
                    browser.close()
                    return result
                page.screenshot(path=str(screenshot))
                result.update(
                    {
                        "ok": True,
                        "http_status": response.status if response else None,
                        "title": title,
                        "evidence_paths": [str(screenshot)],
                    }
                )
                context.close()
                browser.close()
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
        return result

    def fill_known_fields_dry_run(
        self, url: str, fields: dict[str, str]
    ) -> dict[str, Any]:
        """Demonstrate field mapping without submitting forms."""
        probe = self.probe_page(url, dry_run=True)
        probe["planned_fields"] = sorted(fields.keys())
        probe["submitted"] = False
        probe["message"] = "Dry-run only: fields mapped, form not submitted."
        return probe
