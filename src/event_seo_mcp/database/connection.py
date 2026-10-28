"""SQLite connection and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platforms (
    platform_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    automation_status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_content (
    content_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    platform_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(event_id)
);

CREATE TABLE IF NOT EXISTS submission_jobs (
    job_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    platform_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 1,
    content_id TEXT,
    published_url TEXT,
    error_details TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submission_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    adapter_name TEXT NOT NULL,
    message TEXT NOT NULL,
    response_summary_json TEXT,
    error_code TEXT,
    evidence_paths_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES submission_jobs(job_id)
);

CREATE TABLE IF NOT EXISTS published_listings (
    listing_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    platform_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    published_url TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backlink_checks (
    check_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    listing_id TEXT,
    published_url TEXT NOT NULL,
    landing_page_url TEXT NOT NULL,
    http_status INTEGER,
    redirect_chain_json TEXT,
    link_found INTEGER,
    anchor_text TEXT,
    rel_attributes TEXT,
    result TEXT NOT NULL,
    details TEXT,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_event ON submission_jobs(event_id);
CREATE INDEX IF NOT EXISTS idx_jobs_platform ON submission_jobs(platform_id);
CREATE INDEX IF NOT EXISTS idx_content_event ON generated_content(event_id);
CREATE INDEX IF NOT EXISTS idx_backlinks_event ON backlink_checks(event_id);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            with self.connect() as conn:
                conn.executescript(SCHEMA_SQL)
                conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            with self.connect() as conn:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur

    def executemany(self, sql: str, seq: list[tuple]) -> None:
        with self._lock:
            with self.connect() as conn:
                conn.executemany(sql, seq)
                conn.commit()

    def fetchone(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self._lock:
            with self.connect() as conn:
                return conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            with self.connect() as conn:
                return list(conn.execute(sql, params).fetchall())


_db: Database | None = None


def get_database(path: Path | None = None) -> Database:
    global _db
    if _db is None:
        if path is None:
            from event_seo_mcp.settings import get_settings

            path = get_settings().resolved_database_path
        _db = Database(path)
    return _db


def reset_database_singleton() -> None:
    global _db
    _db = None
