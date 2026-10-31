"""Publication policy, SEO drafts, and event-date eligibility."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from event_seo_mcp.publishing.intelligence import (
    ALREADY_SUBMITTED,
    DEADLINE_PASSED,
    ELIGIBLE,
    ELIGIBLE_WITH_RISK,
    EVENT_PAST,
    MANUAL_REVIEW_REQUIRED,
    _policy,
    subtract_business_days,
)
from event_seo_mcp.schemas.platform import PlatformRecord, PlatformsFile
from event_seo_mcp.tools.handlers import ToolService

FREE_EVIDENCE = {
    "classification": "verified_free",
    "official_source_url": "https://www.example.com/official-pricing",
    "verified_at": "2026-10-29",
    "reason": "Official pricing page states a free public listing is available.",
    "free_conditions": "The free listing remains available without a paid upgrade.",
}

PAID_EVIDENCE = {
    "classification": "paid_option",
    "free_submission_available": False,
    "paid_options_available": True,
    "official_source_url": "https://www.example.com/official-paid-pricing",
    "verified_at": "2026-10-29",
    "reason": "Official pricing page lists only a paid submission product.",
}


def _human_audit(hours: int = 48, kind: str = "guarantee", business_days: int | None = None, **overrides) -> dict:
    record = {
        "official_source_url": "https://www.example.com/official-guidelines",
        "verified_at": "2026-10-29T16:30:00Z",
        "verifier": "ops-review-ref-2026-10-29",
        "claim_checked": "The guidelines page states this publication window for new listings.",
        "kind": kind,
    }
    if business_days is None:
        record["hours"] = hours
    else:
        record["business_days"] = business_days
    record.update(overrides)
    return record


def _official_window(
    hours: int = 48,
    kind: str = "guarantee",
    business_days: int | None = None,
    human: bool = False,
) -> dict:
    window = {
        "kind": kind,
        "official_source_url": "https://www.example.com/official-guidelines",
        "verified_at": "2026-10-29",
        "summary": "Official guidelines state this publication window for new listings.",
    }
    if business_days is None:
        window["hours"] = hours
    else:
        window["business_days"] = business_days
    if human:
        window["human_verification"] = _human_audit(hours=hours, kind=kind, business_days=business_days)
    return window


def _platform(**overrides) -> PlatformRecord:
    payload = {
        "platform_id": "example_target",
        "platform_name": "Example Target",
        "category": "event_directory",
        "submission_method": "manual",
        "adapter_name": "manual",
        "authentication_method": "none",
        "paid_submission_possible": False,
    }
    payload.update(overrides)
    return PlatformRecord.model_validate(payload)


def _engine(service: ToolService):
    return service.publishing


def test_every_registry_target_has_an_unknown_timeline(service: ToolService) -> None:
    report = _engine(service).publication_policy()
    assert report["count"] >= 30
    assert report["seo_agent_connected"] is False
    assert report["timelines_invented"] is False
    ids = [row["target_id"] for row in report["targets"]]
    assert len(ids) == len(set(ids))
    for row in report["targets"]:
        assert row["approval_time_max_hours"] is None
        assert row["publication_time_confidence"] == "unknown"
        assert row["google_indexing_estimate"] == "unknown"
        assert row["publication_time_basis"] == "not_guaranteed"
        assert row["citation_validity"] == "absent"
        assert row["source_verification_status"] == "unverified"
        assert row["machine_verification_performed"] is False
        assert row["human_verification"] is None


def test_eventbrite_policy_uses_registry_sources_only(service: ToolService) -> None:
    row = _engine(service).publication_policy("eventbrite")["targets"][0]
    assert row["free_submission_available"] is None
    assert row["paid_options_available"] is None
    assert row["pricing_status"] == "unknown"
    assert row["registry_paid_submission_possible"] is False
    assert row["pricing_evidence_url"] is None
    assert row["pricing_verified_at"] is None
    assert "not evidence" in row["pricing_reason"]
    assert row["live_research_performed"] is False
    assert "eventbrite.com/platform/docs" in str(row["official_guidelines_url"])
    clocks = _engine(service).research_publication_time("eventbrite")
    assert clocks["publication_time"] == "unknown"
    assert clocks["publication_time_kind"] == "unknown"
    assert clocks["publication_time_confidence"] == "unknown"
    assert clocks["live_research_performed"] is False
    assert clocks["research_status"] == "not_live_researched"
    assert clocks["research_timestamp"] is None
    assert clocks["ranking_time"] == "not_estimated"
    assert clocks["google_indexing_estimate"] == "unknown"
    assert clocks["indexing_separate_from_publication"] is True
    assert clocks["source_urls"]


def test_unknown_timeline_is_not_eligible(service: ToolService) -> None:
    plan = _engine(service).analyze_deadlines(
        event_name="Future Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2026-11-01T00:00:00Z",
    )
    assert plan["recommended_submission_order"] == []
    assert "eventbrite" in plan["unknown_timelines"]
    assert all(row["eligibility_status"] != ELIGIBLE for row in plan["decisions"])


def test_documented_window_can_be_eligible_or_too_late(service: ToolService) -> None:
    engine = _engine(service)
    early = engine.analyze_deadlines(
        event_name="Future Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        publication_deadline_buffer_hours=24,
        documented_hours_by_platform={"eventbrite": 48},
    )
    eventbrite = next(row for row in early["decisions"] if row["target_id"] == "eventbrite")
    assert eventbrite["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert eventbrite["timing_source"] == "caller_supplied"
    assert eventbrite["timing_kind"] == "caller_supplied"
    assert eventbrite["free_submission_available"] is None
    assert eventbrite["latest_safe_submission_datetime"]
    assert "eventbrite" not in early["recommended_submission_order"]

    late = engine.analyze_deadlines(
        event_name="Future Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-11-30T00:00:00Z",
        publication_deadline_buffer_hours=24,
        documented_hours_by_platform={"eventbrite": 48},
    )
    late_row = next(row for row in late["decisions"] if row["target_id"] == "eventbrite")
    assert late_row["eligibility_status"] == DEADLINE_PASSED


def test_event_already_started_and_heuristic_risk(service: ToolService) -> None:
    started = _engine(service).analyze_deadlines(
        event_name="Started",
        event_start_datetime="2026-01-01T00:00:00Z",
        event_timezone="UTC",
        submission_datetime="2026-06-01T00:00:00Z",
    )
    assert all(row["eligibility_status"] == EVENT_PAST for row in started["decisions"])

    risk = _engine(service).analyze_deadlines(
        event_name="Heuristic",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        conservative_fallback_hours=72,
    )
    sample = next(row for row in risk["decisions"] if row["target_id"] == "eventbrite")
    assert sample["free_submission_available"] is None
    assert sample["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert sample["publication_time_confidence"] == "heuristic"
    assert sample["timing_source"] == "heuristic"
    assert risk["recommended_submission_order"] == []


def test_business_days_are_not_calendar_days() -> None:
    friday = datetime(2027, 12, 3, 12, 0, tzinfo=timezone.utc)  # Friday
    assert subtract_business_days(friday, 1) == friday - timedelta(days=1)
    assert subtract_business_days(friday, 1).weekday() == 4 or subtract_business_days(friday, 1).weekday() == 3
    monday = datetime(2027, 12, 6, 12, 0, tzinfo=timezone.utc)
    previous = subtract_business_days(monday, 1)
    assert previous.weekday() == 4


def test_business_day_window_fits(service: ToolService) -> None:
    plan = _engine(service).analyze_deadlines(
        event_name="Weekday Summit",
        event_start_datetime="2027-12-10T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-12-01T12:00:00Z",
        publication_deadline_buffer_hours=0,
        documented_business_days_by_platform={"eventbrite": 2},
    )
    row = next(item for item in plan["decisions"] if item["target_id"] == "eventbrite")
    assert row["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert row["timing_source"] == "caller_supplied"
    assert "eventbrite" not in plan["recommended_submission_order"]


def test_timezone_offset_is_preserved_through_utc(service: ToolService) -> None:
    content = _engine(service).generate_seo_content(
        event_name="Eastern Summit",
        event_description="A fictional planning fixture.",
        event_start_datetime="2027-07-15T09:00:00",
        event_timezone="America/New_York",
        landing_page_url="https://example.com/eastern",
        registration_url="https://example.com/eastern/register",
        organizer_name="Example Org",
        target_website="eventbrite",
        location="New York",
        primary_keyword="Eastern Summit",
    )
    assert content["structured_data"]["startDate"].endswith("+00:00")
    assert "13:00:00" in content["structured_data"]["startDate"]
    assert content["official_event_name_preserved"] is True
    assert content["content_source"] == "template"
    assert content["seo_agent_connected"] is False


def test_seo_agent_is_not_invented(service: ToolService) -> None:
    result = _engine(service).generate_seo_content(
        event_name="Named Event",
        event_description="Description.",
        event_start_datetime="2027-07-15T09:00:00Z",
        event_timezone="UTC",
        landing_page_url="https://example.com/e",
        registration_url="https://example.com/e/r",
        organizer_name="Org",
        target_website="eventbrite",
        location="Hall",
        content_source="seo-agent",
    )
    assert result["error"] == "seo_agent_not_configured"


def test_seo_rejects_missing_facts_and_bad_urls(service: ToolService) -> None:
    result = _engine(service).generate_seo_content(
        event_name="",
        event_description="",
        event_start_datetime="not-a-date",
        event_timezone="Not/AZone",
        landing_page_url="javascript:alert(1)",
        registration_url="notaurl",
        organizer_name="",
        target_website="eventbrite",
    )
    assert result["error"] == "validation_error"
    assert "event_name" in result["message"]
    assert result["tracked"] is False


def test_duplicate_bodies_differ_by_target(service: ToolService) -> None:
    kwargs = dict(
        event_name="Same Facts",
        event_description="Shared description.",
        event_start_datetime="2027-07-15T09:00:00Z",
        event_timezone="UTC",
        landing_page_url="https://example.com/same",
        registration_url="https://example.com/same/register",
        organizer_name="Org",
        location="Hall",
        primary_keyword="Same Facts",
    )
    first = _engine(service).generate_seo_content(target_website="eventbrite", **kwargs)
    second = _engine(service).generate_seo_content(target_website="10times", **kwargs)
    assert first["content_hash"] != second["content_hash"]
    assert first["event_name"] == second["event_name"] == "Same Facts"


def test_refresh_persists_every_target(service: ToolService) -> None:
    first = _engine(service).refresh_research()
    assert first["count"] >= 30
    assert first["live_research_performed"] is False
    assert first["research_status"] == "registry_only"
    assert first["counts"]["live_researched"] == 0
    assert first["counts"]["machine_verified"] == 0
    assert first["machine_verification_performed"] is False
    assert first["counts"]["registry_only"] == first["count"]
    assert "researched" not in first["counts"]
    row = service.repo.db.fetchone(
        "SELECT platform_id, refreshed_at FROM target_research_snapshots WHERE platform_id = ?",
        ("eventbrite",),
    )
    assert row is not None
    second = _engine(service).refresh_research()
    assert second["count"] == first["count"]
    again = service.repo.db.fetchone(
        "SELECT COUNT(*) AS n FROM target_research_snapshots",
    )
    assert again["n"] == first["count"]


def test_existing_job_blocks_another_recommendation(service: ToolService, sample_event) -> None:
    service.create_event(sample_event.model_dump(mode="json"))
    service.submit_event(sample_event.event_id, "eventbrite", dry_run=True, authorize_publication=False)
    plan = _engine(service).analyze_deadlines(
        event_name=sample_event.event_title,
        event_start_datetime=sample_event.start_datetime.isoformat(),
        event_timezone="UTC",
        submission_datetime="2026-01-01T00:00:00Z",
        event_id=sample_event.event_id,
        documented_hours_by_platform={"eventbrite": 1},
    )
    row = next(item for item in plan["decisions"] if item["target_id"] == "eventbrite")
    assert row["eligibility_status"] == ALREADY_SUBMITTED


def test_dry_run_tool_cannot_authorize_publication(service: ToolService, sample_event) -> None:
    service.create_event(sample_event.model_dump(mode="json"))
    result = service.submit_event_dry_run(sample_event.event_id, "eventbrite")
    assert result["job"]["dry_run"] is True
    assert result["authorize_publication"] is False
    assert result["live_publication_requested"] is False
    assert result["job"]["state"] != "PUBLISHED"


def test_paid_false_is_not_verified_free() -> None:
    row = _policy(_platform(paid_submission_possible=False))
    assert row["free_submission_available"] is None
    assert row["paid_options_available"] is None
    assert row["pricing_status"] == "unknown"
    assert row["pricing_evidence_url"] is None
    assert "not evidence" in row["pricing_reason"]


def test_verified_free_and_paid_citations_are_classified() -> None:
    free = _policy(_platform(research={"pricing": FREE_EVIDENCE}))
    assert free["free_submission_available"] is True
    assert free["pricing_status"] == "verified_free"
    assert free["pricing_evidence_url"] == FREE_EVIDENCE["official_source_url"]
    assert free["pricing_verified_at"] == "2026-10-29"
    assert free["free_listing_conditions"] == FREE_EVIDENCE["free_conditions"]
    assert free["pricing_reason"] == FREE_EVIDENCE["reason"]
    assert free["pricing_live_verified"] is False

    paid = _policy(_platform(paid_submission_possible=True, research={"pricing": PAID_EVIDENCE}))
    assert paid["free_submission_available"] is False
    assert paid["paid_options_available"] is True
    assert paid["pricing_status"] == "paid_option"
    assert paid["pricing_evidence_url"] == PAID_EVIDENCE["official_source_url"]
    assert paid["pricing_verified_at"] == "2026-10-29"


def test_missing_or_invalid_pricing_evidence_stays_unknown() -> None:
    missing = _policy(_platform(paid_submission_possible=None))
    assert missing["free_submission_available"] is None
    assert missing["pricing_status"] == "unknown"

    invalid = _policy(
        _platform(
            research={
                "pricing": {
                    "free_submission_available": True,
                    "official_source_url": "javascript:alert(1)",
                    "verified_at": "yesterday",
                    "reason": "too thin",
                },
                "publication_window": {"hours": 24, "kind": "guarantee"},
            }
        )
    )
    assert invalid["free_submission_available"] is None
    assert invalid["pricing_status"] == "unknown"
    assert "not accepted" in invalid["pricing_reason"]
    assert invalid["official_publication_hours"] is None
    assert invalid["publication_time_confidence"] == "unknown"
    assert "not used" in invalid["publication_evidence_note"]


def test_registry_citation_is_not_called_live_research(service: ToolService, monkeypatch: pytest.MonkeyPatch) -> None:
    platform = _platform(
        platform_id="cited_target",
        documentation_url="https://www.example.com/official-guidelines",
        research={
            "pricing": FREE_EVIDENCE,
            "publication_window": _official_window(hours=72, kind="estimate"),
        },
    )
    registry = PlatformsFile(version="test", platforms=[platform])
    monkeypatch.setattr(
        "event_seo_mcp.publishing.intelligence.load_platforms_file",
        lambda _path: registry,
    )
    clocks = _engine(service).research_publication_time("cited_target")
    assert clocks["live_research_performed"] is False
    assert clocks["research_status"] == "not_live_researched"
    assert clocks["research_method"] == "registry_read"
    assert clocks["research_timestamp"] is None
    assert clocks["publication_time"] == "72 hours"
    assert clocks["publication_time_kind"] == "estimate"
    assert clocks["confidence"] == "unverified_citation"
    assert clocks["citation_validity"] == "complete"
    assert clocks["source_verification_status"] == "unverified"
    assert clocks["human_verification"] is None
    assert clocks["machine_verification_performed"] is False
    assert clocks["google_indexing_estimate"] == "unknown"
    assert clocks["moderation_approval_time"] == "unknown"
    assert clocks["internal_search_visibility"] == "unknown"
    assert clocks["account_required"] == "unknown"
    assert clocks["free_submission_available"] is True
    assert "No live research" in clocks["evidence_summary"]


def test_official_windows_and_caller_timing_stay_distinct(service: ToolService) -> None:
    base = dict(
        event_name="Future Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        publication_deadline_buffer_hours=24,
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    official = _engine(service).analyze_deadlines(
        **base,
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "guarantee")},
    )
    official_row = next(row for row in official["decisions"] if row["target_id"] == "eventbrite")
    assert official_row["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert official_row["timing_source"] == "citation"
    assert official_row["timing_kind"] == "guarantee"
    assert official_row["citation_validity"] == "complete"
    assert official_row["source_verification_status"] == "unverified"
    assert official_row["publication_time_confidence"] == "unverified_citation"
    assert official_row["machine_verification_performed"] is False
    assert official_row["timing_live_verified"] is False
    assert official_row["verification_warning"]
    assert official_row["latest_safe_submission_datetime"]
    assert "not checked" in official_row["eligibility_reason"]
    assert "eventbrite" not in official["recommended_submission_order"]

    estimate = _engine(service).analyze_deadlines(
        **base,
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "estimate")},
    )
    estimate_row = next(row for row in estimate["decisions"] if row["target_id"] == "eventbrite")
    assert estimate_row["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert estimate_row["timing_kind"] == "estimate"
    assert estimate_row["source_verification_status"] == "unverified"
    assert "eventbrite" not in estimate["recommended_submission_order"]

    caller = _engine(service).analyze_deadlines(
        **base,
        documented_hours_by_platform={"eventbrite": 48},
    )
    caller_row = next(row for row in caller["decisions"] if row["target_id"] == "eventbrite")
    assert caller_row["eligibility_status"] == ELIGIBLE_WITH_RISK
    assert caller_row["timing_source"] == "caller_supplied"
    assert caller_row["timing_kind"] == "caller_supplied"
    assert caller_row["source_verification_status"] == "unverified"
    assert caller_row["machine_verification_performed"] is False
    assert "not an official guarantee" in caller_row["eligibility_reason"]

    heuristic = _engine(service).analyze_deadlines(**base, conservative_fallback_hours=72)
    heuristic_row = next(row for row in heuristic["decisions"] if row["target_id"] == "eventbrite")
    assert heuristic_row["timing_source"] == "heuristic"
    assert heuristic_row["timing_kind"] == "heuristic"
    assert heuristic_row["eligibility_status"] == ELIGIBLE_WITH_RISK
    assert heuristic_row["source_verification_status"] == "unverified"
    assert heuristic_row["machine_verification_performed"] is False


@pytest.mark.parametrize(
    ("extra", "fragment"),
    [
        ({"documented_hours_by_platform": {"eventbrite": -1}}, "documented_hours_by_platform"),
        ({"documented_hours_by_platform": {"eventbrite": True}}, "documented_hours_by_platform"),
        ({"documented_hours_by_platform": {"eventbrite": "48"}}, "documented_hours_by_platform"),
        ({"documented_hours_by_platform": {"eventbrite": 100000}}, "documented_hours_by_platform"),
        ({"documented_hours_by_platform": ["48"]}, "documented_hours_by_platform"),
        ({"documented_business_days_by_platform": {"eventbrite": -2}}, "documented_business_days_by_platform"),
        ({"publication_deadline_buffer_hours": -5}, "publication_deadline_buffer_hours"),
        ({"publication_deadline_buffer_hours": 24.5}, "publication_deadline_buffer_hours"),
        ({"conservative_fallback_hours": -1}, "conservative_fallback_hours"),
        (
            {
                "documented_hours_by_platform": {"eventbrite": 48},
                "documented_business_days_by_platform": {"eventbrite": 2},
            },
            "not both",
        ),
        (
            {"official_publication_windows_by_platform": {"eventbrite": {"hours": 48, "kind": "guarantee"}}},
            "official_source_url",
        ),
        ({"pricing_evidence_by_platform": "free"}, "pricing_evidence_by_platform"),
        (
            {
                "documented_hours_by_platform": {"eventbrite": 48},
                "official_publication_windows_by_platform": {"eventbrite": _official_window()},
            },
            "only one source",
        ),
        ({"event_start_datetime": "2027-12-01"}, "event_start_datetime"),
        (
            {
                "official_publication_windows_by_platform": {
                    "eventbrite": {**_official_window(), "human_verified": True}
                }
            },
            "human_verified",
        ),
        (
            {
                "official_publication_windows_by_platform": {
                    "eventbrite": {**_official_window(), "source_verification_status": "machine_verified"}
                }
            },
            "source_verification_status",
        ),
        (
            {
                "official_publication_windows_by_platform": {
                    "eventbrite": {**_official_window(), "machine_verified": True}
                }
            },
            "machine_verified",
        ),
        (
            {
                "official_publication_windows_by_platform": {
                    "eventbrite": {**_official_window(), "human_verification": _human_audit(verified_at="2026-10-29")}
                }
            },
            "time component",
        ),
        (
            {
                "official_publication_windows_by_platform": {
                    "eventbrite": {**_official_window(), "human_verification": _human_audit(verifier=True)}
                }
            },
            "verifier",
        ),
        (
            {
                "official_publication_windows_by_platform": {
                    "eventbrite": {**_official_window(), "human_verification": _human_audit(hours=12)}
                }
            },
            "must match",
        ),
        (
            {
                "official_publication_windows_by_platform": {
                    "eventbrite": {
                        **_official_window(),
                        "human_verification": _human_audit(official_source_url="https://www.example.com/other-page"),
                    }
                }
            },
            "must match the citation URL",
        ),
    ],
)
@pytest.mark.parametrize("entry", ["analyze", "recommend", "preview"])
def test_invalid_timing_is_rejected(service: ToolService, extra: dict, fragment: str, entry: str) -> None:
    kwargs = dict(
        event_name="Future Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
    )
    kwargs.update(extra)
    if entry == "analyze":
        result = _engine(service).analyze_deadlines(**kwargs)
    elif entry == "recommend":
        result = service.recommend_submission_targets(**kwargs)
    else:
        result = service.preview_submission_plan(**kwargs)
    assert result["error"] == "validation_error"
    assert fragment in result["message"]
    assert "decisions" not in result or result.get("error")


def test_deadline_uses_timezone_buffer_and_past_events(service: ToolService) -> None:
    engine = _engine(service)
    zoned = engine.analyze_deadlines(
        event_name="Eastern Summit",
        event_start_datetime="2027-07-15T09:00:00",
        event_timezone="America/New_York",
        submission_datetime="2027-07-01T12:00:00Z",
        publication_deadline_buffer_hours=24,
        documented_hours_by_platform={"eventbrite": 48},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    row = next(item for item in zoned["decisions"] if item["target_id"] == "eventbrite")
    assert zoned["event_start"] == "2027-07-15T13:00:00+00:00"
    assert row["latest_safe_submission_datetime"] == "2027-07-12T13:00:00+00:00"
    assert row["eligibility_status"] == ELIGIBLE_WITH_RISK

    tight_buffer = engine.analyze_deadlines(
        event_name="Buffer Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-11-29T00:00:00Z",
        publication_deadline_buffer_hours=24,
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "guarantee")},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    buffered = next(item for item in tight_buffer["decisions"] if item["target_id"] == "eventbrite")
    assert buffered["latest_safe_submission_datetime"] == "2027-11-28T15:00:00+00:00"
    assert buffered["eligibility_status"] == DEADLINE_PASSED
    assert buffered["source_verification_status"] == "unverified"
    assert "not a verified guarantee" in buffered["eligibility_reason"]

    open_buffer = engine.analyze_deadlines(
        event_name="Buffer Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-11-29T00:00:00Z",
        publication_deadline_buffer_hours=0,
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "guarantee")},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    unbuffered = next(item for item in open_buffer["decisions"] if item["target_id"] == "eventbrite")
    assert unbuffered["latest_safe_submission_datetime"] == "2027-11-29T15:00:00+00:00"
    assert unbuffered["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert unbuffered["source_verification_status"] == "unverified"
    assert unbuffered["citation_validity"] == "complete"

    started = engine.analyze_deadlines(
        event_name="Started",
        event_start_datetime="2027-07-15T09:00:00",
        event_timezone="America/New_York",
        submission_datetime="2027-07-15T13:00:00Z",
        documented_hours_by_platform={"eventbrite": 1},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    assert all(item["eligibility_status"] == EVENT_PAST for item in started["decisions"])
    assert started["recommended_submission_order"] == []


def test_official_business_day_window_matches_weekday_math(service: ToolService) -> None:
    plan = _engine(service).analyze_deadlines(
        event_name="Weekday Summit",
        event_start_datetime="2027-12-10T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-12-01T12:00:00Z",
        publication_deadline_buffer_hours=0,
        official_publication_windows_by_platform={"eventbrite": _official_window(business_days=2, kind="guarantee")},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    row = next(item for item in plan["decisions"] if item["target_id"] == "eventbrite")
    start = datetime(2027, 12, 10, 15, 0, tzinfo=timezone.utc)
    assert row["latest_safe_submission_datetime"] == subtract_business_days(start, 2).isoformat()
    assert row["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert row["timing_source"] == "citation"
    assert row["timing_kind"] == "guarantee"
    assert row["source_verification_status"] == "unverified"


def test_paid_citation_is_excluded_from_the_default_plan(service: ToolService) -> None:
    plan = _engine(service).analyze_deadlines(
        event_name="Paid Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        official_publication_windows_by_platform={"eventbrite": _official_window()},
        pricing_evidence_by_platform={"eventbrite": PAID_EVIDENCE},
    )
    row = next(item for item in plan["decisions"] if item["target_id"] == "eventbrite")
    assert row["eligibility_status"] == "NOT_FREE"
    assert row["pricing_status"] == "paid_option"
    assert row["free_submission_available"] is False
    assert "eventbrite" not in plan["recommended_submission_order"]


def test_analysis_recommendation_and_preview_agree(service: ToolService) -> None:
    kwargs = dict(
        event_name="Future Summit",
        event_start_datetime="2027-12-01T15:00:00",
        event_timezone="America/New_York",
        submission_datetime="2027-10-01T12:00:00Z",
        publication_deadline_buffer_hours=24,
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "guarantee")},
        documented_hours_by_platform={"10times": 24},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    analysis = service.analyze_event_publishing_deadlines(**kwargs)
    recommended = service.recommend_submission_targets(**kwargs)
    preview = service.preview_submission_plan(**kwargs)
    assert analysis["event_start"] == "2027-12-01T20:00:00+00:00"
    assert recommended["recommended_submission_order"] == analysis["recommended_submission_order"]
    assert [item["target_id"] for item in preview["preview"]] == analysis["recommended_submission_order"]
    assert preview["would_publish"] is False
    assert preview["dry_run"] is True
    by_analysis = {row["target_id"]: row for row in analysis["decisions"]}
    by_recommend = {row["target_id"]: row for row in recommended["decisions"]}
    by_preview = {row["target_id"]: row for row in preview["analysis"]["decisions"]}
    assert by_analysis["eventbrite"]["latest_safe_submission_datetime"] == "2027-11-28T20:00:00+00:00"
    for target_id in ("eventbrite", "10times"):
        assert by_recommend[target_id]["eligibility_status"] == by_analysis[target_id]["eligibility_status"]
        assert by_preview[target_id]["eligibility_status"] == by_analysis[target_id]["eligibility_status"]
        assert (
            by_recommend[target_id]["latest_safe_submission_datetime"]
            == by_analysis[target_id]["latest_safe_submission_datetime"]
            == by_preview[target_id]["latest_safe_submission_datetime"]
        )
        assert by_recommend[target_id]["timing_source"] == by_analysis[target_id]["timing_source"]
        assert by_recommend[target_id]["source_verification_status"] == by_analysis[target_id]["source_verification_status"]
        assert by_recommend[target_id]["citation_validity"] == by_analysis[target_id]["citation_validity"]
        assert by_preview[target_id]["machine_verification_performed"] is False
    assert by_analysis["eventbrite"]["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert by_analysis["eventbrite"]["source_verification_status"] == "unverified"
    assert by_analysis["10times"]["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert "eventbrite" not in analysis["recommended_submission_order"]
    assert "10times" not in analysis["recommended_submission_order"]
    assert analysis["publication_guaranteed"] is False
    assert analysis["machine_verification_performed"] is False


@pytest.mark.parametrize("content_source", ["openai", "", "seo_agent", "Template", "template-plus"])
def test_unsupported_content_source_is_rejected(service: ToolService, content_source: str) -> None:
    result = _engine(service).generate_seo_content(
        event_name="Named Event",
        event_description="Description.",
        event_start_datetime="2027-07-15T09:00:00Z",
        event_timezone="UTC",
        landing_page_url="https://example.com/e",
        registration_url="https://example.com/e/r",
        organizer_name="Org",
        target_website="eventbrite",
        location="Hall",
        content_source=content_source,
    )
    assert result["error"] == "unsupported_content_source"
    assert result["seo_agent_connected"] is False
    assert "body" not in result
    assert result["supported_content_sources"] == ["template"]


def test_long_official_event_name_is_preserved(service: ToolService) -> None:
    event_name = "International Community Operations Leadership Forum " + ("and Expo " * 8)
    content = _engine(service).generate_seo_content(
        event_name=event_name,
        event_description="A planning fixture with a long official name.",
        event_start_datetime="2027-07-15T09:00:00Z",
        event_timezone="UTC",
        landing_page_url="https://example.com/long",
        registration_url="https://example.com/long/register",
        organizer_name="Example Org",
        target_website="eventbrite",
        location="Hall",
        primary_keyword="operations forum",
        title_limit=70,
        description_limit=160,
    )
    assert content["seo_title"] == event_name
    assert content["structured_data"]["name"] == event_name
    assert content["event_name"] == event_name
    assert event_name in content["body"]
    assert "…" not in content["seo_title"]
    assert content["official_event_name_preserved"] is True
    assert content["quality_report"]["seo_title_within_limit"] is False
    assert content["quality_report"]["official_event_name_preserved"] is True
    assert any("was not truncated" in warning and "does not meet the limit" in warning for warning in content["quality_report"]["warnings"])
    lowered = content["body"].lower()
    assert "speaker" not in lowered
    assert "agenda" not in lowered
    assert "ranking" not in lowered
    assert "backlink" not in lowered
    assert content["rankings_promised"] is False
    assert content["quality_report"]["unsupplied_claims_added"] is False
    assert content["seo_agent_connected"] is False


def test_seo_agent_stays_disconnected(service: ToolService) -> None:
    result = _engine(service).generate_seo_content(
        event_name="Named Event",
        event_description="Description.",
        event_start_datetime="2027-07-15T09:00:00Z",
        event_timezone="UTC",
        landing_page_url="https://example.com/e",
        registration_url="https://example.com/e/r",
        organizer_name="Org",
        target_website="eventbrite",
        location="Hall",
        content_source="seo-agent",
    )
    assert result["error"] == "seo_agent_not_configured"
    assert result["seo_agent_connected"] is False
    assert result["content_source"] == "seo-agent"
    assert "body" not in result
    assert "structured_data" not in result


def test_planning_does_not_publish_or_record_a_live_submission(service: ToolService, sample_event) -> None:
    jobs_before = service.repo.db.fetchone("SELECT COUNT(*) AS n FROM submission_jobs")["n"]
    listings_before = service.repo.db.fetchone("SELECT COUNT(*) AS n FROM published_listings")["n"]
    _engine(service).refresh_research()
    _engine(service).research_publication_time("eventbrite")
    _engine(service).generate_seo_content(
        event_name="Dry Plan",
        event_description="Description.",
        event_start_datetime="2027-07-15T09:00:00Z",
        event_timezone="UTC",
        landing_page_url="https://example.com/dry",
        registration_url="https://example.com/dry/register",
        organizer_name="Org",
        target_website="eventbrite",
        location="Hall",
    )
    plan = _engine(service).analyze_deadlines(
        event_name="Dry Plan",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        official_publication_windows_by_platform={"eventbrite": _official_window()},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    preview = service.preview_submission_plan(
        event_name="Dry Plan",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        official_publication_windows_by_platform={"eventbrite": _official_window()},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    assert plan["publication_guaranteed"] is False
    assert preview["would_publish"] is False
    assert all(item["would_publish"] is False for item in preview["preview"])
    assert service.repo.db.fetchone("SELECT COUNT(*) AS n FROM submission_jobs")["n"] == jobs_before
    assert service.repo.db.fetchone("SELECT COUNT(*) AS n FROM published_listings")["n"] == listings_before
    service.create_event(sample_event.model_dump(mode="json"))
    dry = service.submit_event_dry_run(sample_event.event_id, "eventbrite")
    assert dry["job"]["dry_run"] is True
    assert dry["job"]["state"] != "PUBLISHED"
    assert service.repo.db.fetchone("SELECT COUNT(*) AS n FROM published_listings")["n"] == listings_before
    assert plan["machine_verification_performed"] is False
    assert preview["machine_verification_performed"] is False


def test_complete_guarantee_citation_is_not_source_verification(service: ToolService) -> None:
    plan = _engine(service).analyze_deadlines(
        event_name="Cited Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "guarantee")},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    row = next(item for item in plan["decisions"] if item["target_id"] == "eventbrite")
    assert row["citation_validity"] == "complete"
    assert row["timing_kind"] == "guarantee"
    assert row["source_verification_status"] == "unverified"
    assert row["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert row["eligibility_status"] != ELIGIBLE
    assert row["machine_verification_performed"] is False
    assert row["latest_safe_submission_datetime"] == "2027-11-28T15:00:00+00:00"
    assert "eventbrite" in plan["manual_review"]
    assert "eventbrite" not in plan["recommended_submission_order"]
    assert "eventbrite" not in plan["eligible"]


def test_recorded_human_verification_can_be_eligible(service: ToolService) -> None:
    kwargs = dict(
        event_name="Checked Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        publication_deadline_buffer_hours=24,
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "guarantee", human=True)},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    analysis = service.analyze_event_publishing_deadlines(**kwargs)
    recommended = service.recommend_submission_targets(**kwargs)
    preview = service.preview_submission_plan(**kwargs)
    row = next(item for item in analysis["decisions"] if item["target_id"] == "eventbrite")
    assert row["eligibility_status"] == ELIGIBLE
    assert row["source_verification_status"] == "human_verified"
    assert row["citation_validity"] == "complete"
    assert row["timing_kind"] == "guarantee"
    assert row["timing_source"] == "citation"
    assert row["machine_verification_performed"] is False
    assert row["timing_live_verified"] is False
    assert row["human_verification"]["verifier"] == "ops-review-ref-2026-10-29"
    assert row["human_verification"]["official_source_url"] == "https://www.example.com/official-guidelines"
    assert row["human_verification"]["verified_at"] == "2026-10-29T16:30:00+00:00"
    assert row["human_verification"]["hours"] == 48
    assert row["human_verification"]["kind"] == "guarantee"
    assert "listings" in row["human_verification"]["claim_checked"]
    assert "eventbrite" in analysis["recommended_submission_order"]
    assert recommended["recommended_submission_order"] == analysis["recommended_submission_order"]
    assert [item["target_id"] for item in preview["preview"]] == analysis["recommended_submission_order"]
    recommend_row = next(item for item in recommended["decisions"] if item["target_id"] == "eventbrite")
    preview_row = next(item for item in preview["analysis"]["decisions"] if item["target_id"] == "eventbrite")
    assert recommend_row["eligibility_status"] == preview_row["eligibility_status"] == ELIGIBLE
    assert recommend_row["source_verification_status"] == preview_row["source_verification_status"] == "human_verified"
    assert analysis["machine_verification_performed"] is False
    assert preview["would_publish"] is False


def test_human_verified_estimate_stays_risk_labelled(service: ToolService) -> None:
    plan = _engine(service).analyze_deadlines(
        event_name="Estimate Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "estimate", human=True)},
        pricing_evidence_by_platform={"eventbrite": FREE_EVIDENCE},
    )
    row = next(item for item in plan["decisions"] if item["target_id"] == "eventbrite")
    assert row["source_verification_status"] == "human_verified"
    assert row["timing_kind"] == "estimate"
    assert row["eligibility_status"] == ELIGIBLE_WITH_RISK
    assert row["eligibility_status"] != ELIGIBLE
    assert "not a guarantee" in row["eligibility_reason"]
    assert row["machine_verification_performed"] is False


def test_human_verified_window_with_unknown_pricing_stays_out(service: ToolService) -> None:
    plan = _engine(service).analyze_deadlines(
        event_name="Unpriced Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        official_publication_windows_by_platform={"eventbrite": _official_window(48, "guarantee", human=True)},
    )
    row = next(item for item in plan["decisions"] if item["target_id"] == "eventbrite")
    assert row["source_verification_status"] == "human_verified"
    assert row["free_submission_available"] is None
    assert row["pricing_status"] == "unknown"
    assert row["eligibility_status"] == MANUAL_REVIEW_REQUIRED
    assert "eventbrite" not in plan["recommended_submission_order"]


def test_registry_verification_flag_does_not_verify_a_citation() -> None:
    cited = {**_official_window(72, "guarantee"), "human_verified": True, "machine_verified": False}
    row = _policy(_platform(research={"publication_window": cited}))
    assert row["official_publication_hours"] == 72
    assert row["citation_validity"] == "complete"
    assert row["source_verification_status"] == "unverified"
    assert row["human_verification"] is None
    assert row["machine_verification_performed"] is False
    assert "not accepted" in row["publication_evidence_note"]


def test_stored_human_verification_is_reported_without_a_fetch(
    service: ToolService, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = _platform(
        platform_id="cited_target",
        documentation_url="https://www.example.com/official-guidelines",
        research={
            "pricing": FREE_EVIDENCE,
            "publication_window": _official_window(48, "guarantee", human=True),
        },
    )
    registry = PlatformsFile(version="test", platforms=[platform])
    monkeypatch.setattr(
        "event_seo_mcp.publishing.intelligence.load_platforms_file",
        lambda _path: registry,
    )
    clocks = _engine(service).research_publication_time("cited_target")
    assert clocks["live_research_performed"] is False
    assert clocks["machine_verification_performed"] is False
    assert clocks["research_timestamp"] is None
    assert clocks["citation_validity"] == "complete"
    assert clocks["source_verification_status"] == "human_verified"
    assert clocks["confidence"] == "human_verified_guarantee"
    assert clocks["google_indexing_estimate"] == "unknown"
    assert clocks["human_verification"]["verifier"] == "ops-review-ref-2026-10-29"
    plan = _engine(service).analyze_deadlines(
        event_name="Stored Check",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
    )
    row = next(item for item in plan["decisions"] if item["target_id"] == "cited_target")
    assert row["eligibility_status"] == ELIGIBLE
    assert row["machine_verification_performed"] is False
    refreshed = _engine(service).refresh_research()
    assert refreshed["live_research_performed"] is False
    assert refreshed["machine_verification_performed"] is False
    assert refreshed["counts"]["machine_verified"] == 0
    assert refreshed["counts"]["human_verified"] == 1
    assert refreshed["counts"]["live_researched"] == 0
