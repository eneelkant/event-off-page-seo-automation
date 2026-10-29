"""Repository helpers over SQLite."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from event_seo_mcp.database.connection import Database
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import ALLOWED_TRANSITIONS, JobState, SubmissionJobRecord
from event_seo_mcp.security.redaction import redact_mapping


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # --- events ---
    def upsert_event(self, event: EventRecord) -> EventRecord:
        now = _now()
        existing = self.db.fetchone("SELECT event_id FROM events WHERE event_id = ?", (event.event_id,))
        payload = event.model_dump_json()
        if existing:
            self.db.execute(
                "UPDATE events SET payload_json = ?, updated_at = ? WHERE event_id = ?",
                (payload, now, event.event_id),
            )
        else:
            self.db.execute(
                "INSERT INTO events(event_id, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (event.event_id, payload, now, now),
            )
        self.audit("system", "upsert_event", "event", event.event_id, {"event_id": event.event_id})
        return event

    def get_event(self, event_id: str) -> EventRecord | None:
        row = self.db.fetchone("SELECT payload_json FROM events WHERE event_id = ?", (event_id,))
        if not row:
            return None
        return EventRecord.model_validate_json(row["payload_json"])

    def list_events(self) -> list[EventRecord]:
        rows = self.db.fetchall("SELECT payload_json FROM events ORDER BY created_at DESC")
        return [EventRecord.model_validate_json(r["payload_json"]) for r in rows]

    # --- platforms ---
    def upsert_platform(self, platform: PlatformRecord) -> None:
        self.db.execute(
            """
            INSERT INTO platforms(platform_id, payload_json, automation_status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(platform_id) DO UPDATE SET
              payload_json = excluded.payload_json,
              automation_status = excluded.automation_status,
              updated_at = excluded.updated_at
            """,
            (
                platform.platform_id,
                platform.model_dump_json(),
                platform.automation_status,
                _now(),
            ),
        )

    def list_platforms(self) -> list[PlatformRecord]:
        rows = self.db.fetchall("SELECT payload_json FROM platforms ORDER BY platform_id")
        return [PlatformRecord.model_validate_json(r["payload_json"]) for r in rows]

    def get_platform(self, platform_id: str) -> PlatformRecord | None:
        row = self.db.fetchone(
            "SELECT payload_json FROM platforms WHERE platform_id = ?", (platform_id,)
        )
        if not row:
            return None
        return PlatformRecord.model_validate_json(row["payload_json"])

    # --- content ---
    def save_content(self, content: GeneratedContent) -> GeneratedContent:
        content_id = content.content_id or f"cnt-{uuid.uuid4().hex[:12]}"
        content.content_id = content_id
        self.db.execute(
            """
            INSERT INTO generated_content(
              content_id, event_id, platform_id, content_type, payload_json,
              validation_status, approval_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_id,
                content.event_id,
                content.platform_id,
                content.content_type,
                content.model_dump_json(),
                content.validation_status,
                content.approval_status,
                _now(),
            ),
        )
        return content

    def get_content(self, content_id: str) -> GeneratedContent | None:
        row = self.db.fetchone(
            "SELECT payload_json FROM generated_content WHERE content_id = ?", (content_id,)
        )
        if not row:
            return None
        return GeneratedContent.model_validate_json(row["payload_json"])

    # --- jobs ---
    def find_job_by_idempotency(self, key: str) -> SubmissionJobRecord | None:
        row = self.db.fetchone(
            "SELECT * FROM submission_jobs WHERE idempotency_key = ?", (key,)
        )
        return self._row_to_job(row) if row else None

    def create_job(
        self,
        *,
        event_id: str,
        platform_id: str,
        idempotency_key: str,
        state: JobState,
        dry_run: bool,
        content_id: str | None = None,
    ) -> SubmissionJobRecord:
        existing = self.find_job_by_idempotency(idempotency_key)
        if existing:
            return existing
        now = _now()
        job = SubmissionJobRecord(
            job_id=f"job-{uuid.uuid4().hex[:12]}",
            event_id=event_id,
            platform_id=platform_id,
            idempotency_key=idempotency_key,
            state=state,
            dry_run=dry_run,
            content_id=content_id,
        )
        self.db.execute(
            """
            INSERT INTO submission_jobs(
              job_id, event_id, platform_id, idempotency_key, state, dry_run,
              content_id, published_url, error_details, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                job.job_id,
                job.event_id,
                job.platform_id,
                job.idempotency_key,
                job.state.value,
                1 if dry_run else 0,
                content_id,
                now,
                now,
            ),
        )
        self.audit("system", "create_job", "submission_job", job.job_id, {"state": job.state.value})
        return job

    def transition_job(
        self,
        job_id: str,
        new_state: JobState,
        *,
        error_details: str | None = None,
        published_url: str | None = None,
    ) -> SubmissionJobRecord:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Unknown job_id: {job_id}")
        allowed = ALLOWED_TRANSITIONS.get(job.state, set())
        if new_state != job.state and new_state not in allowed:
            raise ValueError(f"Illegal transition {job.state.value} -> {new_state.value}")
        self.db.execute(
            """
            UPDATE submission_jobs
            SET state = ?, error_details = COALESCE(?, error_details),
                published_url = COALESCE(?, published_url), updated_at = ?
            WHERE job_id = ?
            """,
            (new_state.value, error_details, published_url, _now(), job_id),
        )
        self.audit(
            "system",
            "transition_job",
            "submission_job",
            job_id,
            {"from": job.state.value, "to": new_state.value},
        )
        updated = self.get_job(job_id)
        assert updated is not None
        return updated

    def get_job(self, job_id: str) -> SubmissionJobRecord | None:
        row = self.db.fetchone("SELECT * FROM submission_jobs WHERE job_id = ?", (job_id,))
        return self._row_to_job(row) if row else None

    def list_jobs(
        self, *, event_id: str | None = None, platform_id: str | None = None
    ) -> list[SubmissionJobRecord]:
        sql = "SELECT * FROM submission_jobs WHERE 1=1"
        params: list[Any] = []
        if event_id:
            sql += " AND event_id = ?"
            params.append(event_id)
        if platform_id:
            sql += " AND platform_id = ?"
            params.append(platform_id)
        sql += " ORDER BY created_at DESC"
        return [self._row_to_job(r) for r in self.db.fetchall(sql, params)]  # type: ignore[arg-type]

    def add_attempt(
        self,
        job_id: str,
        *,
        attempt_number: int,
        status: JobState,
        dry_run: bool,
        adapter_name: str,
        message: str,
        response_summary: dict[str, Any] | None = None,
        error_code: str | None = None,
        evidence_paths: list[str] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO submission_attempts(
              job_id, attempt_number, status, dry_run, adapter_name, message,
              response_summary_json, error_code, evidence_paths_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                attempt_number,
                status.value,
                1 if dry_run else 0,
                adapter_name,
                message,
                json.dumps(redact_mapping(response_summary or {})),
                error_code,
                json.dumps(evidence_paths or []),
                _now(),
            ),
        )

    def next_attempt_number(self, job_id: str) -> int:
        row = self.db.fetchone(
            "SELECT COALESCE(MAX(attempt_number), 0) AS m FROM submission_attempts WHERE job_id = ?",
            (job_id,),
        )
        return int(row["m"]) + 1 if row else 1

    def save_published_listing(
        self, *, event_id: str, platform_id: str, job_id: str, published_url: str
    ) -> str:
        listing_id = f"lst-{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """
            INSERT INTO published_listings(
              listing_id, event_id, platform_id, job_id, published_url, verified, created_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (listing_id, event_id, platform_id, job_id, published_url, _now()),
        )
        return listing_id

    def save_backlink_check(self, payload: dict[str, Any]) -> str:
        check_id = payload.get("check_id") or f"blk-{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """
            INSERT INTO backlink_checks(
              check_id, event_id, listing_id, published_url, landing_page_url,
              http_status, redirect_chain_json, link_found, anchor_text, rel_attributes,
              result, details, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                check_id,
                payload["event_id"],
                payload.get("listing_id"),
                payload["published_url"],
                payload["landing_page_url"],
                payload.get("http_status"),
                json.dumps(payload.get("redirect_chain") or []),
                1 if payload.get("link_found") else 0 if payload.get("link_found") is not None else None,
                payload.get("anchor_text"),
                payload.get("rel_attributes"),
                payload["result"],
                payload.get("details"),
                payload.get("checked_at") or _now(),
            ),
        )
        return check_id

    def list_backlink_checks(self, event_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM backlink_checks WHERE event_id = ? ORDER BY checked_at DESC",
            (event_id,),
        )
        return [dict(r) for r in rows]

    def audit(
        self,
        actor: str,
        action: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO audit_logs(actor, action, entity_type, entity_id, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(redact_mapping(details or {})),
                _now(),
            ),
        )

    def save_publishing_rule_evaluation(
        self,
        *,
        platform_id: str,
        dry_run: bool,
        authorize_publication: bool,
        allowed: bool,
        eligible_for_live: bool,
        result: dict[str, Any],
        event_id: str | None = None,
    ) -> str:
        evaluation_id = str(uuid.uuid4())
        self.db.execute(
            """
            INSERT INTO publishing_rule_evaluations(
              evaluation_id, event_id, platform_id, dry_run, authorize_publication,
              allowed, eligible_for_live, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                event_id,
                platform_id,
                int(dry_run),
                int(authorize_publication),
                int(allowed),
                int(eligible_for_live),
                json.dumps(redact_mapping(result)),
                _now(),
            ),
        )
        return evaluation_id

    def save_registry_snapshot(
        self, *, version: str, totals: dict[str, Any], validation: dict[str, Any]
    ) -> str:
        snapshot_id = str(uuid.uuid4())
        self.db.execute(
            """
            INSERT INTO registry_snapshots(snapshot_id, version, totals_json, validation_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                version,
                json.dumps(totals),
                json.dumps(validation),
                _now(),
            ),
        )
        return snapshot_id

    def list_registry_entries(self) -> list[PlatformRecord]:
        """Submit targets: workflows + platforms except LinkedIn parent."""
        return [
            p
            for p in self.list_platforms()
            if p.is_workflow or p.platform_id != "linkedin"
        ]

    def list_workflows(self, parent_platform_id: str | None = None) -> list[PlatformRecord]:
        workflows = [p for p in self.list_platforms() if p.is_workflow]
        if parent_platform_id:
            workflows = [w for w in workflows if w.parent_platform_id == parent_platform_id]
        return workflows

    def list_distinct_platforms(self) -> list[PlatformRecord]:
        return [p for p in self.list_platforms() if not p.is_workflow]

    @staticmethod
    def _row_to_job(row: Any) -> SubmissionJobRecord:
        return SubmissionJobRecord(
            job_id=row["job_id"],
            event_id=row["event_id"],
            platform_id=row["platform_id"],
            idempotency_key=row["idempotency_key"],
            state=JobState(row["state"]),
            dry_run=bool(row["dry_run"]),
            content_id=row["content_id"],
            published_url=row["published_url"],
            error_details=row["error_details"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def make_idempotency_key(event_id: str, platform_id: str, content_type: str | None = None) -> str:
        base = f"{event_id}::{platform_id}"
        if content_type:
            base = f"{base}::{content_type}"
        return base
