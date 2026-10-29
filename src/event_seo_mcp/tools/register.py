"""Register MCP tools on an MCPServer instance."""

from __future__ import annotations

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
