"""Operation audits, health status, and GA4 startup warnings."""

from __future__ import annotations

import json
import logging

import pytest

from event_seo_mcp.observability import ga4_runtime_status, record_operation
from event_seo_mcp.server import main
from event_seo_mcp.settings import reset_settings_cache
from event_seo_mcp.tools.handlers import ToolService

PLAN = {
    "event_name": "Observed Summit",
    "event_start_datetime": "2027-12-01T15:00:00Z",
    "event_timezone": "UTC",
    "submission_datetime": "2027-10-01T00:00:00Z",
    "event_id": "evt-observe-1",
}
SECRET_URL = "https://user:pass@events.example.com/secret?token=sekret-value"
SECRET_CAMPAIGN = "Bearer sk-abc123456789"


def _rows(service: ToolService, action: str) -> list[dict]:
    stored = service.repo.db.fetchall(
        "SELECT action, entity_id, details_json FROM audit_logs WHERE action = ? ORDER BY log_id",
        (action,),
    )
    rows = []
    for row in stored:
        item = dict(row)
        item["details"] = json.loads(item["details_json"])
        rows.append(item)
    return rows


def _assert_duration(details: dict) -> None:
    assert isinstance(details["duration_ms"], int)
    assert details["duration_ms"] >= 0


def _assert_no_secrets(blob: str) -> None:
    assert "https://" not in blob
    assert "sekret-value" not in blob
    assert "sk-abc123456789" not in blob
    assert "user:pass" not in blob
    assert "PRIVATE KEY" not in blob
    assert "123456" not in blob


def test_planning_success_and_failure_are_audited(service: ToolService) -> None:
    planned = service.analyze_event_publishing_deadlines(**PLAN)
    assert planned.get("error") is None
    success = _rows(service, "planning")
    assert len(success) == 1
    assert success[0]["entity_id"] == "evt-observe-1"
    assert success[0]["details"]["outcome"] == "success"
    assert success[0]["details"]["summary"] == "planned"
    _assert_duration(success[0]["details"])

    failed = service.analyze_event_publishing_deadlines(**{**PLAN, "event_start_datetime": "not-a-date"})
    assert failed["error"] == "validation_error"
    failure = _rows(service, "planning")[1]
    assert failure["details"]["outcome"] == "failure"
    assert failure["details"]["summary"] == "validation_error"
    _assert_duration(failure["details"])


def test_utm_preview_audits_success_and_hides_urls(service: ToolService) -> None:
    preview = service.preview_event_tracking_url(
        "https://events.example.com/summit?ref=1#tickets",
        "eventbrite",
        "Spring Launch",
    )
    assert preview["error"] is None
    assert preview["tracked_url"]
    success = _rows(service, "utm_generation")
    assert success[0]["entity_id"] is None
    assert success[0]["details"]["outcome"] == "success"
    assert success[0]["details"]["summary"] == "tracked_url"
    _assert_duration(success[0]["details"])

    failed = service.preview_event_tracking_url(SECRET_URL, "eventbrite", SECRET_CAMPAIGN)
    assert failed["error"] == "invalid_url"
    assert failed["tracked_url"] is None
    blob = json.dumps(_rows(service, "utm_generation"))
    _assert_no_secrets(blob)
    assert _rows(service, "utm_generation")[1]["details"]["summary"] == "invalid_url"


def test_plan_with_tracking_records_both_operations(service: ToolService) -> None:
    preview = service.preview_submission_plan(
        **PLAN,
        landing_page_url=SECRET_URL,
        campaign_name=SECRET_CAMPAIGN,
    )
    assert preview["would_publish"] is False
    assert preview["submission_tracking"]["error"] == "invalid_url"
    assert len(_rows(service, "planning")) == 1
    utm = _rows(service, "utm_generation")
    assert len(utm) == 1
    assert utm[0]["details"]["outcome"] == "failure"
    assert utm[0]["entity_id"] == "evt-observe-1"
    _assert_no_secrets(json.dumps(utm))

    recommended = service.recommend_submission_targets(**PLAN)
    assert "submission_tracking" not in recommended
    assert len(_rows(service, "utm_generation")) == 1
    assert len(_rows(service, "planning")) == 2


