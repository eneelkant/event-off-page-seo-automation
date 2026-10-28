"""Content generation and provider tests."""

from __future__ import annotations

import pytest

from event_seo_mcp.providers.base import ProviderError
from event_seo_mcp.providers.factory import get_provider, list_provider_status
from event_seo_mcp.providers.openai_provider import OpenAIProvider
from event_seo_mcp.providers.template_provider import TemplateProvider
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.settings import Settings


def test_template_provider_generates(sample_event: EventRecord) -> None:
    platform = PlatformRecord(
        platform_id="eventbrite",
        platform_name="Eventbrite",
        category="event_directory",
        submission_method="api_preferred",
        adapter_name="eventbrite",
        authentication_method="oauth_or_api_key",
        supported_content_types=["event_directory_description"],
    )
    content = TemplateProvider().generate_content(
        sample_event, platform, "event_directory_description"
    )
    assert content.event_id == sample_event.event_id
    assert content.character_count == len(content.body)
    assert content.validation_status == "needs_review"


def test_openai_unavailable_without_key(settings: Settings) -> None:
    provider = OpenAIProvider(settings)
    assert provider.available() is False
    platform = PlatformRecord(
        platform_id="eventbrite",
        platform_name="Eventbrite",
        category="event_directory",
        submission_method="api",
        adapter_name="eventbrite",
        authentication_method="api_key",
    )
    with pytest.raises(ProviderError):
        provider.generate_content(sample_event_stub(), platform, "event_directory_description")


def sample_event_stub() -> EventRecord:
    return EventRecord.model_validate(
        {
            "event_id": "e1",
            "event_title": "T",
            "event_description": "D",
            "landing_page_url": "https://example.com/e",
            "start_datetime": "2026-01-01T00:00:00",
            "timezone": "UTC",
            "event_type": "meetup",
            "target_audience": "devs",
            "primary_keywords": ["ai"],
            "registration_url": "https://example.com/r",
            "organizer_name": "Org",
        }
    )


def test_provider_status(settings: Settings) -> None:
    status = list_provider_status(settings)
    names = {s["provider"] for s in status}
    assert names == {"template", "openai", "anthropic", "gemini"}
    assert get_provider(settings).name == "template"
