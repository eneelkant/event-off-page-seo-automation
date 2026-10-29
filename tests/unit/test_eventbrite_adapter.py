"""Eventbrite adapter + client — mocked API only (no real Eventbrite calls)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from event_seo_mcp.adapters.eventbrite import (
    EventbriteAdapter,
    build_eventbrite_create_payload,
)
from event_seo_mcp.adapters.eventbrite_client import EventbriteApiError, EventbriteClient
from event_seo_mcp.discovery.platform_discovery import load_platforms_file
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.submission import JobState
from event_seo_mcp.security.redaction import redact_mapping
from event_seo_mcp.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def platforms():
    return load_platforms_file(ROOT / "config/platforms.json")


@pytest.fixture()
def eventbrite_platform(platforms):
    p = platforms.by_id("eventbrite")
    assert p is not None
    return p


@pytest.fixture()
def sample_event() -> EventRecord:
    data = json.loads((FIXTURES / "sample_event.json").read_text(encoding="utf-8"))
    # Ensure start is always in the future relative to test run.
    start = datetime.now(timezone.utc) + timedelta(days=30)
    data["start_datetime"] = start.replace(tzinfo=None).isoformat(timespec="seconds")
    data["end_datetime"] = (start + timedelta(hours=3)).replace(tzinfo=None).isoformat(
        timespec="seconds"
    )
    data["timezone"] = "UTC"
    return EventRecord.model_validate(data)


@pytest.fixture()
def content(sample_event: EventRecord) -> GeneratedContent:
    body = sample_event.event_description
    return GeneratedContent(
        content_id="c-eb-1",
        event_id=sample_event.event_id,
        platform_id="eventbrite",
        content_type="event_directory_description",
        title=sample_event.event_title,
        body=body,
        destination_url=str(sample_event.landing_page_url),
        cta="Register",
        character_count=len(body),
        validation_status="valid",
    )


@pytest.fixture()
def eb_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "t.db",
        platforms_config_path=ROOT / "config/platforms.json",
        repo_root=ROOT,
        dry_run_default=True,
        eventbrite_api_token=None,
        eventbrite_organization_id=None,
        eventbrite_currency="USD",
        eventbrite_publish_on_create=False,
    )


def test_registry_eventbrite_status_accurate(eventbrite_platform) -> None:
    assert eventbrite_platform.automation_status == "NEEDS_VERIFICATION"
    assert eventbrite_platform.verified_submission_url is not None
    assert "organizations" in str(eventbrite_platform.verified_submission_url)
    assert eventbrite_platform.approval_required is True
    assert "NEEDS_VERIFICATION" in (eventbrite_platform.operational_notes or "")
    assert "live" in (eventbrite_platform.operational_notes or "").lower()


def test_capabilities_reflect_missing_credentials(eb_settings: Settings) -> None:
    adapter = EventbriteAdapter(settings=eb_settings)
    report = adapter.check_capabilities()
    assert report.configured is False
    assert report.details["eventbrite_token_present"] is False
    assert report.details["create_path"].startswith("/organizations/")


def test_capabilities_configured_when_token_and_org(eb_settings: Settings) -> None:
    eb_settings.eventbrite_api_token = "test-token-not-real"
    eb_settings.eventbrite_organization_id = "999001"
    adapter = EventbriteAdapter(settings=eb_settings)
    assert adapter.check_capabilities().configured is True


def test_dry_run_never_calls_network(
    eb_settings: Settings,
    sample_event: EventRecord,
    eventbrite_platform,
    content: GeneratedContent,
) -> None:
    calls: list[str] = []

    class BoomClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append("init")

        def close(self) -> None:
            return None

    adapter = EventbriteAdapter(settings=eb_settings, client_factory=BoomClient)
    result = adapter.submit(
        sample_event,
        eventbrite_platform,
        content,
        dry_run=True,
        authorize_publication=False,
    )
    assert calls == []
    assert result.dry_run is True
    assert result.state == JobState.CONTENT_PREPARED
    assert result.published_url is None
    assert "eventbrite_create_body" in result.response_summary
    assert result.response_summary["eventbrite_create_body"]["event"]["currency"] == "USD"


def test_live_without_auth_awaits_approval(
    eb_settings: Settings,
    sample_event: EventRecord,
    eventbrite_platform,
    content: GeneratedContent,
) -> None:
    adapter = EventbriteAdapter(settings=eb_settings)
    result = adapter.submit(
        sample_event,
        eventbrite_platform,
        content,
        dry_run=False,
        authorize_publication=False,
    )
    assert result.state == JobState.AWAITING_APPROVAL


def test_live_authorized_without_token_blocked(
    eb_settings: Settings,
    sample_event: EventRecord,
    eventbrite_platform,
    content: GeneratedContent,
) -> None:
    adapter = EventbriteAdapter(settings=eb_settings)
    result = adapter.submit(
        sample_event,
        eventbrite_platform,
        content,
        dry_run=False,
        authorize_publication=True,
    )
    assert result.state == JobState.BLOCKED
    assert result.error_code == "NOT_CONFIGURED"
    assert "EVENTBRITE_API_TOKEN" in result.message


def test_live_authorized_without_org_blocked(
    eb_settings: Settings,
    sample_event: EventRecord,
    eventbrite_platform,
    content: GeneratedContent,
) -> None:
    eb_settings.eventbrite_api_token = "test-token-not-real"
    adapter = EventbriteAdapter(settings=eb_settings)
    result = adapter.submit(
        sample_event,
        eventbrite_platform,
        content,
        dry_run=False,
        authorize_publication=True,
    )
    assert result.state == JobState.BLOCKED
    assert "ORGANIZATION" in result.message


def test_live_create_mocked_success_draft(
    eb_settings: Settings,
    sample_event: EventRecord,
    eventbrite_platform,
    content: GeneratedContent,
) -> None:
    eb_settings.eventbrite_api_token = "test-token-not-real"
    eb_settings.eventbrite_organization_id = "org-42"
    eb_settings.eventbrite_publish_on_create = False

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer test-token-not-real"
        path = request.url.path
        if path.endswith("/organizations/org-42/events/"):
            return httpx.Response(
                200,
                json={
                    "id": "eb-100",
                    "status": "draft",
                    "url": "https://www.eventbrite.com/e/test-100",
                },
            )
        if path.endswith("/events/eb-100/ticket_classes/"):
            return httpx.Response(200, json={"id": "tc-1", "free": True})
        if "/publish/" in path:
            pytest.fail("publish must not be called when EVENTBRITE_PUBLISH_ON_CREATE=false")
        return httpx.Response(404, json={"error": "not_found", "error_description": path})

    transport = httpx.MockTransport(handler)
    mock_client = httpx.Client(transport=transport)

    def factory(token: str, **kwargs: Any) -> EventbriteClient:
        return EventbriteClient(token, client=mock_client, **{
            k: v for k, v in kwargs.items() if k in {"base_url", "timeout_seconds"}
        })

    adapter = EventbriteAdapter(settings=eb_settings, client_factory=factory)
    result = adapter.submit(
        sample_event,
        eventbrite_platform,
        content,
        dry_run=False,
        authorize_publication=True,
    )
    assert result.state == JobState.SUBMITTED
    assert result.published_url is None
    assert result.response_summary["live_create"]["eventbrite_event_id"] == "eb-100"
    assert result.response_summary["live_create"]["published"] is False
    # Token must never appear in response summary.
    blob = json.dumps(result.response_summary)
    assert "test-token-not-real" not in blob


def test_live_create_mocked_with_publish(
    eb_settings: Settings,
    sample_event: EventRecord,
    eventbrite_platform,
    content: GeneratedContent,
) -> None:
    eb_settings.eventbrite_api_token = "test-token-not-real"
    eb_settings.eventbrite_organization_id = "org-42"
    eb_settings.eventbrite_publish_on_create = True
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        path = request.url.path
        if path.endswith("/organizations/org-42/events/"):
            return httpx.Response(
                200,
                json={
                    "id": "eb-200",
                    "status": "draft",
                    "url": "https://www.eventbrite.com/e/test-200",
                },
            )
        if path.endswith("/ticket_classes/"):
            return httpx.Response(200, json={"id": "tc-2"})
        if path.endswith("/publish/"):
            return httpx.Response(200, json={"published": True})
        return httpx.Response(500, json={"error": "unexpected"})

    transport = httpx.MockTransport(handler)
    mock_http = httpx.Client(transport=transport)

    def factory(token: str, **kwargs: Any) -> EventbriteClient:
        return EventbriteClient(
            token,
            client=mock_http,
            base_url=kwargs.get("base_url", "https://www.eventbriteapi.com/v3"),
            timeout_seconds=kwargs.get("timeout_seconds", 30.0),
        )

    adapter = EventbriteAdapter(settings=eb_settings, client_factory=factory)
    result = adapter.submit(
        sample_event,
        eventbrite_platform,
        content,
        dry_run=False,
        authorize_publication=True,
    )
    assert any(p.endswith("/publish/") for p in seen)
    assert result.state == JobState.PUBLISHED
    assert result.published_url == "https://www.eventbrite.com/e/test-200"


def test_api_error_redacts_secrets_in_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": "INVALID_AUTH",
                "error_description": "Bad token Bearer secret-value-xyz",
            },
        )

    client = EventbriteClient(
        "secret-value-xyz",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(EventbriteApiError) as excinfo:
        client.list_organizations()
    msg = str(excinfo.value)
    assert "secret-value-xyz" not in msg
    assert "REDACTED" in msg or "401" in msg


def test_client_rejects_incomplete_create_payload() -> None:
    client = EventbriteClient("tok", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    with pytest.raises(ValueError, match="missing required"):
        client.create_event("1", {"event": {"name": {"html": "x"}}})


def test_build_payload_shape(
    sample_event: EventRecord, content: GeneratedContent
) -> None:
    body = build_eventbrite_create_payload(sample_event, content, currency="usd")
    event = body["event"]
    assert event["currency"] == "USD"
    assert "html" in event["name"]
    assert "timezone" in event["start"] and "utc" in event["start"]
    assert event["start"]["utc"].endswith("Z")
    assert event["listed"] is False


def test_redaction_covers_eventbrite_token_key() -> None:
    out = redact_mapping({"eventbrite_api_token": "abc123", "ok": 1})
    assert out["eventbrite_api_token"] == "***REDACTED***"
    assert out["ok"] == 1


def test_validation_rejects_past_start(
    eb_settings: Settings,
    eventbrite_platform,
    content: GeneratedContent,
) -> None:
    past = EventRecord.model_validate(
        {
            **json.loads((FIXTURES / "sample_event.json").read_text(encoding="utf-8")),
            "start_datetime": "2020-01-01T12:00:00",
            "end_datetime": "2020-01-01T15:00:00",
            "timezone": "UTC",
        }
    )
    adapter = EventbriteAdapter(settings=eb_settings)
    errors = adapter.validate_submission(past, eventbrite_platform, content)
    assert any("future" in e.lower() for e in errors)