def test_ga4_query_is_audited_once_for_attribution(service: ToolService) -> None:
    disabled = service.query_ga4_campaign_performance("Launch")
    assert disabled["error"] == "ga4_disabled"
    assert disabled["rows"] is None
    failure = _rows(service, "ga4_query")
    assert failure[0]["details"]["outcome"] == "failure"
    assert failure[0]["details"]["summary"] == "ga4_disabled"
    _assert_duration(failure[0]["details"])

    service.settings.ga4_enabled = True
    service.settings.ga4_property_id = "123456789"

    class FakeClient:
        def run_report(self, request: dict, timeout: float | None = None) -> dict:
            assert "private_key" not in json.dumps(request)
            return {"row_count": 0, "rows": []}

    report = service.query_ga4_campaign_performance("Launch", client=FakeClient())
    assert report["ok"] is True
    assert report["data_state"] == "empty"
    success = _rows(service, "ga4_query")[1]
    assert success["details"]["outcome"] == "success"
    assert success["details"]["summary"] == "report"

    service.audit_campaign_attribution("Launch", client=FakeClient())
    assert len(_rows(service, "ga4_query")) == 3


def test_audit_failure_preserves_the_tool_result(service: ToolService, caplog: pytest.LogCaptureFixture) -> None:
    def explode(*_args, **_kwargs):
        raise RuntimeError("BEGIN PRIVATE KEY secret-token")

    service.repo.audit = explode  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        result = service.preview_event_tracking_url("https://events.example.com/a", "10times", "Launch")
    assert result["error"] is None
    assert result["tracked_url"]
    assert "operation audit could not be stored" in caplog.text
    assert "secret-token" not in caplog.text
    assert "PRIVATE KEY" not in caplog.text


def test_health_reports_three_ga4_states(service: ToolService, monkeypatch: pytest.MonkeyPatch) -> None:
    health = service.health_check()
    assert health["ga4_enabled"] is False
    assert health["ga4_status"] == "disabled"
    assert health["live_source_verification_enabled"] is False
    assert "ga4_property_id" not in health

    service.settings.ga4_enabled = True
    service.settings.ga4_property_id = None
    assert service.health_check()["ga4_status"] == "misconfigured"

    service.settings.ga4_property_id = "not-a-property"
    monkeypatch.setattr("event_seo_mcp.observability.ga4_client_importable", lambda: True)
    assert ga4_runtime_status(service.settings) == "misconfigured"

    service.settings.ga4_property_id = "123456789"
    monkeypatch.setattr("event_seo_mcp.observability.ga4_client_importable", lambda: False)
    assert service.health_check()["ga4_status"] == "misconfigured"

    monkeypatch.setattr("event_seo_mcp.observability.ga4_client_importable", lambda: True)
    configured = service.health_check()
    assert configured["ga4_status"] == "configured"
    assert "123456789" not in json.dumps(configured)

    service.settings.live_source_verification_enabled = True
    assert service.health_check()["live_source_verification_enabled"] is True


def test_startup_warns_only_when_enabled_and_misconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []

    class Dummy:
        def run(self, transport: str = "stdio") -> None:
            calls.append(transport)

    monkeypatch.setattr("event_seo_mcp.server.create_server", lambda _settings: (Dummy(), None))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "observe.db"))
    monkeypatch.setenv("AI_PROVIDER", "template")
    monkeypatch.setenv("DRY_RUN_DEFAULT", "true")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("GA4_ENABLED", "true")
    monkeypatch.setenv("GA4_PROPERTY_ID", "123456789")
    reset_settings_cache()
    with caplog.at_level(logging.WARNING):
        main(["--stdio"])
    assert calls == ["stdio"]
    assert caplog.text.count("GA4 is enabled but not configured") == 1
    assert "123456789" not in caplog.text

    calls.clear()
    caplog.clear()
    monkeypatch.setenv("GA4_ENABLED", "false")
    reset_settings_cache()
    with caplog.at_level(logging.WARNING):
        main(["--stdio"])
    assert calls == ["stdio"]
    assert "GA4 is enabled but not configured" not in caplog.text


def test_record_operation_drops_urls_and_unsafe_ids(service: ToolService) -> None:
    record_operation(
        service.repo,
        "planning",
        outcome="failure",
        duration_ms=-5,
        summary=SECRET_URL,
        entity_id=SECRET_URL,
    )
    row = _rows(service, "planning")[0]
    assert row["entity_id"] is None
    assert row["details"]["summary"] == "redacted"
    assert row["details"]["duration_ms"] == 0
    assert row["details"]["outcome"] == "failure"
    _assert_no_secrets(json.dumps(row))
