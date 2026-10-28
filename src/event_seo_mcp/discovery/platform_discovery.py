"""Load platform registry and run submission discovery (non-inventive)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from event_seo_mcp.integrations.crawl4ai import Crawl4AIIntegration
from event_seo_mcp.schemas.platform import PlatformRecord, PlatformsFile
from event_seo_mcp.settings import Settings, get_settings


def load_platforms_file(path: Path | None = None) -> PlatformsFile:
    settings = get_settings()
    path = path or settings.resolved_platforms_path
    data = json.loads(path.read_text(encoding="utf-8"))
    return PlatformsFile.model_validate(data)


def sync_platforms_to_db(repo, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    platforms = load_platforms_file(settings.resolved_platforms_path)
    for platform in platforms.platforms:
        repo.upsert_platform(platform)
    return len(platforms.platforms)


async def discover_platform(platform: PlatformRecord, settings: Settings | None = None) -> dict[str, Any]:
    """Attempt to discover submission requirements without inventing URLs."""
    settings = settings or get_settings()
    result: dict[str, Any] = {
        "platform_id": platform.platform_id,
        "automation_status": platform.automation_status,
        "verified_submission_url": platform.verified_submission_url,
        "discovery_status": "NEEDS_VERIFICATION",
        "findings": [],
    }
    if platform.verified_submission_url:
        result["findings"].append(
            {
                "type": "existing_verified_url",
                "url": str(platform.verified_submission_url),
                "note": "Already present in registry; still requires workflow live-test before READY.",
            }
        )
    homepage = str(platform.official_homepage) if platform.official_homepage else None
    if not homepage:
        result["findings"].append(
            {
                "type": "missing_homepage",
                "note": "Cannot discover submission destination without a confirmed homepage.",
            }
        )
        return result

    crawl = Crawl4AIIntegration(settings)
    hints = await crawl.discover_submission_hints(homepage)
    result["findings"].append(hints)
    if hints.get("verified_submission_url"):
        result["verified_submission_url"] = hints["verified_submission_url"]
        result["discovery_status"] = "CANDIDATE"
    else:
        result["discovery_status"] = "NEEDS_VERIFICATION"
        result["findings"].append(
            {
                "type": "no_url_invented",
                "note": "No verified submission URL discovered; registry value left unchanged.",
            }
        )
    return result
