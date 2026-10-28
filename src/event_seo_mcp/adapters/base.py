"""Shared submission adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState


@dataclass
class CapabilityReport:
    adapter_name: str
    installed: bool
    configured: bool
    healthy: bool
    supported_operations: list[str]
    notes: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubmissionResult:
    state: JobState
    message: str
    dry_run: bool
    published_url: str | None = None
    evidence_paths: list[str] = field(default_factory=list)
    response_summary: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


class PlatformAdapter(ABC):
    name: str

    @abstractmethod
    def check_capabilities(self) -> CapabilityReport:
        raise NotImplementedError

    def validate_submission(
        self, event: EventRecord, platform: PlatformRecord, content: GeneratedContent
    ) -> list[str]:
        missing = event.missing_fields_for(platform.required_fields)
        errors: list[str] = []
        if missing:
            errors.append(f"Missing required event fields: {', '.join(missing)}")
        if not content.body.strip():
            errors.append("Generated content body is empty")
        if platform.automation_status == "BLOCKED":
            errors.append("Platform is BLOCKED")
        return errors

    def prepare_submission(
        self, event: EventRecord, platform: PlatformRecord, content: GeneratedContent
    ) -> dict[str, Any]:
        return {
            "platform_id": platform.platform_id,
            "event_id": event.event_id,
            "title": content.title,
            "body": content.body,
            "destination_url": str(content.destination_url),
            "submission_method": platform.submission_method,
            "verified_submission_url": platform.verified_submission_url,
            "automation_status": platform.automation_status,
        }

    @abstractmethod
    def submit(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content: GeneratedContent,
        *,
        dry_run: bool,
        authorize_publication: bool,
    ) -> SubmissionResult:
        raise NotImplementedError

    def verify_submission(self, result: SubmissionResult) -> SubmissionResult:
        if result.dry_run:
            return result
        if result.state == JobState.PUBLISHED and not result.published_url:
            result.state = JobState.FAILED
            result.error_code = "MISSING_PUBLIC_URL"
            result.message = "Cannot mark PUBLISHED without a verified public listing URL"
        return result

    def capture_evidence(self, result: SubmissionResult) -> list[str]:
        return list(result.evidence_paths)
