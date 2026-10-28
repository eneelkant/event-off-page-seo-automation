"""Submission job and state schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobState(str, Enum):
    DISCOVERED = "DISCOVERED"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
    READY = "READY"
    CONTENT_PREPARED = "CONTENT_PREPARED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    DUPLICATE = "DUPLICATE"


ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.DISCOVERED: {JobState.NEEDS_VERIFICATION, JobState.READY, JobState.BLOCKED},
    JobState.NEEDS_VERIFICATION: {JobState.READY, JobState.BLOCKED, JobState.FAILED},
    JobState.READY: {
        JobState.CONTENT_PREPARED,
        JobState.AWAITING_APPROVAL,
        JobState.SUBMITTING,
        JobState.BLOCKED,
        JobState.DUPLICATE,
    },
    JobState.CONTENT_PREPARED: {
        JobState.AWAITING_APPROVAL,
        JobState.SUBMITTING,
        JobState.BLOCKED,
    },
    JobState.AWAITING_APPROVAL: {
        JobState.SUBMITTING,
        JobState.REJECTED,
        JobState.BLOCKED,
    },
    JobState.SUBMITTING: {
        JobState.SUBMITTED,
        JobState.PENDING_REVIEW,
        JobState.PUBLISHED,
        JobState.FAILED,
        JobState.BLOCKED,
        JobState.AWAITING_APPROVAL,
        JobState.CONTENT_PREPARED,
        JobState.NEEDS_VERIFICATION,
    },
    JobState.SUBMITTED: {JobState.PENDING_REVIEW, JobState.PUBLISHED, JobState.FAILED, JobState.REJECTED},
    JobState.PENDING_REVIEW: {JobState.PUBLISHED, JobState.REJECTED, JobState.FAILED},
    JobState.PUBLISHED: set(),
    JobState.REJECTED: {JobState.READY, JobState.CONTENT_PREPARED},
    JobState.FAILED: {JobState.READY, JobState.SUBMITTING, JobState.BLOCKED},
    JobState.BLOCKED: {JobState.READY, JobState.NEEDS_VERIFICATION},
    JobState.DUPLICATE: set(),
}


class SubmissionAttemptResult(BaseModel):
    attempt_number: int
    status: JobState
    dry_run: bool
    adapter_name: str
    message: str
    evidence_paths: list[str] = Field(default_factory=list)
    response_summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SubmissionJobRecord(BaseModel):
    job_id: str
    event_id: str
    platform_id: str
    idempotency_key: str
    state: JobState
    dry_run: bool = True
    content_id: str | None = None
    published_url: str | None = None
    error_details: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
