"""Community platform adapter with policy-safe defaults."""

from __future__ import annotations

from event_seo_mcp.adapters.base import CapabilityReport, PlatformAdapter, SubmissionResult
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState

POLICY_BLOCKED = {
    "reddit_artificial",
    "reddit_machinelearning",
}


class CommunityAdapter(PlatformAdapter):
    name = "community"

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
            notes="Respects community policies; promotional automation blocked by default for strict subs.",
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
        if platform.platform_id in POLICY_BLOCKED and not dry_run:
            return SubmissionResult(
                state=JobState.BLOCKED,
                message="Platform policy likely prohibits automated promotional posting.",
                dry_run=False,
                error_code="POLICY_BLOCK",
                response_summary=prepared,
            )
        if dry_run or not authorize_publication:
            return SubmissionResult(
                state=JobState.CONTENT_PREPARED if dry_run else JobState.AWAITING_APPROVAL,
                message="Community post prepared for human review; nothing published.",
                dry_run=dry_run,
                response_summary=prepared,
            )
        return SubmissionResult(
            state=JobState.BLOCKED,
            message="Live community posting requires verified official API and policy clearance.",
            dry_run=False,
            error_code="NEEDS_VERIFICATION",
            response_summary=prepared,
        )
