"""Meetup adapter — dry-run scaffold."""

from __future__ import annotations

from event_seo_mcp.adapters.base import CapabilityReport, PlatformAdapter, SubmissionResult
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState


class MeetupAdapter(PlatformAdapter):
    name = "meetup"

    def check_capabilities(self) -> CapabilityReport:
        return CapabilityReport(
            adapter_name=self.name,
            installed=True,
            configured=False,
            healthy=True,
            supported_operations=[
                "check_capabilities",
                "validate_submission",
                "prepare_submission",
                "submit",
                "verify_submission",
                "capture_evidence",
            ],
            notes="Meetup OAuth/API not live-tested; dry-run only.",
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
        errors = self.validate_submission(event, platform, content)
        prepared = self.prepare_submission(event, platform, content)
        if errors:
            return SubmissionResult(
                state=JobState.FAILED,
                message="; ".join(errors),
                dry_run=dry_run,
                error_code="VALIDATION_FAILED",
                response_summary=prepared,
            )
        if dry_run or not authorize_publication:
            return SubmissionResult(
                state=JobState.CONTENT_PREPARED if dry_run else JobState.AWAITING_APPROVAL,
                message="Meetup dry-run/preview only; live API not verified.",
                dry_run=dry_run,
                response_summary=prepared,
            )
        return SubmissionResult(
            state=JobState.BLOCKED,
            message="Live Meetup submission blocked pending verification.",
            dry_run=False,
            error_code="NEEDS_VERIFICATION",
            response_summary=prepared,
        )
