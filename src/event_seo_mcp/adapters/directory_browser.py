"""Generic directory browser adapter using Playwright when available."""

from __future__ import annotations

from event_seo_mcp.adapters.base import CapabilityReport, PlatformAdapter, SubmissionResult
from event_seo_mcp.browser.playwright_adapter import PlaywrightBrowser
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState


class DirectoryBrowserAdapter(PlatformAdapter):
    name = "directory_browser"

    def check_capabilities(self) -> CapabilityReport:
        browser = PlaywrightBrowser()
        pw = browser.availability()
        return CapabilityReport(
            adapter_name=self.name,
            installed=pw["installed"],
            configured=True,
            healthy=pw["installed"],
            supported_operations=[
                "check_capabilities",
                "validate_submission",
                "prepare_submission",
                "submit",
                "verify_submission",
                "capture_evidence",
            ],
            notes=(
                "Browser dry-run can open a verified submission URL when present. "
                "Stops on CAPTCHA/MFA/login walls. Never bypasses protections."
            ),
            details=pw,
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
        if not platform.verified_submission_url:
            return SubmissionResult(
                state=JobState.NEEDS_VERIFICATION,
                message="No verified_submission_url; run discover_platform_submission first.",
                dry_run=dry_run,
                error_code="MISSING_SUBMISSION_URL",
                response_summary=prepared,
            )
        if dry_run or not authorize_publication:
            browser = PlaywrightBrowser()
            evidence: list[str] = []
            summary = dict(prepared)
            if browser.availability()["installed"]:
                probe = browser.probe_page(str(platform.verified_submission_url), dry_run=True)
                evidence = probe.get("evidence_paths") or []
                summary["browser_probe"] = probe
            return SubmissionResult(
                state=JobState.CONTENT_PREPARED if dry_run else JobState.AWAITING_APPROVAL,
                message="Directory browser dry-run/preview completed; nothing published.",
                dry_run=dry_run,
                evidence_paths=evidence,
                response_summary=summary,
            )
        return SubmissionResult(
            state=JobState.BLOCKED,
            message=(
                "Live browser submission blocked: platform marked NEEDS_VERIFICATION "
                "and human verification may be required."
            ),
            dry_run=False,
            error_code="NEEDS_VERIFICATION",
            response_summary=prepared,
        )
