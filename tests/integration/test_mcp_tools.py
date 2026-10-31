"""MCP server tool registration and smoke flows."""

from __future__ import annotations

import pytest

from event_seo_mcp.database.connection import Database
from event_seo_mcp.database.repository import Repository
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.server import create_server
from event_seo_mcp.settings import Settings


EXPECTED_TOOLS = {
    "health_check",
    "list_platforms",
    "get_platform_details",
    "discover_platform_submission",
    "validate_event",
    "create_event",
    "get_event",
    "generate_platform_content",
    "generate_campaign_content",
    "validate_generated_content",
    "preview_submission",
    "check_submission_eligibility",
    "submit_event",
    "submit_campaign",
    "get_submission_status",
    "list_submission_jobs",
    "verify_backlink",
    "verify_event_backlinks",
    "get_campaign_report",
    "export_submission_report",
    "check_adapter_health",
    "list_submission_targets",
    "submit_event_to_site",
    "record_publication_update",
    "get_target_publication_policy",
    "research_target_publication_time",
    "refresh_target_research",
    "generate_seo_event_content",
    "analyze_event_publishing_deadlines",
    "recommend_submission_targets",
    "preview_submission_plan",
    "verify_publication_source",
    "verify_pricing_source",
    "submit_event_dry_run",
}


@pytest.mark.asyncio
async def test_tools_registered(settings: Settings) -> None:
    db = Database(settings.resolved_database_path)
    mcp, service = create_server(settings, database=db)
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(names)
    by_name = {tool.name: tool for tool in tools}
    timing_inputs = {
        "documented_hours_by_platform",
        "documented_business_days_by_platform",
        "official_publication_windows_by_platform",
        "pricing_evidence_by_platform",
        "publication_deadline_buffer_hours",
    }
    for name in (
        "analyze_event_publishing_deadlines",
        "recommend_submission_targets",
        "preview_submission_plan",
    ):
        schema = by_name[name].input_schema
        properties = schema["properties"] if isinstance(schema, dict) else schema.properties
        assert timing_inputs <= set(properties)
    for name in ("verify_publication_source", "verify_pricing_source"):
        schema = by_name[name].input_schema
        properties = schema["properties"] if isinstance(schema, dict) else schema.properties
        assert set(properties) <= {"platform_id", "verification_authorization"}
        assert "official_source_url" not in properties
        assert "human_verified" not in properties
        assert "pricing_live_verified" not in properties
    content_schema = by_name["generate_seo_event_content"].input_schema
    content_properties = content_schema["properties"] if isinstance(content_schema, dict) else content_schema.properties
    assert "content_source" in content_properties


@pytest.mark.asyncio
async def test_health_via_call_tool(settings: Settings) -> None:
    db = Database(settings.resolved_database_path)
    mcp, _service = create_server(settings, database=db)
    result = await mcp.call_tool("health_check", {})
    # result is CallToolResult-like; accept structured content
    assert result is not None


def test_end_to_end_dry_run(settings: Settings, sample_event: EventRecord) -> None:
    db = Database(settings.resolved_database_path)
    _mcp, service = create_server(settings, database=db)
    created = service.create_event(sample_event.model_dump(mode="json"))
    assert created["created"] is True
    platforms = service.list_platforms()
    assert platforms["count"] >= 30
    content = service.generate_platform_content(
        sample_event.event_id, "eventbrite", "event_directory_description"
    )
    assert content["content"]["title"]
    preview = service.preview_submission(sample_event.event_id, "eventbrite")
    assert "prepared" in preview
    submitted = service.submit_event(sample_event.event_id, "eventbrite", dry_run=True)
    assert submitted["job"]["dry_run"] is True
    report = service.get_campaign_report(sample_event.event_id)
    assert report["planned_submissions"] >= 1
    exported = service.export_submission_report(sample_event.event_id, format="csv")
    assert "csv" in exported
