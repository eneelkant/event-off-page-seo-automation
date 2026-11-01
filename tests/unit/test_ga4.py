"""GA4 report building uses a fake client and never invents metrics."""

from __future__ import annotations

import json

import pytest

from event_seo_mcp.reporting import ga4
from event_seo_mcp.reporting.ga4 import query_ga4_campaign_performance, validate_report_fields
from event_seo_mcp.settings import Settings


class FakeClient:
    def __init__(self, pages: list[dict] | None = None, error: BaseException | None = None) -> None:
        self.pages = pages or []
        self.error = error
        self.calls: list[dict] = []

    def run_report(self, request: dict, timeout: float | None = None) -> dict:
        self.calls.append(
            {
                "offset": request["offset"],
                "limit": request["limit"],
                "metrics": [item["name"] for item in request["metrics"]],
                "dimensions": [item["name"] for item in request["dimensions"]],
                "dimension_filter": request["dimension_filter"],
                "timeout": timeout,
            }
        )
        if self.error and (not self.pages or request["offset"] > 0):
            raise self.error
        index = request["offset"] // request["limit"]
        return self.pages[index]


def _row(source: str, sessions: str, campaign: str = "Spring Launch", path: str = "/summit") -> dict:
    return {
        "dimension_values": [
            {"value": source},
            {"value": "event_directory"},
            {"value": campaign},
            {"value": path},
        ],
        "metric_values": [
            {"value": sessions},
            {"value": "2"},
            {"value": "4"},
            {"value": "5"},
        ],
    }


def test_disabled_report_is_not_a_zero_result() -> None:
    result = query_ga4_campaign_performance("123", "Spring Launch", "2026-01-01", "2026-01-31", enabled=False)
    assert result["ok"] is False
    assert result["error"] == "ga4_disabled"
    assert result["rows"] is None
    assert result["row_count"] is None
    assert result["sessions_in_returned_rows"] is None
    assert result["fabricated"] is False


def test_configuration_errors_do_not_call_the_client() -> None:
    client = FakeClient()
    missing = query_ga4_campaign_performance(None, "Spring Launch", "2026-01-01", "2026-01-31", enabled=True, client=client)
    assert missing["error"] == "configuration_error"
    invalid = query_ga4_campaign_performance("abc", "Spring Launch", "2026-13-01", "2026-01-31", enabled=True, client=client)
    assert invalid["error"] == "configuration_error"
    assert client.calls == []


def test_report_parses_rows_and_omits_conversions_by_default() -> None:
    client = FakeClient(pages=[{"row_count": 1, "rows": [_row("eventbrite", "3")]}])
    result = query_ga4_campaign_performance(
        "properties/123456",
        "Spring Launch",
        "30daysAgo",
        "today",
        source="Eventbrite",
        medium="event_directory",
        page_path="https://events.example.com/summit?utm_source=eventbrite",
        enabled=True,
        client=client,
    )
    assert result["ok"] is True
    assert result["data_state"] == "rows"
    assert result["rows"][0]["sessions"] == 3
    assert result["rows"][0]["sessionSource"] == "eventbrite"
    assert result["sessions_in_returned_rows"] == 3
    assert "conversions" not in result["metrics"]
    assert client.calls[0]["dimension_filter"]["and_group"]["expressions"][1]["filter"]["string_filter"]["value"] == "eventbrite"
    assert client.calls[0]["dimension_filter"]["and_group"]["expressions"][-1]["filter"]["string_filter"]["value"] == "/summit"


