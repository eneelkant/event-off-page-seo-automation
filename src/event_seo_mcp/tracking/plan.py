"""Attach tracked landing URLs to a dry-run submission plan.

The canonical URL is copied into the plan response. Persistent event rows
are not updated.
"""

from __future__ import annotations

from typing import Any

from event_seo_mcp.settings import Settings
from event_seo_mcp.tracking.utm import UtmUrlError, build_event_utm_url, normalize_platform

TRACKING_FIELDS = (
    "landing_page_url",
    "campaign_name",
    "utm_medium",
    "utm_content",
    "utm_conflict_policy",
)

PRESERVATION_NOTE = (
    "Directory sites are not assumed to keep query parameters. "
    "A generated URL is a tracking candidate. It is not proof the listing will retain UTM tags, "
    "and it is not proof a backlink exists."
)


def take_tracking_request(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Remove tracking arguments so deadline analysis does not see them."""
    extracted: dict[str, Any] = {}
    for key in TRACKING_FIELDS:
        if key in payload:
            extracted[key] = payload.pop(key)
    if not any(value not in (None, "") for value in extracted.values()):
        return None
    return extracted


def build_submission_tracking(
    target_ids: list[str],
    request: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Build reproducible tracked URLs for planned targets.

    An invalid URL is reported on the plan. It does not change eligibility
    and it does not publish.
    """
    medium = request.get("utm_medium") or settings.utm_default_medium
    content = request.get("utm_content") or settings.utm_default_content
    policy = request.get("utm_conflict_policy") or settings.utm_conflict_policy
    landing = request.get("landing_page_url")
    campaign = request.get("campaign_name")
    report: dict[str, Any] = {
        "dry_run": True,
        "would_publish": False,
        "stored_landing_page_modified": False,
        "canonical_landing_page_url": landing if isinstance(landing, str) else None,
        "campaign_name": campaign if isinstance(campaign, str) else None,
        "utm_medium": medium,
        "utm_content": content,
        "conflict_policy": policy,
        "utm_parameter_preservation": "unknown",
        "preservation_note": PRESERVATION_NOTE,
        "configuration": {
            "utm_source_rule": "normalized_platform_id",
            "utm_medium": medium,
            "utm_content": content,
            "utm_campaign": campaign if isinstance(campaign, str) else None,
            "conflict_policy": policy,
        },
        "links": [],
        "error": None,
        "message": None,
    }
    if not isinstance(landing, str) or not landing.strip() or not isinstance(campaign, str) or not campaign.strip():
        report["error"] = "tracking_not_configured"
        report["message"] = "landing_page_url and campaign_name are both required to generate tracked URLs."
        return report
    try:
        build_event_utm_url(
            landing,
            "event_directory",
            campaign,
            medium=str(medium),
            content=str(content),
            conflict_policy=str(policy),
        )
    except UtmUrlError as exc:
        report["error"] = exc.code
        report["message"] = exc.message
        return report
    links: list[dict[str, Any]] = []
    for target_id in target_ids:
        links.append(_one_link(target_id, landing, campaign, medium, content, policy))
    report["links"] = links
    failed = [item for item in links if item["error"]]
    if links and len(failed) == len(links):
        report["error"] = failed[0]["error"]
        report["message"] = failed[0]["message"]
    return report


def _one_link(
    target_id: str,
    landing: str,
    campaign: str,
    medium: str,
    content: str,
    policy: str,
) -> dict[str, Any]:
    link: dict[str, Any] = {
        "target_id": target_id,
        "platform": None,
        "canonical_landing_page_url": landing,
        "tracked_landing_page_url": None,
        "utm_parameter_preservation": "unknown",
        "error": None,
        "message": None,
    }
    try:
        platform = normalize_platform(target_id)
        tracked = build_event_utm_url(
            landing,
            platform,
            campaign,
            medium=str(medium),
            content=str(content),
            conflict_policy=str(policy),
        )
    except UtmUrlError as exc:
        link["error"] = exc.code
        link["message"] = exc.message
        return link
    link["platform"] = platform
    link["tracked_landing_page_url"] = tracked
    return link
