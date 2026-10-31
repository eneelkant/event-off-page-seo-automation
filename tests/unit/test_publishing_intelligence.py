"""Publication policy, SEO drafts, and event-date eligibility."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from event_seo_mcp.publishing.intelligence import (
    ALREADY_SUBMITTED,
    DEADLINE_PASSED,
    ELIGIBLE,
    ELIGIBLE_WITH_RISK,
    EVENT_PAST,
    PUBLICATION_TIME_UNKNOWN,
    subtract_business_days,
)
from event_seo_mcp.tools.handlers import ToolService


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


def test_eventbrite_policy_uses_registry_sources_only(service: ToolService) -> None:
    row = _engine(service).publication_policy("eventbrite")["targets"][0]
    assert row["free_submission_available"] is True
    assert "eventbrite.com/platform/docs" in str(row["official_guidelines_url"])
    clocks = _engine(service).research_publication_time("eventbrite")
    assert clocks["publication_time_confidence"] == "unknown"
    assert clocks["ranking_time"] == "not_estimated"
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
    assert eventbrite["eligibility_status"] == ELIGIBLE
    assert eventbrite["latest_safe_submission_datetime"]
    assert "eventbrite" in early["recommended_submission_order"]

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
    sample = next(row for row in risk["decisions"] if row["free_submission_available"] is True)
    assert sample["eligibility_status"] == ELIGIBLE_WITH_RISK
    assert sample["publication_time_confidence"] == "heuristic"


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
    assert row["eligibility_status"] == ELIGIBLE


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
    assert result["job"]["state"] != "PUBLISHED"
