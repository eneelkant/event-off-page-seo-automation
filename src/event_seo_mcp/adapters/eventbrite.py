"""Eventbrite adapter — dry-run scaffold until API credentials verified."""

from __future__ import annotations

import os

from event_seo_mcp.adapters.base import CapabilityReport, PlatformAdapter, SubmissionResult
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState


class EventbriteAdapter(PlatformAdapter):
    name = "eventbrite"

    def check_capabilities(self) -> CapabilityReport:
        token = os.getenv("EVENTBRITE_API_TOKEN")
        return CapabilityReport(
            adapter_name=self.name,
            installed=True,
            configured=bool(token),
            healthy=True,
            supported_operations=[
                "check_capabilities",
                "validate_submission",
                "prepare_submission",
                "submit",
                "verify_submission",
                "capture_evidence",
            ],
            notes=(
                "Official Eventbrite API exists. Live create-event calls are disabled until "
                "credentials and endpoint verification complete. Dry-run is supported."
            ),
            details={"eventbrite_token_present": bool(token)},
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
                message=(
                    "Dry-run: Eventbrite payload prepared; no API call made."
                    if dry_run
                    else "Publication authorization required before live Eventbrite submit."
                ),
                dry_run=dry_run,
                response_summary=prepared,
            )
        # Live path intentionally blocked until verified.
        return SubmissionResult(
            state=JobState.BLOCKED,
            message=(
                "Live Eventbrite submission is NEEDS_VERIFICATION. "
                "Configure EVENTBRITE_API_TOKEN and verify create-event flow before enabling."
            ),
            dry_run=False,
            error_code="NEEDS_VERIFICATION",
            response_summary=prepared,
        )
