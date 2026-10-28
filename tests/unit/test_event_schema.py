"""Event schema validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from event_seo_mcp.schemas.event import EventRecord


def test_valid_event(sample_event: EventRecord) -> None:
    assert sample_event.event_id == "evt-test-001"
    assert "AI" in sample_event.primary_keywords


def test_invalid_url(sample_event: EventRecord) -> None:
    data = sample_event.model_dump(mode="json")
    data["landing_page_url"] = "not-a-url"
    with pytest.raises(ValidationError):
        EventRecord.model_validate(data)


def test_invalid_end_before_start(sample_event: EventRecord) -> None:
    data = sample_event.model_dump(mode="json")
    data["end_datetime"] = "2020-01-01T00:00:00"
    with pytest.raises(ValidationError):
        EventRecord.model_validate(data)


def test_empty_keywords_rejected(sample_event: EventRecord) -> None:
    data = sample_event.model_dump(mode="json")
    data["primary_keywords"] = ["  ", ""]
    with pytest.raises(ValidationError):
        EventRecord.model_validate(data)


def test_missing_required_field(sample_event: EventRecord) -> None:
    data = sample_event.model_dump(mode="json")
    del data["organizer_name"]
    with pytest.raises(ValidationError):
        EventRecord.model_validate(data)
