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
    # Backward compat: v0.1 files had only platforms[] without workflows/categories.
    if "workflows" not in data:
        data["workflows"] = []
    if "categories" not in data:
        data["categories"] = sorted({p.get("category") for p in data.get("platforms", []) if p.get("category")})
    return PlatformsFile.model_validate(data)


def sync_platforms_to_db(repo, settings: Settings | None = None) -> int:
    """Persist distinct platforms + workflow submit entries (35 registry rows)."""
    settings = settings or get_settings()
    registry = load_platforms_file(settings.resolved_platforms_path)
    # Store all distinct platforms (including LinkedIn parent) and all workflows.
    seen: set[str] = set()
    count = 0
    for platform in list(registry.platforms) + list(registry.workflows):
        if platform.platform_id in seen:
            continue
        seen.add(platform.platform_id)
        repo.upsert_platform(platform)
        count += 1
    return count


def registry_stats(path: Path | None = None) -> dict[str, Any]:
    registry = load_platforms_file(path)
    checks = registry.validate_totals()
    return {
        "version": registry.version,
        "totals": registry.totals,
        "validation": checks,
        "categories": registry.categories,
        "platform_ids": [p.platform_id for p in registry.platforms],
        "workflow_ids": [w.workflow_id or w.platform_id for w in registry.workflows],
        "registry_entry_ids": [e.platform_id for e in registry.registry_entries()],
    }


async def discover_platform(platform: PlatformRecord, settings: Settings | None = None) -> dict[str, Any]:
    """Attempt to discover submission requirements without inventing URLs."""
    settings = settings or get_settings()
    result: dict[str, Any] = {
        "platform_id": platform.platform_id,
        "automation_status": platform.automation_status,
        "verified_submission_url": platform.verified_submission_url,
        "discovery_status": "NEEDS_VERIFICATION",
        "research": platform.research.model_dump(mode="json"),
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
