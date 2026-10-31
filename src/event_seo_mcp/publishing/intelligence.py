"""Registry-backed publication policy, deadlines, and SEO drafts.

This module reads config/platforms.json. It does not fetch official websites,
does not invent publication times, and does not connect to an seo-agent API.
A target is free only when a complete official citation says so.
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

SUPPORTED_CONTENT_SOURCES = frozenset({"template"})
SUPPORTED_EVENT_STATUSES = frozenset(
    {
        "https://schema.org/EventScheduled",
        "https://schema.org/EventCancelled",
        "https://schema.org/EventMovedOnline",
        "https://schema.org/EventPostponed",
        "https://schema.org/EventRescheduled",
    }
)

MAX_PUBLICATION_HOURS = 24 * 366
MAX_BUSINESS_DAYS = 366
MAX_BUFFER_HOURS = 24 * 90
MAX_TITLE_LIMIT = 300
MAX_DESCRIPTION_LIMIT = 1000

LIVE_RESEARCH_LIMITATION = (
    "Live research of official submission guidelines is not implemented. "
    "This tool reads the local registry and any complete citation stored there "
    "or supplied by the caller. It does not fetch pages, and it does not turn "
    "a missing value into an official publication time."
)

_SUBMITTED_STATES = {
    "SUBMITTING",
    "SUBMITTED",
    "PENDING_REVIEW",
    "AWAITING_APPROVAL",
    "CONTENT_PREPARED",
    "DUPLICATE",
}

_EMPTY_WINDOW = {
    "official_publication_hours": None,
    "official_publication_business_days": None,
    "official_publication_kind": None,
    "official_publication_source_url": None,
    "official_publication_verified_at": None,
    "official_publication_summary": None,
    "publication_evidence_note": None,
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
            "live_research_performed": False,
            "research_status": "registry_only",
            "research_limitation": LIVE_RESEARCH_LIMITATION,
        }

    def research_publication_time(self, platform_id: str) -> dict[str, Any]:
        policy = self.publication_policy(platform_id)
        if policy.get("error"):
            return policy
        target = policy["targets"][0]
        publication_time = "unknown"
        publication_time_kind = "unknown"
        confidence = "none"
        if target["official_publication_hours"] is not None:
            publication_time = f"{target['official_publication_hours']} hours"
            publication_time_kind = target["official_publication_kind"]
            confidence = "registry_citation"
        elif target["official_publication_business_days"] is not None:
            publication_time = f"{target['official_publication_business_days']} business days"
            publication_time_kind = target["official_publication_kind"]
            confidence = "registry_citation"
        return {
            "platform_id": platform_id,
            "research_status": "not_live_researched",
            "live_research_performed": False,
            "research_method": "registry_read",
            "research_timestamp": None,
            "registry_recorded_at": target["publication_time_verified_at"],
            "limitation": LIVE_RESEARCH_LIMITATION,
            "free_submission_eligibility": target["pricing_status"],
            "free_submission_available": target["free_submission_available"],
            "free_submission_conditions": target["free_listing_conditions"],
            "paid_options_available": target["paid_options_available"],
            "pricing_reason": target["pricing_reason"],
            "pricing_evidence_url": target["pricing_evidence_url"],
            "pricing_verified_at": target["pricing_verified_at"],
            "account_required": "unknown",
            "email_verification_required": "unknown",
            "organization_verification_required": "unknown",
            "submission_processing_time": "unknown",
            "moderation_approval_time": "unknown",
            "approval_time_kind": "unknown",
            "publication_time": publication_time,
            "publication_time_kind": publication_time_kind,
            "publication_time_confidence": "unknown" if confidence == "none" else confidence,
            "internal_search_visibility": "unknown",
            "search_engine_indexing_time": "unknown",
            "google_indexing_estimate": "unknown",
            "indexing_separate_from_publication": True,
            "ranking_time": "not_estimated",
            "official_source_url": target["official_publication_source_url"] or target["official_guidelines_url"],
            "evidence_summary": (
                "No live research was performed. Registry fields were read only. "
                + (
                    "A stored publication citation is reported separately from Google indexing."
                    if confidence == "registry_citation"
                    else "Publication time, approval time, and indexing time remain unknown."
                )
            ),
            "confidence": confidence,
            "value_origin": "registry_citation" if confidence == "registry_citation" else "unknown",
            "source_urls": _source_urls(target),
            "registry_sources_are_not_live_research": True,
            "note": (
                "Submission, moderation, publication, internal search, and Google indexing "
                "are separate clocks. Unknown means no reliable evidence is stored. "
                "A registry citation is not a live fetch and is not a new guarantee."
            ),
        }

    def refresh_research(self) -> dict[str, Any]:
        policies = self.publication_policy()["targets"]
        now = _utc_now().isoformat()
        counts = {"registry_only": 0, "live_researched": 0, "missing_official_url": 0}
        for policy in policies:
            counts["registry_only"] += 1
            if not policy["base_url"] and not policy["official_guidelines_url"]:
                counts["missing_official_url"] += 1
            snapshot = dict(policy)
            snapshot["research_status"] = "registry_only"
            snapshot["live_research_performed"] = False
            self.repo.db.execute(
                """
                INSERT INTO target_research_snapshots(platform_id, payload_json, refreshed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(platform_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    refreshed_at = excluded.refreshed_at
                """,
                (policy["target_id"], json.dumps(snapshot), now),
            )
        return {
            "refreshed_at": now,
            "count": len(policies),
            "counts": counts,
            "research_status": "registry_only",
            "live_research_performed": False,
            "research_method": "registry_read",
            "limitation": LIVE_RESEARCH_LIMITATION,
            "persisted": True,
            "persistence_note": (
                "Snapshots are stored in SQLite at DATABASE_PATH. Fly.io has no volume "
                "in fly.toml, so a machine restart can drop this database. "
                "Persisting a registry read is not live research."
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
        source = str(content_source or "").strip()
        if source == "seo-agent":
            return {
                "error": "seo_agent_not_configured",
                "message": (
                    "seo-agent is not connected. No provider, credentials, or response "
                    "was invented. The only supported content_source is template."
                ),
                "content_source": "seo-agent",
                "seo_agent_connected": False,
                "supported_content_sources": sorted(SUPPORTED_CONTENT_SOURCES),
            }
        if source not in SUPPORTED_CONTENT_SOURCES:
            return {
                "error": "unsupported_content_source",
                "message": (
                    "content_source must be template. Unsupported values are rejected "
                    "instead of being relabeled as template output."
                ),
                "content_source": content_source,
                "seo_agent_connected": False,
                "supported_content_sources": sorted(SUPPORTED_CONTENT_SOURCES),
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
            content_language=content_language,
            event_status=event_status,
            title_limit=title_limit,
            description_limit=description_limit,
            event_end_datetime=event_end_datetime,
        )
        if problems:
            return {"error": "validation_error", "message": "; ".join(problems), "tracked": False, "seo_agent_connected": False}

        start = _parse_zoned(event_start_datetime, event_timezone)
        assert start is not None
        registry = load_platforms_file(self.settings.resolved_platforms_path)
        platform = registry.by_id(target_website)
        site_name = platform.platform_name if platform else target_website
        keyword = (primary_keyword or event_name).strip()
        secondary = [item.strip() for item in (secondary_keywords or []) if item and item.strip()]
        place_parts = [part.strip() for part in (location, virtual_event_details) if part and part.strip()]
        place = "; ".join(place_parts)
        audience = (target_audience or "").strip()
        seo_title = event_name
        description = (
            f"{event_name} is scheduled for {start.isoformat()} ({event_timezone}) in {place}. "
            f"{event_description.strip()}"
        )
        if audience:
            description = f"{description} Audience: {audience}."
        description = f"{description} Register: {registration_url}"
        if keyword and keyword.lower() not in description.lower():
            description = f"{description} Keyword: {keyword}."
        meta = description
        body = (
            f"# {event_name}\n\n"
            f"{event_description.strip()}\n\n"
            f"## When and where\n\n"
            f"- Start: {start.isoformat()} ({event_timezone})\n"
            f"- Place: {place}\n"
            f"- Organizer: {organizer_name.strip()}\n"
        )
        if audience:
            body += f"- Audience: {audience}\n"
        body += (
            f"- Language: {content_language.strip()}\n\n"
            f"## Registration\n\n"
            f"Landing page: {landing_page_url}\n\n"
            f"Registration: {registration_url}\n\n"
            f"Prepared for {site_name}. Facts are limited to the fields supplied for this request."
        )
        if secondary:
            body += "\n\nRelated terms supplied by the caller: " + ", ".join(secondary) + "."
        if event_end_datetime:
            end = _parse_zoned(event_end_datetime, event_timezone)
            assert end is not None
            body += f"\n\nEnd: {end.isoformat()} ({event_timezone})."
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        title_within_limit = len(seo_title) <= title_limit
        meta_within_limit = len(meta) <= description_limit
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
            title_within_limit=title_within_limit,
            meta_within_limit=meta_within_limit,
        )
        attendance = (
            "https://schema.org/OnlineEventAttendanceMode"
            if (virtual_event_details or "").strip() and not (location or "").strip()
            else "https://schema.org/OfflineEventAttendanceMode"
        )
        if (virtual_event_details or "").strip() and (location or "").strip():
            attendance = "https://schema.org/MixedEventAttendanceMode"
        structured: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "Event",
            "name": event_name,
            "description": event_description.strip(),
            "startDate": start.isoformat(),
            "eventStatus": event_status,
            "eventAttendanceMode": attendance,
            "url": landing_page_url,
            "organizer": {"@type": "Organization", "name": organizer_name.strip()},
        }
        if (location or "").strip():
            structured["location"] = {"@type": "Place", "name": location.strip()}
        elif (virtual_event_details or "").strip():
            structured["location"] = {
                "@type": "VirtualLocation",
                "description": virtual_event_details.strip(),
                "url": landing_page_url,
            }
        if event_end_datetime:
            end = _parse_zoned(event_end_datetime, event_timezone)
            assert end is not None
            structured["endDate"] = end.isoformat()
        preserved = event_name == seo_title == structured["name"] and event_name in body
        return {
            "event_name": event_name,
            "content_source": "template",
            "seo_agent_connected": False,
            "target_website": site_name,
            "seo_title": seo_title,
            "meta_description": meta,
            "body": body,
            "official_event_name_preserved": preserved,
            "content_hash": digest,
            "generated_at": _utc_now().isoformat(),
            "quality_report": {
                "warnings": warnings,
                "missing_fields": [],
                "seo_title_within_limit": title_within_limit,
                "meta_description_within_limit": meta_within_limit,
                "official_event_name_preserved": preserved,
                "unsupplied_claims_added": False,
            },
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
        official_publication_windows_by_platform: dict[str, Any] | None = None,
        pricing_evidence_by_platform: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timing_error = _validate_timing_inputs(
            publication_deadline_buffer_hours=publication_deadline_buffer_hours,
            conservative_fallback_hours=conservative_fallback_hours,
            documented_hours_by_platform=documented_hours_by_platform,
            documented_business_days_by_platform=documented_business_days_by_platform,
            official_publication_windows_by_platform=official_publication_windows_by_platform,
            pricing_evidence_by_platform=pricing_evidence_by_platform,
        )
        if timing_error:
            return {"error": "validation_error", "message": timing_error}
        start = _parse_zoned(event_start_datetime, event_timezone)
        if start is None:
            return {
                "error": "validation_error",
                "message": "event_start_datetime must be a timezone-aware ISO-8601 datetime with a time component",
            }
        planned = _parse_zoned(submission_datetime, "UTC") if submission_datetime else _utc_now()
        if submission_datetime and planned is None:
            return {"error": "validation_error", "message": "submission_datetime must be an ISO-8601 datetime with a time component"}
        assert planned is not None
        policies = self.publication_policy()["targets"]
        hours_override = documented_hours_by_platform or {}
        business_override = documented_business_days_by_platform or {}
        official_overlay = official_publication_windows_by_platform or {}
        pricing_overlay = pricing_evidence_by_platform or {}
        conflict = _timing_conflicts(policies, hours_override, business_override, official_overlay)
        if conflict:
            return {"error": "validation_error", "message": conflict}
        decisions = []
        for policy in policies:
            if policy["is_workflow"]:
                continue
            row = dict(policy)
            platform_id = row["target_id"]
            if platform_id in pricing_overlay:
                row.update(
                    _pricing_from_evidence(
                        pricing_overlay[platform_id],
                        row.get("registry_paid_submission_possible"),
                    )
                )
            if platform_id in official_overlay:
                row.update(_accepted_window_fields(official_overlay[platform_id]))
            decisions.append(
                self._decide(
                    row,
                    start=start,
                    planned=planned,
                    buffer_hours=publication_deadline_buffer_hours,
                    fallback_hours=conservative_fallback_hours,
                    allow_paid=allow_paid,
                    virtual_event=virtual_event,
                    event_id=event_id,
                    documented_hours=hours_override.get(platform_id),
                    documented_business_days=business_override.get(platform_id),
                )
            )
        groups: dict[str, list[str]] = {key: [] for key in (
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
            "safety_buffer_hours": publication_deadline_buffer_hours,
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
            "live_research_performed": False,
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
                    "timing_source": row["timing_source"],
                    "timing_kind": row["timing_kind"],
                    "latest_safe_submission_datetime": row["latest_safe_submission_datetime"],
                    "dry_run": True,
                    "would_publish": False,
                }
            )
        return {
            "preview": previews,
            "dry_run": True,
            "would_publish": False,
            "analysis": analysis,
        }

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
        if existing == "PUBLISHED":
            return _decision_row(
                policy, ALREADY_PUBLISHED,
                "A stored job for this event and target is already PUBLISHED.",
                start, planned, None, None, "unknown", "unknown",
            )
        if existing:
            return _decision_row(
                policy, ALREADY_SUBMITTED,
                "A stored job already exists for this event and target.",
                start, planned, None, None, "unknown", "unknown",
            )
        if start <= planned:
            return _decision_row(
                policy, EVENT_PAST,
                "The event start is not after the planning time, so ordinary pre-event promotion is not recommended.",
                start, planned, None, None, "unknown", "unknown",
            )
        if policy["automation_status"] == "BLOCKED":
            return _decision_row(
                policy, NOT_SUPPORTED,
                "The registry marks this target BLOCKED.",
                start, planned, None, None, "unknown", "unknown",
            )
        if policy["free_submission_available"] is False and not allow_paid:
            return _decision_row(
                policy, NOT_FREE,
                "Official evidence says a free submission is not available, and paid options are disabled for this plan.",
                start, planned, None, None, "unknown", "unknown",
            )
        if virtual_event is True and policy["supports_virtual_events"] is False:
            return _decision_row(
                policy, NOT_SUPPORTED,
                "The registry records that this target does not support virtual events.",
                start, planned, None, None, "unknown", "unknown",
            )
        if virtual_event is False and policy["supports_physical_events"] is False:
            return _decision_row(
                policy, NOT_SUPPORTED,
                "The registry records that this target does not support physical events.",
                start, planned, None, None, "unknown", "unknown",
            )

        official_hours = policy.get("official_publication_hours")
        official_days = policy.get("official_publication_business_days")
        official_kind = policy.get("official_publication_kind")
        business_days: int | None = None
        hours: int | None = None
        timing_source = "unknown"
        timing_kind = "unknown"
        if official_hours is not None or official_days is not None:
            timing_source = "official_evidence"
            timing_kind = official_kind or "guarantee"
            if official_days is not None:
                business_days = official_days
                hours = official_days * 24
            else:
                hours = official_hours
        elif documented_business_days is not None:
            timing_source = "caller_supplied"
            timing_kind = "caller_supplied"
            business_days = documented_business_days
            hours = documented_business_days * 24
        elif documented_hours is not None:
            timing_source = "caller_supplied"
            timing_kind = "caller_supplied"
            hours = documented_hours
        elif fallback_hours is not None:
            timing_source = "heuristic"
            timing_kind = "heuristic"
            hours = fallback_hours
        else:
            return _decision_row(
                policy, PUBLICATION_TIME_UNKNOWN,
                "No documented publication window is stored. Unknown timelines are excluded from the default plan.",
                start, planned, None, None, "unknown", "unknown",
            )

        assert hours is not None
        if business_days is not None:
            latest = subtract_business_days(start, business_days) - timedelta(hours=buffer_hours)
            window_label = f"{business_days} business days"
        else:
            latest = start - timedelta(hours=hours) - timedelta(hours=buffer_hours)
            window_label = f"{hours} hours"
        buffer_label = f"{buffer_hours} hour safety buffer"
        if planned > latest:
            status = DEADLINE_PASSED
            reason = (
                f"The latest safe submission time, using {window_label} plus the {buffer_label}, "
                "is before the planning time."
            )
        elif timing_source == "official_evidence" and timing_kind == "guarantee":
            status = ELIGIBLE
            reason = (
                f"A cited official source states a guaranteed window of {window_label}. "
                "This process did not re-fetch that page. "
                f"The window plus the {buffer_label} fits before the event start."
            )
        elif timing_source == "official_evidence":
            status = ELIGIBLE_WITH_RISK
            reason = (
                f"A cited official source gives an estimate of {window_label}, not a guarantee. "
                f"The estimate plus the {buffer_label} fits before the event start."
            )
        elif timing_source == "caller_supplied":
            status = ELIGIBLE_WITH_RISK
            reason = (
                f"Caller supplied a window of {window_label}. "
                "This is not an official guarantee and was not verified by a live fetch. "
                f"The supplied window plus the {buffer_label} fits before the event start."
            )
        else:
            status = ELIGIBLE_WITH_RISK
            reason = (
                f"Heuristic fallback of {hours} hours was supplied by the caller. "
                "This is an estimate, not an official publication commitment."
            )
        if policy["free_submission_available"] is not True and status in {ELIGIBLE, ELIGIBLE_WITH_RISK}:
            if policy["free_submission_available"] is False and allow_paid:
                reason += " Paid submission is explicitly allowed for this analysis."
            else:
                status = MANUAL_REVIEW_REQUIRED
                reason = (
                    "A publication window was calculated, but free submission is not verified "
                    "by an official source. Unknown or unverified pricing is excluded from the default plan. "
                    + str(policy.get("pricing_reason") or "")
                ).strip()
        return _decision_row(
            policy, status, reason, start, planned, latest, hours, timing_source, timing_kind,
        )


def _decision_row(
    policy: dict[str, Any],
    status: str,
    reason: str,
    start: datetime,
    planned: datetime,
    latest: datetime | None,
    hours: int | None,
    timing_source: str,
    timing_kind: str,
) -> dict[str, Any]:
    if timing_source == "official_evidence" and timing_kind == "estimate":
        confidence = "cited_estimate"
    elif timing_source == "official_evidence":
        confidence = "cited_official_source"
    elif timing_source == "caller_supplied":
        confidence = "caller_supplied"
    elif timing_source == "heuristic":
        confidence = "heuristic"
    else:
        confidence = policy.get("publication_time_confidence") or "unknown"
    return {
        "target_id": policy["target_id"],
        "website_name": policy["website_name"],
        "eligibility_status": status,
        "eligibility_reason": reason,
        "free_submission_available": policy["free_submission_available"],
        "pricing_status": policy.get("pricing_status"),
        "pricing_reason": policy.get("pricing_reason"),
        "pricing_evidence_url": policy.get("pricing_evidence_url"),
        "pricing_verified_at": policy.get("pricing_verified_at"),
        "publication_time_confidence": confidence,
        "timing_source": timing_source,
        "timing_kind": timing_kind,
        "conservative_publication_hours": hours,
        "latest_safe_submission_datetime": latest.isoformat() if latest else None,
        "hours_until_event": round((start - planned).total_seconds() / 3600, 2),
        "search_indexing_separate": True,
        "timing_live_verified": False,
        "official_source_url": policy.get("official_publication_source_url"),
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
    pricing = _pricing_from_evidence(platform.research.pricing, paid)
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
    window = _registry_window_fields(platform.research.publication_window)
    return {
        "target_id": platform.platform_id,
        "website_name": platform.platform_name,
        "base_url": homepage,
        "submission_url": submission,
        "official_guidelines_url": guidelines,
        "pricing_url": pricing["pricing_evidence_url"],
        "free_submission_available": pricing["free_submission_available"],
        "free_listing_conditions": pricing["free_listing_conditions"],
        "paid_options_available": pricing["paid_options_available"],
        "pricing_status": pricing["pricing_status"],
        "pricing_reason": pricing["pricing_reason"],
        "pricing_evidence_url": pricing["pricing_evidence_url"],
        "pricing_verified_at": pricing["pricing_verified_at"],
        "pricing_confidence": pricing["pricing_confidence"],
        "pricing_live_verified": False,
        "registry_paid_submission_possible": paid,
        "account_required": "unknown",
        "email_verification_required": "unknown",
        "organization_verification_required": "unknown",
        "manual_review_required": platform.approval_required,
        "approval_time_min_hours": None,
        "approval_time_max_hours": None,
        "approval_time_unit": None,
        "approval_time_business_days": None,
        "approval_time_basis": "unknown",
        "moderation_approval_time": "unknown",
        "publication_time_basis": window["official_publication_kind"] or "not_guaranteed",
        "publication_time_confidence": "unknown" if window["official_publication_kind"] is None else "registry_citation",
        "publication_time_source_url": window["official_publication_source_url"] or guidelines,
        "publication_time_verified_at": window["official_publication_verified_at"] or verified_at,
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
        "research_status": "registry_only",
        "live_research_performed": False,
        **window,
    }


def _registry_paid_note(paid: bool | None) -> str:
    if paid is False:
        return (
            "Registry paid_submission_possible is false. That flag is not evidence that a public "
            "listing is free, and it does not prove paid options are absent."
        )
    if paid is True:
        return (
            "Registry paid_submission_possible is true, but no complete official pricing citation "
            "is stored. Paid options stay unverified and free availability stays unknown."
        )
    return "No official pricing evidence is stored. Unknown pricing is not treated as free."


def _pricing_from_evidence(packet: Any, registry_paid: bool | None) -> dict[str, Any]:
    registry_note = _registry_paid_note(registry_paid)
    unknown = {
        "free_submission_available": None,
        "paid_options_available": None,
        "pricing_status": "unknown",
        "pricing_reason": registry_note,
        "pricing_evidence_url": None,
        "pricing_verified_at": None,
        "free_listing_conditions": None,
        "pricing_confidence": "none",
        "pricing_live_verified": False,
        "registry_paid_submission_possible": registry_paid,
    }
    if packet is None:
        return unknown
    problem = _pricing_problem(packet)
    if problem:
        unknown["pricing_reason"] = f"Pricing evidence was not accepted: {problem} {registry_note}"
        return unknown
    free = packet.get("free_submission_available")
    paid = packet.get("paid_options_available")
    classification = packet.get("classification")
    if classification == "verified_free" and free is None:
        free = True
    if classification == "paid_option" and paid is None:
        paid = True
    if free is True:
        status = "verified_free"
    elif paid is True:
        status = "paid_option"
    elif free is False:
        status = "verified_not_free"
    else:
        status = "unknown"
    verified_at = _parse_evidence_date(packet.get("verified_at"))
    return {
        "free_submission_available": free,
        "paid_options_available": paid,
        "pricing_status": status,
        "pricing_reason": str(packet.get("reason")).strip(),
        "pricing_evidence_url": _http_url(packet.get("official_source_url")),
        "pricing_verified_at": verified_at,
        "free_listing_conditions": (
            str(packet.get("free_conditions")).strip() if free is True and packet.get("free_conditions") else None
        ),
        "pricing_confidence": "cited_official_source",
        "pricing_live_verified": False,
        "registry_paid_submission_possible": registry_paid,
    }


def _pricing_problem(packet: Any) -> str | None:
    if not isinstance(packet, dict):
        return "pricing evidence must be an object with an official source URL, verification date, and reason"
    classification = packet.get("classification")
    if classification not in {None, "verified_free", "paid_option"}:
        return "classification must be verified_free or paid_option"
    free = packet.get("free_submission_available")
    paid = packet.get("paid_options_available")
    if classification == "verified_free" and free is None:
        free = True
    if classification == "paid_option" and paid is None:
        paid = True
    if free is not None and not isinstance(free, bool):
        return "free_submission_available must be a boolean when supplied"
    if paid is not None and not isinstance(paid, bool):
        return "paid_options_available must be a boolean when supplied"
    if classification == "verified_free" and free is False:
        return "verified_free contradicts free_submission_available false"
    if classification == "paid_option" and paid is False:
        return "paid_option contradicts paid_options_available false"
    if free is None and paid is None:
        return "evidence did not state whether free submission or a paid option is available"
    if _http_url(packet.get("official_source_url")) is None:
        return "official_source_url must be an http or https URL"
    if _parse_evidence_date(packet.get("verified_at")) is None:
        return "verified_at must be an ISO-8601 date or datetime"
    reason = packet.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < 12:
        return "reason must explain the official pricing evidence"
    return None


def _registry_window_fields(raw: Any) -> dict[str, Any]:
    if raw is None:
        return dict(_EMPTY_WINDOW)
    problem = _official_window_problem(raw)
    if problem:
        fields = dict(_EMPTY_WINDOW)
        fields["publication_evidence_note"] = f"Stored publication evidence was not used: {problem}"
        return fields
    return _accepted_window_fields(raw)


def _accepted_window_fields(item: dict[str, Any]) -> dict[str, Any]:
    summary = str(item.get("summary") or item.get("reason") or "").strip()
    return {
        "official_publication_hours": item.get("hours"),
        "official_publication_business_days": item.get("business_days"),
        "official_publication_kind": item.get("kind"),
        "official_publication_source_url": _http_url(item.get("official_source_url")),
        "official_publication_verified_at": _parse_evidence_date(item.get("verified_at")),
        "official_publication_summary": summary,
        "publication_evidence_note": None,
    }


def _official_window_problem(item: Any) -> str | None:
    if not isinstance(item, dict):
        return "publication window evidence must be an object"
    hours = item.get("hours")
    days = item.get("business_days")
    has_hours = hours is not None
    has_days = days is not None
    if has_hours == has_days:
        return "provide exactly one of hours or business_days"
    if has_hours and not _in_int_range(hours, MAX_PUBLICATION_HOURS):
        return f"hours must be an integer from 0 to {MAX_PUBLICATION_HOURS}"
    if has_days and not _in_int_range(days, MAX_BUSINESS_DAYS):
        return f"business_days must be an integer from 0 to {MAX_BUSINESS_DAYS}"
    if item.get("kind") not in {"guarantee", "estimate"}:
        return "kind must be guarantee or estimate"
    if _http_url(item.get("official_source_url")) is None:
        return "official_source_url must be an http or https URL"
    if _parse_evidence_date(item.get("verified_at")) is None:
        return "verified_at must be an ISO-8601 date or datetime"
    summary = item.get("summary") or item.get("reason")
    if not isinstance(summary, str) or len(summary.strip()) < 12:
        return "summary must explain the cited publication window"
    return None


def _validate_timing_inputs(
    *,
    publication_deadline_buffer_hours: Any,
    conservative_fallback_hours: Any,
    documented_hours_by_platform: Any,
    documented_business_days_by_platform: Any,
    official_publication_windows_by_platform: Any,
    pricing_evidence_by_platform: Any,
) -> str | None:
    if not _in_int_range(publication_deadline_buffer_hours, MAX_BUFFER_HOURS):
        return f"publication_deadline_buffer_hours must be an integer from 0 to {MAX_BUFFER_HOURS}"
    if conservative_fallback_hours is not None and not _in_int_range(conservative_fallback_hours, MAX_PUBLICATION_HOURS):
        return f"conservative_fallback_hours must be an integer from 0 to {MAX_PUBLICATION_HOURS}"
    hours_problem = _validate_int_map("documented_hours_by_platform", documented_hours_by_platform, MAX_PUBLICATION_HOURS)
    if hours_problem:
        return hours_problem
    days_problem = _validate_int_map(
        "documented_business_days_by_platform",
        documented_business_days_by_platform,
        MAX_BUSINESS_DAYS,
    )
    if days_problem:
        return days_problem
    if official_publication_windows_by_platform is not None and not isinstance(official_publication_windows_by_platform, dict):
        return "official_publication_windows_by_platform must be an object"
    if isinstance(official_publication_windows_by_platform, dict):
        for key, item in official_publication_windows_by_platform.items():
            if not isinstance(key, str) or not key.strip():
                return "official publication window keys must be platform ids"
            problem = _official_window_problem(item)
            if problem:
                return f"{key}: {problem}"
    if pricing_evidence_by_platform is not None and not isinstance(pricing_evidence_by_platform, dict):
        return "pricing_evidence_by_platform must be an object"
    hours = documented_hours_by_platform or {}
    days = documented_business_days_by_platform or {}
    both = set(hours) & set(days)
    if both:
        names = ", ".join(sorted(both))
        return f"provide hours or business days for {names}, not both"
    return None


def _timing_conflicts(
    policies: list[dict[str, Any]],
    hours: dict[str, int],
    days: dict[str, int],
    official_overlay: dict[str, Any],
) -> str | None:
    official_ids = set(official_overlay)
    for policy in policies:
        if policy.get("official_publication_hours") is not None or policy.get("official_publication_business_days") is not None:
            official_ids.add(policy["target_id"])
    overlap = official_ids & (set(hours) | set(days))
    if overlap:
        names = ", ".join(sorted(overlap))
        return (
            f"official publication evidence and caller-supplied timing both set a window for {names}. "
            "Pass only one source for each target."
        )
    return None


def _validate_int_map(name: str, value: Any, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return f"{name} must be an object of platform id to integer"
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            return f"{name} keys must be platform ids"
        if not _in_int_range(item, maximum):
            return f"{name}[{key}] must be an integer from 0 to {maximum}"
    return None


def _in_int_range(value: Any, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


def _source_urls(target: dict[str, Any]) -> list[str]:
    urls = list(target.get("source_urls") or [])
    for key in ("official_guidelines_url", "base_url", "submission_url", "pricing_evidence_url"):
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
    if not str(fields["content_language"] or "").strip():
        problems.append("content_language is required")
    if fields["event_status"] not in SUPPORTED_EVENT_STATUSES:
        problems.append("event_status must be a schema.org Event status URL")
    if not _in_int_range(fields["title_limit"], MAX_TITLE_LIMIT) or fields["title_limit"] < 1:
        problems.append(f"title_limit must be an integer from 1 to {MAX_TITLE_LIMIT}")
    if not _in_int_range(fields["description_limit"], MAX_DESCRIPTION_LIMIT) or fields["description_limit"] < 1:
        problems.append(f"description_limit must be an integer from 1 to {MAX_DESCRIPTION_LIMIT}")
    if _parse_zoned(str(fields["event_start_datetime"] or ""), str(fields["event_timezone"] or "")) is None:
        problems.append("event_start_datetime must be ISO-8601 with a time component in a valid IANA timezone")
    elif fields.get("event_end_datetime"):
        start = _parse_zoned(str(fields["event_start_datetime"]), str(fields["event_timezone"]))
        end = _parse_zoned(str(fields["event_end_datetime"]), str(fields["event_timezone"]))
        if end is None:
            problems.append("event_end_datetime must be ISO-8601 with a time component in the event timezone")
        elif start is not None and end < start:
            problems.append("event_end_datetime must not be before event_start_datetime")
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
    if fields["event_name"] != fields["seo_title"] or fields["event_name"] not in fields["body"]:
        warnings.append("seo_title does not contain the full official event name")
    if not fields["title_within_limit"]:
        warnings.append(
            f"seo_title is {len(fields['seo_title'])} characters and exceeds the limit of {fields['title_limit']}. "
            "The official event name was not truncated, and the title does not meet the limit."
        )
    if not fields["meta_within_limit"]:
        warnings.append(
            f"meta_description is {len(fields['meta'])} characters and exceeds the limit of {fields['description_limit']}. "
            "It was not truncated."
        )
    if fields["keyword"] and fields["keyword"].lower() not in fields["body"].lower():
        warnings.append("primary keyword is missing from the body")
    if fields["landing_page_url"] not in fields["body"] or fields["registration_url"] not in fields["body"]:
        warnings.append("a required URL is missing from the body")
    return warnings


def _parse_zoned(value: str, timezone_name: str) -> datetime | None:
    text = (value or "").strip()
    if not text or not _has_time_component(text):
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


def _has_time_component(text: str) -> bool:
    if "T" in text or "t" in text:
        return True
    return " " in text and ":" in text


def _parse_evidence_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.date().isoformat()


def _http_url(value: Any) -> str | None:
    from event_seo_mcp.integrations.google_sheets.service import valid_http_url

    if not isinstance(value, str):
        return None
    return valid_http_url(value)


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
