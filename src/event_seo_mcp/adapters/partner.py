"""Partner marketing adapter — prepares outreach, no live portal automation."""

from __future__ import annotations

from event_seo_mcp.adapters.base import CapabilityReport, PlatformAdapter, SubmissionResult
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState


class PartnerAdapter(PlatformAdapter):
    name = "partner"

    def check_capabilities(self) -> CapabilityReport:
        return CapabilityReport(
            adapter_name=self.name,
            installed=True,
            configured=True,
            healthy=True,
            supported_operations=[
                "check_capabilities",
                "validate_submission",
                "prepare_submission",
                "submit",
                "verify_submission",
                "capture_evidence",
            ],
            notes="Partner portals require eligibility; adapter prepares outreach copy only.",
        )

    def submit(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content: GeneratedContent,
        *,
        dry_run: bool,
        authorize_publication: bool,
    ) -> SubmissionResult:
        prepared = self.prepare_submission(event, platform, content)
        errors = self.validate_submission(event, platform, content)
        if errors:
            return SubmissionResult(
                state=JobState.FAILED,
                message="; ".join(errors),
                dry_run=dry_run,
                error_code="VALIDATION_FAILED",
                response_summary=prepared,
            )
        state = JobState.CONTENT_PREPARED if dry_run else JobState.AWAITING_APPROVAL
        return SubmissionResult(
            state=state,
            message="Partner promotion content prepared; live portal submit not verified.",
            dry_run=dry_run,
            response_summary=prepared,
        )