def test_empty_report_is_success_and_errors_are_not_zeros() -> None:
    empty = query_ga4_campaign_performance(
        "123",
        "Spring Launch",
        "2026-01-01",
        "2026-01-31",
        enabled=True,
        client=FakeClient(pages=[{"row_count": 0, "rows": []}]),
    )
    assert empty["ok"] is True
    assert empty["error"] is None
    assert empty["rows"] == []
    assert empty["row_count"] == 0
    assert empty["data_state"] == "empty"
    assert empty["sessions_in_returned_rows"] == 0

    class Unauthenticated(Exception):
        pass

    secret = "-----BEGIN PRIVATE KEY-----\nsecret-key-material\n-----END PRIVATE KEY-----"
    failed = query_ga4_campaign_performance(
        "123",
        "Spring Launch",
        "2026-01-01",
        "2026-01-31",
        enabled=True,
        client=FakeClient(error=Unauthenticated(secret)),
    )
    assert failed["ok"] is False
    assert failed["error"] == "authentication_error"
    assert failed["rows"] is None
    assert failed["row_count"] is None
    blob = json.dumps(failed)
    assert "PRIVATE KEY" not in blob
    assert "secret-key-material" not in blob


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("ResourceExhausted", "quota_exceeded"),
        ("TimeoutError", "timeout"),
        ("InvalidArgument", "metric_not_supported"),
    ],
)
def test_api_failures_keep_rows_unavailable(name: str, code: str) -> None:
    error_type = type(name, (Exception,), {})
    message = "field is incompatible" if code == "metric_not_supported" else "failed"
    result = query_ga4_campaign_performance(
        "123",
        "Spring Launch",
        "2026-01-01",
        "2026-01-31",
        enabled=True,
        include_conversions=True,
        client=FakeClient(error=error_type(message)),
    )
    assert result["error"] == code
    assert result["rows"] is None
    assert result["data_state"] == "unavailable"


def test_pagination_and_truncation() -> None:
    pages = [
        {"row_count": 2, "rows": [_row("eventbrite", "1")]},
        {"row_count": 2, "rows": [_row("10times", "4")]},
    ]
    client = FakeClient(pages=pages)
    result = query_ga4_campaign_performance(
        "123",
        "Spring Launch",
        "2026-01-01",
        "2026-01-31",
        enabled=True,
        page_size=1,
        max_pages=5,
        client=client,
    )
    assert result["complete"] is True
    assert result["truncated"] is False
    assert result["returned_row_count"] == 2
    assert [row["sessionSource"] for row in result["rows"]] == ["eventbrite", "10times"]
    assert client.calls[1]["offset"] == 1

    truncated = query_ga4_campaign_performance(
        "123",
        "Spring Launch",
        "2026-01-01",
        "2026-01-31",
        enabled=True,
        page_size=1,
        max_pages=1,
        client=FakeClient(pages=[{"row_count": 3, "rows": [_row("eventbrite", "1")]}]),
    )
    assert truncated["ok"] is True
    assert truncated["complete"] is False
    assert truncated["truncated"] is True
    assert truncated["sessions_in_returned_rows"] is None


def test_later_page_failure_discards_partial_rows() -> None:
    result = query_ga4_campaign_performance(
        "123",
        "Spring Launch",
        "2026-01-01",
        "2026-01-31",
        enabled=True,
        page_size=1,
        client=FakeClient(
            pages=[{"row_count": 2, "rows": [_row("eventbrite", "1")]}],
            error=TimeoutError("late"),
        ),
    )
    assert result["error"] == "timeout"
    assert result["rows"] is None


def test_missing_optional_client_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> None:
        raise ga4._ClientMissing()

    monkeypatch.setattr(ga4, "_default_client", missing)
    result = query_ga4_campaign_performance("123", "Spring Launch", "2026-01-01", "2026-01-31", enabled=True)
    assert result["error"] == "ga4_client_missing"
    assert result["rows"] is None


def test_schema_rejects_unknown_fields_and_settings_default_off() -> None:
    with pytest.raises(ValueError):
        validate_report_fields(["sessionSource"], ["conversions"], allow_conversions=False)
    with pytest.raises(ValueError):
        validate_report_fields(["city"], ["sessions"], allow_conversions=False)
    settings = Settings(ga4_enabled=False, ga4_property_id="")
    assert settings.ga4_enabled is False
    assert settings.ga4_property_id is None
    assert settings.utm_default_medium == "event_directory"
    assert settings.utm_conflict_policy == "replace"
