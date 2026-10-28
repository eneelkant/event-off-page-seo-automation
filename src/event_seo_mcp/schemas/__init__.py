"""Pydantic schemas for events, platforms, content, and submissions."""

from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord, FAQItem
from event_seo_mcp.schemas.platform import PlatformRecord, PlatformsFile
from event_seo_mcp.schemas.submission import (
    JobState,
    SubmissionAttemptResult,
    SubmissionJobRecord,
)

__all__ = [
    "EventRecord",
    "FAQItem",
    "GeneratedContent",
    "JobState",
    "PlatformRecord",
    "PlatformsFile",
    "SubmissionAttemptResult",
    "SubmissionJobRecord",
]
