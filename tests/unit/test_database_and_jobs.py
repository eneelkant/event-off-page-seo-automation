"""Database and job transition tests."""

from __future__ import annotations

import pytest

from event_seo_mcp.database.repository import Repository
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.submission import JobState


def test_event_roundtrip(repo: Repository, sample_event: EventRecord) -> None:
    repo.upsert_event(sample_event)
    loaded = repo.get_event(sample_event.event_id)
    assert loaded is not None
    assert loaded.event_title == sample_event.event_title


def test_duplicate_idempotency(repo: Repository, sample_event: EventRecord) -> None:
    repo.upsert_event(sample_event)
    key = Repository.make_idempotency_key(sample_event.event_id, "eventbrite", "event_directory_description")
    job1 = repo.create_job(
        event_id=sample_event.event_id,
        platform_id="eventbrite",
        idempotency_key=key,
        state=JobState.READY,
        dry_run=True,
    )
    job2 = repo.create_job(
        event_id=sample_event.event_id,
        platform_id="eventbrite",
        idempotency_key=key,
        state=JobState.READY,
        dry_run=True,
    )
    assert job1.job_id == job2.job_id


def test_illegal_transition(repo: Repository, sample_event: EventRecord) -> None:
    repo.upsert_event(sample_event)
    job = repo.create_job(
        event_id=sample_event.event_id,
        platform_id="eventbrite",
        idempotency_key="k1",
        state=JobState.READY,
        dry_run=True,
    )
    with pytest.raises(ValueError):
        repo.transition_job(job.job_id, JobState.PUBLISHED)


def test_retry_attempt_numbers(repo: Repository, sample_event: EventRecord) -> None:
    repo.upsert_event(sample_event)
    job = repo.create_job(
        event_id=sample_event.event_id,
        platform_id="meetup",
        idempotency_key="k2",
        state=JobState.READY,
        dry_run=True,
    )
    assert repo.next_attempt_number(job.job_id) == 1
    repo.add_attempt(
        job.job_id,
        attempt_number=1,
        status=JobState.FAILED,
        dry_run=True,
        adapter_name="meetup",
        message="transient",
        error_code="TMP",
    )
    assert repo.next_attempt_number(job.job_id) == 2
