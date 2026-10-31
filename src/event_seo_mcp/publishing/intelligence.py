"""Registry-backed publication policy, deadlines, and SEO drafts.

Publication timelines stay unknown unless a caller supplies documented hours.
This module does not scrape websites and does not connect to an seo-agent API.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from event_seo_mcp.database.repository import Repository
from event_seo_mcp.discovery.platform_discovery import load_platforms_file
from event_seo_mcp.providers.template_provider import TemplateProvider
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.settings import Settings

ELIGIBLE = "ELIGIBLE"
ELIGIBLE_WITH_RISK = "ELIGIBLE_WITH_RISK"
DEADLINE_PASSED = "DEADLINE_PASSED"
PUBLICATION_TIME_UNKNOWN = "PUBLICATION_TIME_UNKNOWN"
NOT_FREE = "NOT_FREE"
NOT_SUPPORTED = "NOT_SUPPORTED"
MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
ALREADY_SUBMITTED = "ALREADY_SUBMITTED"
ALREADY_PUBLISHED = "ALREADY_PUBLISHED"
EVENT_PAST = "EVENT_PAST"

_SUBMITTED_STATES = {
    "SUBMITTING",
    "SUBMITTED",
    "PENDING_REVIEW",
    "AWAITING_APPROVAL",
    "CONTENT_PREPARED",
    "DUPLICATE",
}


class PublishingIntelligence:
    def __init__(self, repo: Repository, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings

    def publication_policy(self, platform_id: str | None = None) -> dict[str, Any]:
        registry = load_platforms_file(self.settings.resolved_platforms_path)
        rows = list(registry.platforms) + list(registry.workflows)
        if platform_id:
            match = registry.by_id(platform_id)
            if match is None:
                return {"error": "platform_not_found", "platform_id": platform_id}
            rows = [match]
        policies = [_policy(row) for row in rows]
        return {
            "count": len(policies),
            "targets": policies,
            "timelines_invented": False,
            "seo_agent_connected": False,
        }

    def research_publication_time(self, platform_id: str) -> dict[str, Any]:
        policy = self.publication_policy(platform_id)
        if policy.get("error"):
            return policy
        target = policy["targets"][0]
        return {
            "platform_id": platform_id,
            "submission_processing_time": "unknown",
            "moderation_approval_time": target["approval_time_basis"],
            "publication_time": target["publication_time_basis"],
            "internal_search_visibility": target["search_visibility_time"],
            "search_engine_indexing_time": target["google_indexing_estimate"],
            "ranking_time": "not_estimated",
            "publication_time_confidence": target["publication_time_confidence"],
            "source_urls": _source_urls(target),
            "verified_at": target["publication_time_verified_at"],
            "note": (
                "These clocks are recorded separately. Unknown means the registry "
                "has no official commitment. This is not a guarantee."
            ),
        }

    def refresh_research(self) -> dict[str, Any]:
        policies = self.publication_policy()["targets"]
        now = _utc_now().isoformat()
        counts = {"researched": 0, "partial": 0, "manual_review": 0, "inaccessible": 0}
        for policy in policies:
            if policy["base_url"] is None and not policy["official_guidelines_url"]:
                bucket = "inaccessible"
            elif policy["publication_time_confidence"] == "unknown":
                bucket = "manual_review"
            elif policy["research_notes"]:
                bucket = "partial"
            else:
                bucket = "researched"
            if policy["publication_time_source_url"]:
                bucket = "partial" if policy["publication_time_confidence"] == "unknown" else "researched"
            counts[bucket] = counts.get(bucket, 0) + 1
            self.repo.db.execute(
                """
                INSERT INTO target_research_snapshots(platform_id, payload_json, refreshed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(platform_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    refreshed_at = excluded.refreshed_at
                """,
                (policy["target_id"], json.dumps(policy), now),
            )
        return {
            "refreshed_at": now,
            "count": len(policies),
            "counts": counts,
            "persisted": True,
            "persistence_note": (
                "Snapshots are stored in SQLite at DATABASE_PATH. Fly.io has no volume "
                "in fly.toml, so a machine restart can drop this database."
            ),
        }

    def generate_seo_content(
        self,
        *,
        event_name: str,
        event_description: str,
        event_start_datetime: str,
        event_timezone: str,
        landing_page_url: str,
        registration_url: str,
        organizer_name: str,
        target_website: str,
        event_end_datetime: str | None = None,
        location: str | None = None,
        virtual_event_details: str | None = None,
        target_audience: str | None = None,
        primary_keyword: str | None = None,
        secondary_keywords: list[str] | None = None,
        content_source: str = "template",
        content_language: str = "en",
        event_status: str = "https://schema.org/EventScheduled",
        title_limit: int = 70,
        description_limit: int = 160,
    ) -> dict[str, Any]:
        if content_source == "seo-agent":
            return {
                "error": "seo_agent_not_configured",
                "message": (
                    "seo-agent is not an existing integration. Set content_source to template, "
                    "or connect a provider and credentials before requesting seo-agent."
                ),
                "content_source": content_source,
            }
        problems = _content_problems(
            event_name=event_name,
            event_description=event_description,
            event_start_datetime=event_start_datetime,
            event_timezone=event_timezone,
            landing_page_url=landing_page_url,
            registration_url=registration_url,
            organizer_name=organizer_name,
            target_website=target_website,
            location=location,
            virtual_event_details=virtual_event_details,
        )
        if problems:
            return {"error": "validation_error", "message": "; ".join(problems), "tracked": False}

        start = _parse_zoned(event_start_datetime, event_timezone)
        assert start is not None
        registry = load_platforms_file(self.settings.resolved_platforms_path)
        platform = registry.by_id(target_website)
        site_name = platform.platform_name if platform else target_website
        keyword = (primary_keyword or event_name).strip()
        secondary = [item.strip() for item in (secondary_keywords or []) if item and item.strip()]
        place = (location or "").strip() or (virtual_event_details or "").strip()
        audience = (target_audience or "the stated audience").strip()
        seo_title = event_name if len(event_name) <= title_limit else event_name[: title_limit - 1].rstrip() + "…"
        description = (
            f"{event_name} is scheduled for {start.isoformat()} ({event_timezone}) in {place}. "
            f"{event_description.strip()} Audience: {audience}. "
            f"Register: {registration_url}"
        )
        if keyword.lower() not in description.lower():
            description = f"{description} Keyword: {keyword}."
        meta = description if len(description) <= description_limit else description[: description_limit - 1].rstrip() + "…"
        body = (
            f"# {event_name}\n\n"
            f"{event_description.strip()}\n\n"
            f"## When and where\n\n"
            f"- Start: {start.isoformat()} ({event_timezone})\n"
            f"- Place: {place}\n"
            f"- Audience: {audience}\n"
            f"- Language: {content_language}\n\n"
            f"## Registration\n\n"
            f"Landing page: {landing_page_url}\n\n"
            f"Registration: {registration_url}\n\n"
            f"Prepared for {site_name}. Facts are limited to the fields supplied for this request."
        )
        if secondary:
            body += "\n\nRelated terms: " + ", ".join(secondary) + "."
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        warnings = _quality_warnings(
            event_name=event_name,
            seo_title=seo_title,
            meta=meta,
            body=body,
            keyword=keyword,
            title_limit=title_limit,
            description_limit=description_limit,
            landing_page_url=landing_page_url,
            registration_url=registration_url,
        )
        structured = {
            "@context": "https://schema.org",
            "@type": "Event",
            "name": event_name,
            "description": event_description.strip(),
            "startDate": start.isoformat(),
            "eventStatus": event_status,
            "eventAttendanceMode": (
                "https://schema.org/OnlineEventAttendanceMode"
                if (virtual_event_details or "").strip() and not (location or "").strip()
                else "https://schema.org/OfflineEventAttendanceMode"
            ),
            "url": landing_page_url,
            "organizer": {"@type": "Organization", "name": organizer_name},
        }
        if event_end_datetime:
            end = _parse_zoned(event_end_datetime, event_timezone)
            if end is not None:
                structured["endDate"] = end.isoformat()
        return {
            "event_name": event_name,
            "content_source": "template" if content_source in {"", "template"} else content_source,
            "seo_agent_connected": False,
            "target_website": site_name,
            "seo_title": seo_title,
            "meta_description": meta,
            "body": body,
            "official_event_name_preserved": event_name in body and event_name == structured["name"],
            "content_hash": digest,
            "generated_at": _utc_now().isoformat(),
            "quality_report": {"warnings": warnings, "missing_fields": []},
            "structured_data": structured,
            "rankings_promised": False,
        }

    def analyze_deadlines(
        self,
        *,
        event_name: str,
        event_start_datetime: str,
        event_timezone: str,
        submission_datetime: str | None = None,
        publication_deadline_buffer_hours: int = 24,
        conservative_fallback_hours: int | None = None,
        allow_paid: bool = False,
        virtual_event: bool | None = None,
        event_id: str | None = None,
        documented_hours_by_platform: dict[str, int] | None = None,
        documented_business_days_by_platform: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        start = _parse_zoned(event_start_datetime, event_timezone)
        if start is None:
            return {"error": "validation_error", "message": "event_start_datetime must be a timezone-aware ISO-8601 datetime"}
        planned = _parse_zoned(submission_datetime, "UTC") if submission_datetime else _utc_now()
        if submission_datetime and planned is None:
            return {"error": "validation_error", "message": "submission_datetime must be ISO-8601"}
        assert planned is not None
        policies = self.publication_policy()["targets"]
        hours_override = documented_hours_by_platform or {}
        business_override = documented_business_days_by_platform or {}
        decisions = [
            self._decide(
                policy,
                start=start,
                planned=planned,
                buffer_hours=publication_deadline_buffer_hours,
                fallback_hours=conservative_fallback_hours,
                allow_paid=allow_paid,
                virtual_event=virtual_event,
                event_id=event_id,
                documented_hours=hours_override.get(policy["target_id"]),
                documented_business_days=business_override.get(policy["target_id"]),
            )
            for policy in policies
            if not policy["is_workflow"]
        ]
        groups = {key: [] for key in (
            ELIGIBLE,
            ELIGIBLE_WITH_RISK,
            DEADLINE_PASSED,
            PUBLICATION_TIME_UNKNOWN,
            NOT_FREE,
            NOT_SUPPORTED,
            MANUAL_REVIEW_REQUIRED,
            ALREADY_SUBMITTED,
            ALREADY_PUBLISHED,
            EVENT_PAST,
        )}
        for row in decisions:
            groups.setdefault(row["eligibility_status"], []).append(row["target_id"])
        recommended = [
            row["target_id"]
            for row in sorted(decisions, key=_rank)
            if row["eligibility_status"] in {ELIGIBLE, ELIGIBLE_WITH_RISK}
        ]
        return {
            "event_name": event_name,
            "event_start": start.isoformat(),
            "planning_datetime": planned.isoformat(),
            "total_targets": len(decisions),
            "free_targets": sum(1 for row in decisions if row["free_submission_available"] is True),
            "eligible": groups[ELIGIBLE],
            "eligible_with_risk": groups[ELIGIBLE_WITH_RISK],
            "excluded_deadlines": groups[DEADLINE_PASSED],
            "unknown_timelines": groups[PUBLICATION_TIME_UNKNOWN],
            "paid_or_not_free": groups[NOT_FREE],
            "manual_review": groups[MANUAL_REVIEW_REQUIRED],
            "recommended_submission_order": recommended,
            "decisions": decisions,
            "indexing_is_not_publication": True,
            "publication_guaranteed": False,
        }

    def preview_plan(self, **kwargs: Any) -> dict[str, Any]:
        analysis = self.analyze_deadlines(**kwargs)
        if analysis.get("error"):
            return analysis
        previews = []
        for row in analysis["decisions"]:
            if row["eligibility_status"] not in {ELIGIBLE, ELIGIBLE_WITH_RISK}:
                continue
            previews.append(
                {
                    "target_id": row["target_id"],
                    "website_name": row["website_name"],
                    "eligibility_status": row["eligibility_status"],
                    "eligibility_reason": row["eligibility_reason"],
                    "dry_run": True,
                    "would_publish": False,
                }
            )
        return {"preview": previews, "dry_run": True, "analysis": analysis}

    def _decide(
        self,
        policy: dict[str, Any],
        *,
        start: datetime,
        planned: datetime,
        buffer_hours: int,
        fallback_hours: int | None,
        allow_paid: bool,
        virtual_event: bool | None,
        event_id: str | None,
        documented_hours: int | None,
        documented_business_days: int | None,
    ) -> dict[str, Any]:
        existing = _existing_job(self.repo, event_id, policy["target_id"])
        reason = ""
        status = PUBLICATION_TIME_UNKNOWN
        hours = documented_hours
        heuristic = False
        if existing == "PUBLISHED":
            status = ALREADY_PUBLISHED
            reason = "A stored job for this event and target is already PUBLISHED."
        elif existing:
            status = ALREADY_SUBMITTED
            reason = "A stored job already exists for this event and target."
        elif start <= planned:
            status = EVENT_PAST
            reason = "The event start is not after the planning time, so ordinary pre-event promotion is not recommended."
        elif policy["automation_status"] == "BLOCKED":
            status = NOT_SUPPORTED
            reason = "The registry marks this target BLOCKED."
        elif policy["free_submission_available"] is False and not allow_paid:
            status = NOT_FREE
            reason = "The registry records this target as not a free submission, and paid options are disabled."
        elif virtual_event is True and policy["supports_virtual_events"] is False:
            status = NOT_SUPPORTED
            reason = "The registry records that this target does not support virtual events."
        elif virtual_event is False and policy["supports_physical_events"] is False:
            status = NOT_SUPPORTED
            reason = "The registry records that this target does not support physical events."
        elif hours is None and policy["approval_time_max_hours"] is None:
            if fallback_hours is None:
                status = PUBLICATION_TIME_UNKNOWN
                reason = "No documented publication window is stored. The target is excluded from the default plan."
            else:
                hours = fallback_hours
                heuristic = True
        if status in {ALREADY_PUBLISHED, ALREADY_SUBMITTED, EVENT_PAST, NOT_SUPPORTED, NOT_FREE, PUBLICATION_TIME_UNKNOWN} and not (
            status == PUBLICATION_TIME_UNKNOWN and (hours is not None or documented_business_days is not None)
        ):
            return _decision_row(policy, status, reason, start, planned, None, None, heuristic)

        if documented_business_days is not None:
            latest = subtract_business_days(start, documented_business_days) - timedelta(hours=buffer_hours)
            hours = documented_business_days * 24
        else:
            assert hours is not None
            latest = start - timedelta(hours=hours) - timedelta(hours=buffer_hours)
        if planned > latest:
            status = DEADLINE_PASSED
            reason = "The latest safe submission time, using the supplied window plus the safety buffer, has passed."
        elif heuristic:
            status = ELIGIBLE_WITH_RISK
            reason = (
                f"Heuristic fallback of {hours} hours was supplied by the caller. "
                "This is an estimate, not an official publication commitment."
            )
        elif documented_business_days is not None:
            status = ELIGIBLE
            reason = (
                f"Caller supplied a documented window of {documented_business_days} business days "
                "plus the safety buffer, and it fits before the event start."
            )
        else:
            status = ELIGIBLE
            reason = "The documented publication window plus the safety buffer fits before the event start."
        if policy["free_submission_available"] is not True and status in {ELIGIBLE, ELIGIBLE_WITH_RISK}:
            status = MANUAL_REVIEW_REQUIRED
            reason = "Timing was calculated, but a free listing is not proven from the registry."
        return _decision_row(policy, status, reason, start, planned, latest, hours, heuristic)


def _decision_row(
    policy: dict[str, Any],
    status: str,
    reason: str,
    start: datetime,
    planned: datetime,
    latest: datetime | None,
    hours: int | None,
    heuristic: bool,
) -> dict[str, Any]:
    return {
        "target_id": policy["target_id"],
        "website_name": policy["website_name"],
        "eligibility_status": status,
        "eligibility_reason": reason,
        "free_submission_available": policy["free_submission_available"],
        "publication_time_confidence": "heuristic" if heuristic else policy["publication_time_confidence"],
        "conservative_publication_hours": hours,
        "latest_safe_submission_datetime": latest.isoformat() if latest else None,
        "hours_until_event": round((start - planned).total_seconds() / 3600, 2),
        "search_indexing_separate": True,
    }


def _rank(row: dict[str, Any]) -> tuple:
    order = {ELIGIBLE: 0, ELIGIBLE_WITH_RISK: 1}
    return (order.get(row["eligibility_status"], 9), row["website_name"])


def _existing_job(repo: Repository, event_id: str | None, platform_id: str) -> str | None:
    if not event_id:
        return None
    jobs = repo.list_jobs(event_id=event_id, platform_id=platform_id)
    if not jobs:
        return None
    state = str(jobs[0].state.value if hasattr(jobs[0].state, "value") else jobs[0].state)
    if state == "PUBLISHED":
        return "PUBLISHED"
    if state in _SUBMITTED_STATES or state not in {"FAILED", "REJECTED", "BLOCKED"}:
        return "SUBMITTED"
    return None


def _policy(platform: PlatformRecord) -> dict[str, Any]:
    paid = platform.paid_submission_possible
    if platform.policy.paid_submission_possible is not None:
        paid = platform.policy.paid_submission_possible
    free: bool | None
    if paid is False:
        free = True
    elif paid is True:
        free = False
    else:
        free = None
    sources = [str(source.url) for source in platform.research.sources if source.url]
    guidelines = str(platform.documentation_url) if platform.documentation_url else None
    homepage = str(platform.official_homepage) if platform.official_homepage else None
    submission = str(platform.verified_submission_url) if platform.verified_submission_url else None
    verified_at = platform.research.researched_at or (
        platform.last_verified_at.isoformat() if platform.last_verified_at else None
    )
    supports_virtual = (
        True if "virtual_event" in platform.required_fields or "virtual_event" in platform.optional_fields else None
    )
    supports_physical = (
        True
        if any(field in platform.required_fields or field in platform.optional_fields for field in ("venue_name", "city"))
        else None
    )
    return {
        "target_id": platform.platform_id,
        "website_name": platform.platform_name,
        "base_url": homepage,
        "submission_url": submission,
        "official_guidelines_url": guidelines,
        "pricing_url": None,
        "free_submission_available": free,
        "free_listing_conditions": (
            "Registry field paid_submission_possible is false. This is not an official promise that a public listing is free."
            if free is True
            else None
        ),
        "paid_options_available": True if paid is True else (False if paid is False else None),
        "account_required": None,
        "email_verification_required": None,
        "organization_verification_required": None,
        "manual_review_required": platform.approval_required,
        "approval_time_min_hours": None,
        "approval_time_max_hours": None,
        "approval_time_unit": None,
        "approval_time_business_days": None,
        "approval_time_basis": "unknown",
        "publication_time_basis": "not_guaranteed",
        "publication_time_confidence": "unknown",
        "publication_time_source_url": guidelines,
        "publication_time_verified_at": verified_at,
        "search_visibility_time": "unknown",
        "search_visibility_source_url": None,
        "google_indexing_estimate": "unknown",
        "google_indexing_source_url": None,
        "supported_event_types": [platform.category],
        "supports_virtual_events": supports_virtual,
        "supports_physical_events": supports_physical,
        "geographic_restrictions": None,
        "content_requirements": platform.required_fields,
        "link_policy": None,
        "automation_method": platform.submission_method,
        "automation_status": platform.automation_status,
        "terms_compliance_notes": platform.operational_notes,
        "target_status": "manual_review" if platform.automation_status != "READY" else "registry_ready_timeline_unknown",
        "research_notes": platform.research.notes,
        "unknown_fields": platform.research.unknown_fields,
        "is_workflow": platform.is_workflow,
        "source_urls": sources,
    }


def _source_urls(target: dict[str, Any]) -> list[str]:
    urls = list(target.get("source_urls") or [])
    for key in ("official_guidelines_url", "base_url", "submission_url"):
        value = target.get(key)
        if value and value not in urls:
            urls.append(value)
    return urls


def _content_problems(**fields: Any) -> list[str]:
    problems: list[str] = []
    if not str(fields["event_name"] or "").strip():
        problems.append("event_name is required")
    if not str(fields["event_description"] or "").strip():
        problems.append("event_description is required")
    if not str(fields["organizer_name"] or "").strip():
        problems.append("organizer_name is required")
    if not str(fields["target_website"] or "").strip():
        problems.append("target_website is required")
    if _parse_zoned(str(fields["event_start_datetime"] or ""), str(fields["event_timezone"] or "")) is None:
        problems.append("event_start_datetime must be ISO-8601 in a valid IANA timezone")
    from event_seo_mcp.integrations.google_sheets.service import valid_http_url

    if not valid_http_url(str(fields["landing_page_url"] or "")):
        problems.append("landing_page_url must be an http or https URL")
    if not valid_http_url(str(fields["registration_url"] or "")):
        problems.append("registration_url must be an http or https URL")
    if not str(fields["location"] or "").strip() and not str(fields["virtual_event_details"] or "").strip():
        problems.append("location or virtual_event_details is required")
    return problems


def _quality_warnings(**fields: Any) -> list[str]:
    warnings: list[str] = []
    if fields["event_name"] not in fields["seo_title"]:
        warnings.append("seo_title does not contain the full official event name")
    if len(fields["seo_title"]) > fields["title_limit"]:
        warnings.append("seo_title exceeds the target length")
    if len(fields["meta"]) > fields["description_limit"]:
        warnings.append("meta_description exceeds the target length")
    if fields["keyword"].lower() not in fields["body"].lower():
        warnings.append("primary keyword is missing from the body")
    if fields["landing_page_url"] not in fields["body"] or fields["registration_url"] not in fields["body"]:
        warnings.append("a required URL is missing from the body")
    return warnings


def _parse_zoned(value: str, timezone_name: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def subtract_business_days(moment: datetime, days: int) -> datetime:
    current = moment
    remaining = days
    while remaining > 0:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def template_available() -> bool:
    return TemplateProvider().available()
