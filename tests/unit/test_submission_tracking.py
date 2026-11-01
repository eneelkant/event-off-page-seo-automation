"""Tracked URLs attach to dry-run plans and leave stored events unchanged."""

from __future__ import annotations

import json

from event_seo_mcp.publishing.intelligence import ELIGIBLE
from event_seo_mcp.publishing.source_verification import FetchResult
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.tools.handlers import ToolService

OFFICIAL = "https://www.eventbrite.com/platform/docs/create-events"
LANDING = "https://events.example.com/summit?ref=newsletter#register"
CAMPAIGN = "Spring Launch"


class Scripted:
    def __init__(self, result: FetchResult) -> None:
        self.result = result

    def fetch(self, url: str) -> FetchResult:
        assert url == OFFICIAL
        return self.result


def _body(payload: dict) -> FetchResult:
    return FetchResult(
        outcome="ok",
        reason="fetched",
        final_url=OFFICIAL,
        status_code=200,
        content_type="application/json",
        body=json.dumps(payload).encode(),
        retrieved_at="2026-10-31T12:00:00+00:00",
    )


def _trust_eventbrite(service: ToolService) -> None:
    service.settings.live_source_verification_enabled = True
    service.settings.verification_operator_token = "operator-token-not-a-secret"
    service.verify_publication_source(
        "eventbrite",
        "operator-token-not-a-secret",
        fetcher=Scripted(
            _body(
                {
                    "schema_version": 1,
                    "evidence_type": "publication_window",
                    "platform_id": "eventbrite",
                    "kind": "guarantee",
                    "hours": 48,
                    "evidence_summary": "Official documentation states listings are published within 48 hours.",
                }
            )
        ),
    )
    service.verify_pricing_source(
        "eventbrite",
        "operator-token-not-a-secret",
        fetcher=Scripted(
            _body(
                {
                    "schema_version": 1,
                    "evidence_type": "pricing",
                    "platform_id": "eventbrite",
                    "free_submission_available": True,
                    "paid_options_available": False,
                    "evidence_summary": "Official pricing documentation states a free listing is available.",
                }
            )
        ),
    )


def test_plan_keeps_canonical_url_and_does_not_store_it(service: ToolService, sample_event: EventRecord) -> None:
    service.create_event(sample_event.model_dump(mode="json"))
    _trust_eventbrite(service)
    kwargs = dict(
        event_name="Tracked Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
        landing_page_url=LANDING,
        campaign_name=CAMPAIGN,
    )
    preview = service.preview_submission_plan(**kwargs)
    recommended = service.recommend_submission_targets(**kwargs)
    assert preview["dry_run"] is True
    assert preview["would_publish"] is False
    link = next(item for item in preview["preview"] if item["target_id"] == "eventbrite")
    assert link["eligibility_status"] == ELIGIBLE
    assert link["canonical_landing_page_url"] == LANDING
    assert link["tracked_landing_page_url"] != LANDING
    assert "utm_source=eventbrite" in link["tracked_landing_page_url"]
    assert "utm_campaign=Spring%20Launch" in link["tracked_landing_page_url"]
    assert link["tracked_landing_page_url"].endswith("#register")
    assert link["utm_parameter_preservation"] == "unknown"
    assert preview["submission_tracking"]["stored_landing_page_modified"] is False
    assert preview["submission_tracking"]["conflict_policy"] == "replace"
    again = service.preview_submission_plan(**kwargs)
    again_link = next(item for item in again["preview"] if item["target_id"] == "eventbrite")
    assert again_link["tracked_landing_page_url"] == link["tracked_landing_page_url"]
    recommended_link = next(item for item in recommended["submission_tracking"]["links"] if item["target_id"] == "eventbrite")
    assert recommended_link["tracked_landing_page_url"] == link["tracked_landing_page_url"]
    stored = service.get_event(sample_event.event_id)["event"]["landing_page_url"]
    assert stored == "https://example.com/events/test-ai-meetup"
    assert "utm_" not in stored


def test_tracking_is_omitted_until_requested_and_invalid_urls_do_not_publish(service: ToolService) -> None:
    kwargs = dict(
        event_name="Plain Summit",
        event_start_datetime="2027-12-01T15:00:00Z",
        event_timezone="UTC",
        submission_datetime="2027-10-01T00:00:00Z",
    )
    plain = service.preview_submission_plan(**kwargs)
    assert "submission_tracking" not in plain
    invalid = service.preview_submission_plan(**kwargs, landing_page_url="javascript:alert(1)", campaign_name="Launch")
    assert invalid["would_publish"] is False
    assert invalid["submission_tracking"]["error"] == "invalid_url"
    assert invalid["submission_tracking"]["links"] == [] or all(
        item["tracked_landing_page_url"] is None for item in invalid["submission_tracking"]["links"]
    )
    disabled = service.query_ga4_campaign_performance("Launch")
    assert disabled["error"] == "ga4_disabled"
    assert disabled["rows"] is None
    audit = service.audit_campaign_attribution("Launch", source="eventbrite")
    assert audit["error"] == "ga4_disabled"
    assert audit["backlink_verified"] is False
    assert audit["tracking_broken"] is False
    assert service.health_check()["ga4_enabled"] is False
