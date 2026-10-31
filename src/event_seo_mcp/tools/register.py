"""Register MCP tools on an MCPServer instance."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer

from event_seo_mcp.tools.handlers import ToolService


def register_tools(mcp: MCPServer, service: ToolService) -> None:
    @mcp.tool()
    def health_check() -> dict[str, Any]:
        """Return server health, adapter, provider, and optional integration status."""
        return service.health_check()

    @mcp.tool()
    def list_platforms(category: str | None = None, include_workflows: bool = False) -> dict[str, Any]:
        """List distinct platforms (30). Set include_workflows=true to include workflow rows."""
        return service.list_platforms(category, include_workflows=include_workflows)

    @mcp.tool()
    def list_registry_entries(category: str | None = None) -> dict[str, Any]:
        """List 35 registry submit entries (29 non-LinkedIn platforms + 6 LinkedIn workflows)."""
        return service.list_registry_entries(category)

    @mcp.tool()
    def list_workflows(parent_platform_id: str | None = "linkedin") -> dict[str, Any]:
        """List workflows for a parent platform (LinkedIn = 6 thought-leadership workflows)."""
        return service.list_workflows(parent_platform_id)

    @mcp.tool()
    def get_registry_stats() -> dict[str, Any]:
        """Validate registry totals: 35 entries / 7 categories / 30 platforms / 6 LinkedIn workflows."""
        return service.get_registry_stats()

    @mcp.tool()
    def get_platform_details(platform_id: str) -> dict[str, Any]:
        """Get platform/workflow record, adapter selection, credential presence, and research."""
        return service.get_platform_details(platform_id)

    @mcp.tool()
    def get_credential_status(platform_id: str | None = None) -> dict[str, Any]:
        """Report which credential env vars are present (secret values never returned)."""
        return service.get_credential_status(platform_id)

    @mcp.tool()
    def evaluate_publishing_rules(
        platform_id: str,
        event_id: str | None = None,
        dry_run: bool | None = None,
        authorize_publication: bool = False,
    ) -> dict[str, Any]:
        """Evaluate publishing rules for dry-run or live submit (persists evaluation; no publish)."""
        return service.evaluate_publishing_rules(
            platform_id,
            event_id,
            dry_run=dry_run,
            authorize_publication=authorize_publication,
        )

    @mcp.tool()
    async def discover_platform_submission(platform_id: str) -> dict[str, Any]:
        """Discover public submission hints for a platform without inventing URLs."""
        return await service.discover_platform_submission(platform_id)

    @mcp.tool()
    def validate_event(event: dict[str, Any]) -> dict[str, Any]:
        """Validate an event payload against the event schema."""
        return service.validate_event(event)

    @mcp.tool()
    def create_event(event: dict[str, Any]) -> dict[str, Any]:
        """Validate and persist an event record."""
        return service.create_event(event)

    @mcp.tool()
    def get_event(event_id: str) -> dict[str, Any]:
        """Fetch a stored event by id."""
        return service.get_event(event_id)

    @mcp.tool()
    def generate_platform_content(
        event_id: str,
        platform_id: str,
        content_type: str,
        extra_instructions: str | None = None,
    ) -> dict[str, Any]:
        """Generate platform-specific content for review (template or configured AI provider)."""
        return service.generate_platform_content(
            event_id, platform_id, content_type, extra_instructions
        )

    @mcp.tool()
    def generate_campaign_content(
        event_id: str, platform_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Generate content drafts for many platforms in a campaign."""
        return service.generate_campaign_content(event_id, platform_ids)

    @mcp.tool()
    def validate_generated_content(content: dict[str, Any]) -> dict[str, Any]:
        """Validate a generated content object against schema and soft limits."""
        return service.validate_generated_content(content)

    @mcp.tool()
    def preview_submission(
        event_id: str, platform_id: str, content_id: str | None = None
    ) -> dict[str, Any]:
        """Preview a submission payload without publishing."""
        return service.preview_submission(event_id, platform_id, content_id)

    @mcp.tool()
    def check_submission_eligibility(event_id: str, platform_id: str) -> dict[str, Any]:
        """Check dry-run eligibility and why live submission remains blocked."""
        return service.check_submission_eligibility(event_id, platform_id)

    @mcp.tool()
    def submit_event(
        event_id: str,
        platform_id: str,
        content_id: str | None = None,
        dry_run: bool = True,
        authorize_publication: bool = False,
    ) -> dict[str, Any]:
        """Submit (or dry-run) an event to one platform. Live mode requires authorize_publication=true."""
        return service.submit_event(
            event_id,
            platform_id,
            content_id=content_id,
            dry_run=dry_run,
            authorize_publication=authorize_publication,
        )

    @mcp.tool()
    def submit_campaign(
        event_id: str,
        platform_ids: list[str] | None = None,
        dry_run: bool = True,
        authorize_publication: bool = False,
    ) -> dict[str, Any]:
        """Submit (or dry-run) an event across multiple platforms. Defaults to dry_run=true."""
        return service.submit_campaign(
            event_id,
            platform_ids,
            dry_run=dry_run,
            authorize_publication=authorize_publication,
        )

    @mcp.tool()
    def get_submission_status(job_id: str) -> dict[str, Any]:
        """Get submission job status by job_id."""
        return service.get_submission_status(job_id)

    @mcp.tool()
    def list_submission_jobs(
        event_id: str | None = None, platform_id: str | None = None
    ) -> dict[str, Any]:
        """List submission jobs, optionally filtered."""
        return service.list_submission_jobs(event_id, platform_id)

    @mcp.tool()
    def verify_backlink(
        event_id: str,
        published_url: str,
        landing_page_url: str | None = None,
        html_fixture: str | None = None,
    ) -> dict[str, Any]:
        """Verify whether a published page links back to the event landing page."""
        return service.verify_backlink(
            event_id, published_url, landing_page_url, html_fixture
        )

    @mcp.tool()
    def verify_event_backlinks(event_id: str) -> dict[str, Any]:
        """Verify backlinks for all stored published listings of an event."""
        return service.verify_event_backlinks(event_id)

    @mcp.tool()
    def get_campaign_report(event_id: str | None = None) -> dict[str, Any]:
        """Return campaign KPI report. Does not fabricate traffic or conversions."""
        return service.get_campaign_report(event_id)

    @mcp.tool()
    def export_submission_report(
        event_id: str | None = None, format: str = "json"
    ) -> dict[str, Any]:
        """Export submission report as JSON or CSV text."""
        return service.export_submission_report(event_id, format)

    @mcp.tool()
    def check_adapter_health() -> dict[str, Any]:
        """Check adapter, provider, and optional framework availability."""
        return service.check_adapter_health()

    @mcp.tool()
    def list_submission_targets() -> dict[str, Any]:
        """Read approved submission sites from Google Sheets. Passwords are never returned."""
        return service.list_submission_targets()

    @mcp.tool()
    def submit_event_to_site(
        event_name: str,
        event_description: str,
        landing_page_url: str,
        event_datetime: str,
        target_site: str,
        registration_url: str,
        location: str | None = None,
        virtual_event_details: str | None = None,
        dry_run: bool = True,
        authorize_publication: bool = False,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Track an event submission in Google Sheets. Dry-run is the default and does not publish."""
        return service.submit_event_to_site(
            event_name=event_name,
            event_description=event_description,
            landing_page_url=landing_page_url,
            event_datetime=event_datetime,
            target_site=target_site,
            registration_url=registration_url,
            location=location,
            virtual_event_details=virtual_event_details,
            dry_run=dry_run,
            authorize_publication=authorize_publication,
            event_id=event_id,
        )

    @mcp.tool()
    def get_target_publication_policy(platform_id: str | None = None) -> dict[str, Any]:
        """Return registry publication policy for one target or every configured target.

        This reads the local registry and does not fetch the website. A target is free only
        when a complete official citation says so. paid_submission_possible false is not that citation.
        """
        return service.get_target_publication_policy(platform_id)

    @mcp.tool()
    def research_target_publication_time(platform_id: str) -> dict[str, Any]:
        """Read one target's stored citation. Does not fetch the website or claim machine verification.

        citation_validity and source_verification_status are separate. A complete citation, including one
        with a verifier name and claim, stays unverified. Google indexing is separate from publication time.
        """
        return service.research_target_publication_time(platform_id)

    @mcp.tool()
    def refresh_target_research() -> dict[str, Any]:
        """Store a registry snapshot for every target. This is not live research or machine verification."""
        return service.refresh_target_research()

    @mcp.tool()
    def generate_seo_event_content(
        event_name: str,
        event_description: str,
        event_start_datetime: str,
        event_timezone: str,
        landing_page_url: str,
        registration_url: str,
        organizer_name: str,
        target_website: str,
        event_end_datetime: str | None = None,
        location: str | None = None,
        virtual_event_details: str | None = None,
        target_audience: str | None = None,
        primary_keyword: str | None = None,
        secondary_keywords: list[str] | None = None,
        content_source: str = "template",
        content_language: str = "en",
    ) -> dict[str, Any]:
        """Draft listing copy from supplied facts. The only supported content_source is template.

        seo-agent stays disconnected. Other content_source values are rejected and are not relabeled as template.
        The official event name is kept in full even when it exceeds the title limit.
        """
        return service.generate_seo_event_content(
            event_name=event_name,
            event_description=event_description,
            event_start_datetime=event_start_datetime,
            event_timezone=event_timezone,
            landing_page_url=landing_page_url,
            registration_url=registration_url,
            organizer_name=organizer_name,
            target_website=target_website,
            event_end_datetime=event_end_datetime,
            location=location,
            virtual_event_details=virtual_event_details,
            target_audience=target_audience,
            primary_keyword=primary_keyword,
            secondary_keywords=secondary_keywords,
            content_source=content_source,
            content_language=content_language,
        )

    @mcp.tool()
    def analyze_event_publishing_deadlines(
        event_name: str,
        event_start_datetime: str,
        event_timezone: str,
        submission_datetime: str | None = None,
        publication_deadline_buffer_hours: int = 24,
        conservative_fallback_hours: int | None = None,
        allow_paid: bool = False,
        virtual_event: bool | None = None,
        event_id: str | None = None,
        documented_hours_by_platform: dict[str, int] | None = None,
        documented_business_days_by_platform: dict[str, int] | None = None,
        official_publication_windows_by_platform: dict[str, Any] | None = None,
        pricing_evidence_by_platform: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Classify every non-workflow target against the timezone-aware event start.

        A complete citation is not source verification. kind guarantee does not make a target ELIGIBLE.
        A human_verification name, timestamp, and claim are not authentication. No trusted verification
        workflow is configured, so those citations stay unverified and require manual review.
        Machine verification is not performed. Unknown timelines stay out of the default recommendation.
        A pricing citation, including classification verified_free, is a claim. It does not set
        free_submission_available and does not make caller-supplied or heuristic windows eligible.
        """
        return service.analyze_event_publishing_deadlines(
            event_name=event_name,
            event_start_datetime=event_start_datetime,
            event_timezone=event_timezone,
            submission_datetime=submission_datetime,
            publication_deadline_buffer_hours=publication_deadline_buffer_hours,
            conservative_fallback_hours=conservative_fallback_hours,
            allow_paid=allow_paid,
            virtual_event=virtual_event,
            event_id=event_id,
            documented_hours_by_platform=documented_hours_by_platform,
            documented_business_days_by_platform=documented_business_days_by_platform,
            official_publication_windows_by_platform=official_publication_windows_by_platform,
            pricing_evidence_by_platform=pricing_evidence_by_platform,
        )

    @mcp.tool()
    def recommend_submission_targets(
        event_name: str,
        event_start_datetime: str,
        event_timezone: str,
        submission_datetime: str | None = None,
        publication_deadline_buffer_hours: int = 24,
        conservative_fallback_hours: int | None = None,
        event_id: str | None = None,
        documented_hours_by_platform: dict[str, int] | None = None,
        documented_business_days_by_platform: dict[str, int] | None = None,
        official_publication_windows_by_platform: dict[str, Any] | None = None,
        pricing_evidence_by_platform: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the default plan. Unknown and claimed pricing, unknown timelines, and unverified citations stay excluded.

        Timing arguments match analyze_event_publishing_deadlines. A verified_free classification
        and caller-supplied verification metadata cannot make a target ELIGIBLE. Paid options stay excluded.
        """
        return service.recommend_submission_targets(
            event_name=event_name,
            event_start_datetime=event_start_datetime,
            event_timezone=event_timezone,
            submission_datetime=submission_datetime,
            publication_deadline_buffer_hours=publication_deadline_buffer_hours,
            conservative_fallback_hours=conservative_fallback_hours,
            event_id=event_id,
            documented_hours_by_platform=documented_hours_by_platform,
            documented_business_days_by_platform=documented_business_days_by_platform,
            official_publication_windows_by_platform=official_publication_windows_by_platform,
            pricing_evidence_by_platform=pricing_evidence_by_platform,
        )

    @mcp.tool()
    def preview_submission_plan(
        event_name: str,
        event_start_datetime: str,
        event_timezone: str,
        submission_datetime: str | None = None,
        publication_deadline_buffer_hours: int = 24,
        conservative_fallback_hours: int | None = None,
        event_id: str | None = None,
        documented_hours_by_platform: dict[str, int] | None = None,
        documented_business_days_by_platform: dict[str, int] | None = None,
        official_publication_windows_by_platform: dict[str, Any] | None = None,
        pricing_evidence_by_platform: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Preview the same default plan as recommend_submission_targets. The preview does not publish.

        Unverified citations stay in manual review. Machine verification is not claimed.
        """
        return service.preview_submission_plan(
            event_name=event_name,
            event_start_datetime=event_start_datetime,
            event_timezone=event_timezone,
            submission_datetime=submission_datetime,
            publication_deadline_buffer_hours=publication_deadline_buffer_hours,
            conservative_fallback_hours=conservative_fallback_hours,
            event_id=event_id,
            documented_hours_by_platform=documented_hours_by_platform,
            documented_business_days_by_platform=documented_business_days_by_platform,
            official_publication_windows_by_platform=official_publication_windows_by_platform,
            pricing_evidence_by_platform=pricing_evidence_by_platform,
        )

    @mcp.tool()
    def submit_event_dry_run(event_id: str, platform_id: str) -> dict[str, Any]:
        """Run the existing submit path with dry-run forced on and publication authorization forced off."""
        return service.submit_event_dry_run(event_id, platform_id)

    @mcp.resource(
        "event-seo://publication-policies",
        name="publication_policies",
        description="Read-only registry publication policies. Timelines are unknown unless already cited.",
        mime_type="application/json",
    )
    def publication_policies() -> str:
        return json.dumps(service.get_target_publication_policy())

    @mcp.prompt(name="check_event_deadlines", description="Ask for an explainable free-site submission plan.")
    def check_event_deadlines(event_name: str, event_start_datetime: str, event_timezone: str) -> str:
        return (
            f"Use analyze_event_publishing_deadlines for {event_name} starting {event_start_datetime} "
            f"({event_timezone}). Do not treat unknown publication times as eligible, and do not publish."
        )

    @mcp.tool()
    def record_publication_update(
        event_id: str,
        publication_status: str,
        site_name: str | None = None,
        website: str | None = None,
        published_url: str | None = None,
        published_date: str | None = None,
        external_submission_id: str | None = None,
    ) -> dict[str, Any]:
        """Update a tracked Submissions row after a live URL is confirmed. Idempotent for the same URL."""
        return service.record_publication_update(
            event_id=event_id,
            publication_status=publication_status,
            site_name=site_name,
            website=website,
            published_url=published_url,
            published_date=published_date,
            external_submission_id=external_submission_id,
        )
