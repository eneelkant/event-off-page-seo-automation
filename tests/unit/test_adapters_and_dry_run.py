"""Adapter capability and dry-run safety."""

from __future__ import annotations

from event_seo_mcp.adapters.registry import get_adapter, list_adapters
from event_seo_mcp.orchestration.orchestrator import Orchestrator
from event_seo_mcp.database.repository import Repository
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.submission import JobState
from event_seo_mcp.settings import Settings
from event_seo_mcp.tools.handlers import ToolService


def test_all_adapters_report_capabilities() -> None:
    for adapter in list_adapters():
        report = adapter.check_capabilities()
        assert report.adapter_name
        assert "check_capabilities" in report.supported_operations


def test_dry_run_does_not_publish(
    service: ToolService, repo: Repository, sample_event: EventRecord, settings: Settings
) -> None:
    repo.upsert_event(sample_event)
    result = service.submit_event(
        sample_event.event_id,
        "eventbrite",
        dry_run=True,
        authorize_publication=False,
    )
    assert result.get("refused") is not True
    job = result["job"]
    assert job["dry_run"] is True
    assert job["state"] in {JobState.SUBMITTED.value, JobState.CONTENT_PREPARED.value, JobState.AWAITING_APPROVAL.value}
    assert job.get("published_url") in (None, "")


def test_live_without_authorization_refused(
    service: ToolService, repo: Repository, sample_event: EventRecord
) -> None:
    repo.upsert_event(sample_event)
    result = service.submit_event(
        sample_event.event_id,
        "eventbrite",
        dry_run=False,
        authorize_publication=False,
    )
    assert result.get("refused") is True


def test_optional_integrations_soft_fail(service: ToolService) -> None:
    health = service.check_adapter_health()
    names = {i["integration"] for i in health["integrations"]}
    assert names == {"browser-use", "crawl4ai", "agno", "skyvern"}
    assert all(i.get("soft_fail") for i in health["integrations"])


def test_human_verification_patterns() -> None:
    from event_seo_mcp.browser.playwright_adapter import HUMAN_CHALLENGE_PATTERNS

    assert any(p.search("Please complete the CAPTCHA") for p in HUMAN_CHALLENGE_PATTERNS)
