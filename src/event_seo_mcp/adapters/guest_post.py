"""Guest posting adapter — pitch/article drafts only."""

from __future__ import annotations

from event_seo_mcp.adapters.base import CapabilityReport, PlatformAdapter, SubmissionResult
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState


class GuestPostAdapter(PlatformAdapter):
    name = "guest_post"

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
            notes="Editorial contribution paths; drafts only until publisher workflow verified.",
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
        return SubmissionResult(
            state=JobState.CONTENT_PREPARED if dry_run else JobState.AWAITING_APPROVAL,
            message="Guest post pitch/article prepared for editorial review.",
            dry_run=dry_run,
            response_summary=prepared,
        )
