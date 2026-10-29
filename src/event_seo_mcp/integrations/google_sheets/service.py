"""Sheet-backed submission targets, tracking, and publication updates.

Passwords from the credentials tab are classified and discarded. They are never
returned to MCP clients, written to the Submissions tab, or sent to adapters.
Live publication goes through an existing official API adapter only. Every
other site stays manual. Dry-run is the default and does not call the site.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from event_seo_mcp.database.repository import Repository
from event_seo_mcp.integrations.google_sheets.client import (
    GoogleSheetsApiClient,
    SheetsApiError,
    SheetsError,
    SheetsGateway,
    SheetsNotConfigured,
    SheetsTimeoutError,
    credentials_range,
    row_range,
    submissions_range,
)
from event_seo_mcp.orchestration.orchestrator import Orchestrator
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.settings import Settings

logger = logging.getLogger(__name__)

SHEET_STATUSES = {
    "PENDING",
    "DRY_RUN",
    "SUBMITTED",
    "AWAITING_APPROVAL",
    "PUBLISHED",
    "REJECTED",
    "FAILED",
    "MANUAL_ACTION_REQUIRED",
}
CREDENTIAL_HEADERS = [
    "site category",
    "site name",
    "website",
    "username",
    "password",
    "page rank",
]
SUBMISSION_HEADERS = [
    "site category",
    "submission date",
    "submission status",
    "published date",
    "site name",
    "website",
    "published url",
]
# Only this adapter confirms creation against a documented official API.
AUTOMATED_API_ADAPTERS = {"eventbrite"}


class SheetsWorkflow:
    def __init__(
        self,
        repo: Repository,
        settings: Settings,
        orchestrator: Orchestrator,
        client: SheetsGateway | None = None,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.orchestrator = orchestrator
        self._client = client

    def list_targets(self) -> dict[str, Any]:
        try:
            rows = self._gateway().get_values(credentials_range(self._credentials_tab()))
        except SheetsError as exc:
            return _error(exc)
        header_error = _header_error(rows, CREDENTIAL_HEADERS, self._credentials_tab())
        if header_error:
            return header_error
        targets = []
        for offset, raw in enumerate(rows[1:], start=2):
            target = self._target_from_row(raw, sheet_row=offset)
            if target is not None:
                targets.append(target)
        logger.info("sheets_targets count=%s", len(targets))
        return {"count": len(targets), "targets": targets, "passwords_exposed": False}

    def submit_event_to_site(
        self,
        *,
        event_name: str,
        event_description: str,
        landing_page_url: str,
        event_datetime: str,
        target_site: str,
        registration_url: str,
        location: str | None = None,
        virtual_event_details: str | None = None,
        dry_run: bool | None = True,
        authorize_publication: bool = False,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        dry_run = _as_bool(dry_run, True)
        authorize_publication = _as_bool(authorize_publication, False) and not dry_run

        problems = _validate_event_fields(
            event_name=event_name,
            event_description=event_description,
            landing_page_url=landing_page_url,
            event_datetime=event_datetime,
            registration_url=registration_url,
            location=location,
            virtual_event_details=virtual_event_details,
            target_site=target_site,
        )
        landing = valid_http_url(landing_page_url) or ""
        registration = valid_http_url(registration_url) or ""
        when = _parse_datetime(event_datetime)
        identifier = make_event_id(event_id, event_name, landing or landing_page_url)

        try:
            target = self._resolve_target(target_site)
        except SheetsError as exc:
            return _error(exc)

        if target is None:
            return {
                "error": "target_not_found",
                "message": "No row in Site Login Credentials matches that site name or website.",
                "event_id": identifier,
            }
        if isinstance(target, dict) and target.get("error"):
            return target

        if problems or when is None:
            message = "; ".join(problems or ["event_datetime must be an ISO-8601 date and time"])
            tracked = self._write_tracking(
                event_id=identifier,
                target=target,
                status="FAILED",
                published_url=None,
                published_date=None,
            )
            if tracked.get("error"):
                tracked["event_id"] = identifier
                return tracked
            return {
                "error": "validation_error",
                "message": message,
                "event_id": identifier,
                "status": "FAILED",
                "dry_run": dry_run,
                "published": False,
                "sheet_row": tracked.get("sheet_row"),
            }

        if dry_run:
            tracked = self._write_tracking(
                event_id=identifier,
                target=target,
                status="DRY_RUN",
                published_url=None,
                published_date=None,
            )
            if tracked.get("error"):
                tracked["event_id"] = identifier
                return tracked
            return {
                "event_id": identifier,
                "status": "DRY_RUN",
                "dry_run": True,
                "published": False,
                "duplicate": tracked.get("duplicate", False),
                "site_name": target["site_name"],
                "website": target["website"],
                "submission_method": target["submission_method"],
                "message": (
                    "Dry-run recorded. No site was contacted and nothing was published. "
                    "Set dry_run=false and authorize_publication=true only for an authorized API."
                ),
                "manual_instructions": _manual_instructions(target) if not target["api_supported"] else [],
                "sheet_row": tracked.get("sheet_row"),
            }

        if not authorize_publication:
            tracked = self._write_tracking(
                event_id=identifier,
                target=target,
                status="AWAITING_APPROVAL",
                published_url=None,
                published_date=None,
            )
            if tracked.get("error"):
                tracked["event_id"] = identifier
                return tracked
            return {
                "event_id": identifier,
                "status": "AWAITING_APPROVAL",
                "dry_run": False,
                "published": False,
                "duplicate": tracked.get("duplicate", False),
                "message": "Live submission requires authorize_publication=true. Nothing was published.",
                "sheet_row": tracked.get("sheet_row"),
            }

        if not target["api_supported"]:
            tracked = self._write_tracking(
                event_id=identifier,
                target=target,
                status="MANUAL_ACTION_REQUIRED",
                published_url=None,
                published_date=None,
            )
            if tracked.get("error"):
                tracked["event_id"] = identifier
                return tracked
            return {
                "event_id": identifier,
                "status": "MANUAL_ACTION_REQUIRED",
                "dry_run": False,
                "published": False,
                "duplicate": tracked.get("duplicate", False),
                "submission_method": target["submission_method"],
                "message": (
                    "This site has no confirmed official submission API. "
                    "Submit it manually. Automated login with sheet credentials is not performed."
                ),
                "manual_instructions": _manual_instructions(target),
                "sheet_row": tracked.get("sheet_row"),
            }

        platform = self.repo.get_platform(target["platform_id"])
        if platform is None:
            tracked = self._write_tracking(
                event_id=identifier,
                target=target,
                status="MANUAL_ACTION_REQUIRED",
                published_url=None,
                published_date=None,
            )
            if tracked.get("error"):
                tracked["event_id"] = identifier
                return tracked
            return {
                "event_id": identifier,
                "status": "MANUAL_ACTION_REQUIRED",
                "dry_run": False,
                "published": False,
                "message": "Matched platform is not in the local registry.",
                "manual_instructions": _manual_instructions(target),
                "sheet_row": tracked.get("sheet_row"),
            }

        event = _event_record(
            event_id=identifier,
            event_name=event_name.strip(),
            event_description=event_description.strip(),
            landing_page_url=landing,
            registration_url=registration,
            start=when,
            location=location,
            virtual_event_details=virtual_event_details,
        )
        outcome = self._dispatch_authorized_api(event, platform)
        status, published_url, message = _status_from_dispatch(outcome)
        published_date = _today() if status == "PUBLISHED" else None
        tracked = self._write_tracking(
            event_id=identifier,
            target=target,
            status=status,
            published_url=published_url,
            published_date=published_date,
            external_submission_id=_external_id(outcome),
        )
        if tracked.get("error"):
            tracked["event_id"] = identifier
            tracked["status"] = status
            return tracked
        return {
            "event_id": identifier,
            "status": status,
            "dry_run": False,
            "published": status == "PUBLISHED",
            "published_url": published_url,
            "duplicate": tracked.get("duplicate", False) or bool(outcome.get("duplicate")),
            "message": message,
            "sheet_row": tracked.get("sheet_row"),
            "platform_id": platform.platform_id,
        }

    def record_publication_update(
        self,
        *,
        event_id: str,
        publication_status: str,
        site_name: str | None = None,
        website: str | None = None,
        published_url: str | None = None,
        published_date: str | None = None,
        external_submission_id: str | None = None,
    ) -> dict[str, Any]:
        identifier = (event_id or "").strip()
        if not identifier:
            return {"error": "validation_error", "message": "event_id is required"}
        status = (publication_status or "").strip().upper()
        if status not in SHEET_STATUSES:
            return {
                "error": "validation_error",
                "message": f"publication_status must be one of: {', '.join(sorted(SHEET_STATUSES))}",
            }
        if not (site_name or "").strip() and not (website or "").strip():
            return {
                "error": "validation_error",
                "message": "site_name or website is required to find the submission row",
            }

        confirmed_url: str | None = None
        confirmed_date: str | None = None
        if status == "PUBLISHED":
            confirmed_url = valid_http_url(published_url or "")
            if not confirmed_url:
                return {
                    "error": "validation_error",
                    "message": (
                        "A live http or https URL is required before a submission can be marked "
                        "PUBLISHED. An approval email alone is not publication evidence."
                    ),
                }
            confirmed_date = _normalize_date(published_date)
            if not confirmed_date:
                return {
                    "error": "validation_error",
                    "message": "published_date is required when marking a submission PUBLISHED",
                }

        link = self._find_link(identifier, site_name=site_name, website=website)
        if link is None:
            return {
                "error": "submission_not_found",
                "message": "No tracked submission matches that event and site. No row was updated.",
                "event_id": identifier,
            }
        if link.get("ambiguous"):
            return {
                "error": "ambiguous_match",
                "message": "More than one submission matches that site. Pass the website used at submit time.",
                "event_id": identifier,
            }

        current_url = (link.get("published_url") or "").strip()
        if status == "PUBLISHED" and link["status"] == "PUBLISHED" and current_url == confirmed_url:
            return {
                "event_id": identifier,
                "status": "PUBLISHED",
                "updated": False,
                "idempotent": True,
                "published_url": current_url,
                "sheet_row": link.get("sheet_row"),
                "message": "Submission is already published at this URL.",
            }

        target = {
            "site_category": "",
            "site_name": link["site_name"],
            "website": link["website"],
        }
        try:
            tracked = self._update_existing_row(
                event_id=identifier,
                site_key=link["site_key"],
                sheet_row=int(link["sheet_row"]),
                status=status,
                published_url=confirmed_url,
                published_date=confirmed_date,
                external_submission_id=external_submission_id,
                target=target,
            )
        except SheetsError as exc:
            return _error(exc)
        return {
            "event_id": identifier,
            "status": status,
            "updated": True,
            "idempotent": False,
            "published": status == "PUBLISHED",
            "published_url": confirmed_url,
            "published_date": confirmed_date,
            "sheet_row": tracked.get("sheet_row"),
            "external_submission_id": external_submission_id,
        }

    def _dispatch_authorized_api(self, event: EventRecord, platform: PlatformRecord) -> dict[str, Any]:
        content_type = (
            platform.supported_content_types[0]
            if platform.supported_content_types
            else "event_directory_description"
        )
        content = self.orchestrator.generate_content(event, platform, content_type)  # type: ignore[arg-type]
        return self.orchestrator.submit_event(
            event,
            platform,
            content,
            dry_run=False,
            authorize_publication=True,
        )

    def _gateway(self) -> SheetsGateway:
        if self._client is not None:
            return self._client
        return GoogleSheetsApiClient(self.settings)

    def _credentials_tab(self) -> str:
        return self.settings.google_sheets_credentials_tab or "Site Login Credentials"

    def _submissions_tab(self) -> str:
        return self.settings.google_sheets_submissions_tab or "Submissions"

    def _resolve_target(self, target_site: str) -> dict[str, Any] | None:
        rows = self._gateway().get_values(credentials_range(self._credentials_tab()))
        header_error = _header_error(rows, CREDENTIAL_HEADERS, self._credentials_tab())
        if header_error:
            return header_error
        needle_name = _norm(target_site)
        needle_host = _host(target_site)
        matches: list[dict[str, Any]] = []
        for offset, raw in enumerate(rows[1:], start=2):
            target = self._target_from_row(raw, sheet_row=offset)
            if target is None:
                continue
            if needle_host and needle_host == _host(target["website"]):
                matches.append(target)
            elif needle_name and needle_name == _norm(target["site_name"]):
                matches.append(target)
        if not matches:
            return None
        if len(matches) > 1:
            return {
                "error": "ambiguous_match",
                "message": "Target site matches more than one credentials row. Use the website URL.",
            }
        return matches[0]

    def _target_from_row(self, raw: list[str], *, sheet_row: int) -> dict[str, Any] | None:
        cells = _pad(raw, 6)
        category, site_name, website = cells[0].strip(), cells[1].strip(), cells[2].strip()
        username, password, page_rank = cells[3].strip(), cells[4].strip(), cells[5].strip()
        if not any((category, site_name, website)):
            return None
        storage = classify_password(password)
        # Drop the secret immediately. Username is also withheld from tool output.
        del password, username
        platform = self._match_platform(site_name, website)
        method = platform.submission_method if platform else "manual"
        api_supported = bool(
            platform
            and platform.adapter_name in AUTOMATED_API_ADAPTERS
            and platform.submission_method == "api_preferred"
            and not platform.is_workflow
        )
        website_ok = bool(valid_http_url(website))
        if not website_ok:
            readiness = "MISSING_WEBSITE"
            eligibility = "ineligible"
        elif api_supported and platform and platform.automation_status == "READY":
            readiness = "API_READY"
            eligibility = "authorized_api"
        elif api_supported:
            readiness = "DRY_RUN_READY"
            eligibility = "api_needs_explicit_authorization"
        else:
            readiness = "MANUAL_ACTION_REQUIRED"
            eligibility = "manual_only"
        return {
            "sheet_row": sheet_row,
            "site_category": category,
            "site_name": site_name,
            "website": website,
            "page_rank": page_rank or None,
            "eligibility": eligibility,
            "submission_method": method,
            "readiness": readiness,
            "credential_storage": storage,
            "password_returned": False,
            "platform_id": platform.platform_id if platform else None,
            "api_supported": api_supported,
            "automation_status": platform.automation_status if platform else None,
        }

    def _match_platform(self, site_name: str, website: str) -> PlatformRecord | None:
        host = _host(website)
        name = _norm(site_name)
        candidates = [p for p in self.repo.list_platforms() if not p.is_workflow]
        for platform in candidates:
            if host and host == _host(str(platform.official_homepage or "")):
                return platform
        for platform in candidates:
            if name and name == _norm(platform.platform_name):
                return platform
        return None

    def _write_tracking(
        self,
        *,
        event_id: str,
        target: dict[str, Any],
        status: str,
        published_url: str | None,
        published_date: str | None,
        external_submission_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return self._commit_tracking(
                event_id=event_id,
                target=target,
                status=status,
                published_url=published_url,
                published_date=published_date,
                external_submission_id=external_submission_id,
            )
        except SheetsError as exc:
            return _error(exc)

    def _commit_tracking(
        self,
        *,
        event_id: str,
        target: dict[str, Any],
        status: str,
        published_url: str | None,
        published_date: str | None,
        external_submission_id: str | None = None,
    ) -> dict[str, Any]:
        site_key = _site_key(target["website"], target["site_name"])
        existing = self._get_link(event_id, site_key)
        if existing and existing["sheet_row"]:
            return self._update_existing_row(
                event_id=event_id,
                site_key=site_key,
                sheet_row=int(existing["sheet_row"]),
                status=status,
                published_url=published_url if status == "PUBLISHED" else None,
                published_date=published_date if status == "PUBLISHED" else None,
                external_submission_id=external_submission_id,
                target=target,
                duplicate=True,
            )
        if existing and existing["append_uncertain"]:
            adopted = self._adopt_unclaimed_row(event_id, site_key, target)
            if adopted is not None:
                return self._update_existing_row(
                    event_id=event_id,
                    site_key=site_key,
                    sheet_row=adopted,
                    status=status,
                    published_url=published_url if status == "PUBLISHED" else None,
                    published_date=published_date if status == "PUBLISHED" else None,
                    external_submission_id=external_submission_id,
                    target=target,
                    duplicate=True,
                )
        row = _submission_row(
            target,
            status=status,
            published_url=published_url if status == "PUBLISHED" else None,
            published_date=published_date if status == "PUBLISHED" else None,
        )
        header_problem = self._ensure_submission_headers()
        if header_problem:
            return header_problem
        try:
            updated_range = self._gateway().append_row(submissions_range(self._submissions_tab()), row)
        except SheetsTimeoutError:
            self._save_link(
                event_id=event_id,
                site_key=site_key,
                sheet_row=None,
                status="PENDING",
                website=target["website"],
                site_name=target["site_name"],
                append_uncertain=True,
                external_submission_id=external_submission_id,
                published_url=None,
            )
            raise
        sheet_row = _row_number(updated_range)
        self._save_link(
            event_id=event_id,
            site_key=site_key,
            sheet_row=sheet_row,
            status=status,
            website=target["website"],
            site_name=target["site_name"],
            append_uncertain=False,
            external_submission_id=external_submission_id,
            published_url=published_url if status == "PUBLISHED" else None,
        )
        return {"sheet_row": sheet_row, "duplicate": False, "status": status}

    def _update_existing_row(
        self,
        *,
        event_id: str,
        site_key: str,
        sheet_row: int,
        status: str,
        published_url: str | None,
        published_date: str | None,
        external_submission_id: str | None,
        target: dict[str, Any],
        duplicate: bool = False,
    ) -> dict[str, Any]:
        current = self._read_submission_row(sheet_row)
        category = current[0] or target.get("site_category") or ""
        submission_date = current[1] or _today()
        site_name = current[4] or target.get("site_name") or ""
        website = current[5] or target.get("website") or ""
        row = [
            category,
            submission_date,
            status,
            published_date or "",
            site_name,
            website,
            published_url or "",
        ]
        if status != "PUBLISHED":
            row[3] = ""
            row[6] = ""
        self._gateway().update_row(row_range(self._submissions_tab(), sheet_row), row)
        self._save_link(
            event_id=event_id,
            site_key=site_key,
            sheet_row=sheet_row,
            status=status,
            website=website,
            site_name=site_name,
            append_uncertain=False,
            external_submission_id=external_submission_id,
            published_url=published_url if status == "PUBLISHED" else None,
        )
        return {"sheet_row": sheet_row, "duplicate": duplicate, "status": status}

    def _adopt_unclaimed_row(self, event_id: str, site_key: str, target: dict[str, Any]) -> int | None:
        claimed = {
            int(row["sheet_row"])
            for row in self._all_links()
            if row["sheet_row"] and not (row["event_id"] == event_id and row["site_key"] == site_key)
        }
        values = self._gateway().get_values(submissions_range(self._submissions_tab()))
        host = _host(target["website"])
        name = _norm(target["site_name"])
        found: list[int] = []
        for offset, raw in enumerate(values[1:], start=2):
            if offset in claimed:
                continue
            cells = _pad(raw, 7)
            if _host(cells[5]) == host or _norm(cells[4]) == name:
                found.append(offset)
        if len(found) == 1:
            return found[0]
        return None

    def _ensure_submission_headers(self) -> dict[str, Any] | None:
        tab = self._submissions_tab()
        values = self._gateway().get_values(submissions_range(tab))
        if not values:
            self._gateway().update_row(
                row_range(tab, 1),
                [
                    "Site Category",
                    "Submission Date",
                    "Submission Status",
                    "Published Date",
                    "Site Name",
                    "Website",
                    "Published URL",
                ],
            )
            return None
        return _header_error(values, SUBMISSION_HEADERS, tab)

    def _read_submission_row(self, sheet_row: int) -> list[str]:
        values = self._gateway().get_values(row_range(self._submissions_tab(), sheet_row))
        if not values:
            return _pad([], 7)
        return _pad(values[0], 7)

    def _find_link(
        self, event_id: str, *, site_name: str | None, website: str | None
    ) -> dict[str, Any] | None:
        rows = [row for row in self._all_links() if row["event_id"] == event_id]
        if website and valid_http_url(website):
            host = _host(website)
            rows = [row for row in rows if _host(row["website"]) == host]
        elif website:
            rows = [row for row in rows if _norm(row["website"]) == _norm(website)]
        if website and not rows:
            return None
        if site_name:
            rows = [row for row in rows if _norm(row["site_name"]) == _norm(site_name)]
        if not rows:
            return None
        if len(rows) > 1:
            return {"ambiguous": True}
        row = rows[0]
        if not row["sheet_row"]:
            return None
        return row

    def _get_link(self, event_id: str, site_key: str) -> dict[str, Any] | None:
        row = self.repo.db.fetchone(
            """
            SELECT event_id, site_key, sheet_row, status, website, site_name,
                   append_uncertain, external_submission_id, published_url
            FROM sheet_submission_links
            WHERE event_id = ? AND site_key = ?
            """,
            (event_id, site_key),
        )
        return dict(row) if row else None

    def _all_links(self) -> list[dict[str, Any]]:
        rows = self.repo.db.fetchall(
            """
            SELECT event_id, site_key, sheet_row, status, website, site_name,
                   append_uncertain, external_submission_id, published_url
            FROM sheet_submission_links
            """
        )
        return [dict(row) for row in rows]

    def _save_link(
        self,
        *,
        event_id: str,
        site_key: str,
        sheet_row: int | None,
        status: str,
        website: str,
        site_name: str,
        append_uncertain: bool,
        external_submission_id: str | None,
        published_url: str | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.repo.db.execute(
            """
            INSERT INTO sheet_submission_links(
                event_id, site_key, sheet_row, status, website, site_name,
                append_uncertain, external_submission_id, published_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, site_key) DO UPDATE SET
                sheet_row = excluded.sheet_row,
                status = excluded.status,
                website = excluded.website,
                site_name = excluded.site_name,
                append_uncertain = excluded.append_uncertain,
                external_submission_id = excluded.external_submission_id,
                published_url = excluded.published_url,
                updated_at = excluded.updated_at
            """,
            (
                event_id,
                site_key,
                sheet_row,
                status,
                website,
                site_name,
                1 if append_uncertain else 0,
                external_submission_id,
                published_url,
                now,
            ),
        )


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no", ""}:
            return False
    return default


def classify_password(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "missing"
    lowered = text.lower()
    if lowered.startswith(("secret:", "env:", "sm://")) or text.startswith("projects/"):
        return "secret_reference"
    return "legacy_cell"


def valid_http_url(value: str) -> str | None:
    text = (value or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    return text


def make_event_id(event_id: str | None, event_name: str, landing_page_url: str) -> str:
    explicit = (event_id or "").strip()
    if explicit:
        return explicit[:128]
    slug = re.sub(r"[^a-z0-9]+", "-", (event_name or "").lower()).strip("-")[:48] or "event"
    digest = hashlib.sha256((landing_page_url or "").encode("utf-8")).hexdigest()[:8]
    return f"evt-{slug}-{digest}"


def _validate_event_fields(
    *,
    event_name: str,
    event_description: str,
    landing_page_url: str,
    event_datetime: str,
    registration_url: str,
    location: str | None,
    virtual_event_details: str | None,
    target_site: str,
) -> list[str]:
    problems: list[str] = []
    if not (event_name or "").strip():
        problems.append("event_name is required")
    if not (event_description or "").strip():
        problems.append("event_description is required")
    if not valid_http_url(landing_page_url):
        problems.append("landing_page_url must be an http or https URL")
    if _parse_datetime(event_datetime) is None:
        problems.append("event_datetime must be an ISO-8601 date and time")
    if not valid_http_url(registration_url):
        problems.append("registration_url must be an http or https URL")
    if not (location or "").strip() and not (virtual_event_details or "").strip():
        problems.append("location or virtual_event_details is required")
    if not (target_site or "").strip():
        problems.append("target_site is required")
    return problems


def _parse_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _normalize_date(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    parsed = _parse_datetime(text)
    if parsed is not None:
        return parsed.date().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    return None


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _event_record(
    *,
    event_id: str,
    event_name: str,
    event_description: str,
    landing_page_url: str,
    registration_url: str,
    start: datetime,
    location: str | None,
    virtual_event_details: str | None,
) -> EventRecord:
    virtual = bool((virtual_event_details or "").strip()) and not (location or "").strip()
    return EventRecord(
        event_id=event_id,
        event_title=event_name,
        event_description=event_description,
        landing_page_url=landing_page_url,  # type: ignore[arg-type]
        start_datetime=start,
        timezone="UTC",
        event_type="event",
        target_audience=event_name,
        primary_keywords=[event_name],
        registration_url=registration_url,  # type: ignore[arg-type]
        organizer_name="Event organizer",
        venue_name=(location or "").strip() or None,
        virtual_event=virtual,
    )


def _manual_instructions(target: dict[str, Any]) -> list[str]:
    storage = target.get("credential_storage")
    if storage == "secret_reference":
        credential_note = "Use the secret-manager reference stored in the sheet. The secret value is not loaded here."
    elif storage == "legacy_cell":
        credential_note = (
            "A legacy password cell exists and was not returned. Move it to a secret manager "
            "and replace the cell with env:NAME or secret:NAME."
        )
    else:
        credential_note = "No site password is stored in the sheet."
    return [
        f"Open {target.get('website') or 'the site'} and sign in yourself.",
        credential_note,
        "Do not automate login. This server does not bypass CAPTCHA, MFA, or access controls.",
        "Submit the event name, description, landing page, date and time, location or virtual details, and registration URL through the site's own form.",
        "After the listing is live, call record_publication_update with the live https URL.",
    ]


def _submission_row(
    target: dict[str, Any],
    *,
    status: str,
    published_url: str | None,
    published_date: str | None,
) -> list[str]:
    published = status == "PUBLISHED"
    return [
        target.get("site_category") or "",
        _today(),
        status,
        published_date if published and published_date else "",
        target.get("site_name") or "",
        target.get("website") or "",
        published_url if published and published_url else "",
    ]


def _status_from_dispatch(outcome: dict[str, Any]) -> tuple[str, str | None, str]:
    if outcome.get("error"):
        return "FAILED", None, str(outcome.get("message") or outcome["error"])
    if outcome.get("refused"):
        message = str(outcome.get("message") or "Live submission refused")
        lowered = message.lower()
        if "authorize_publication" in lowered:
            return "AWAITING_APPROVAL", None, message
        if "credential" in lowered or "verification" in lowered or "blocked" in lowered:
            return "MANUAL_ACTION_REQUIRED", None, message
        return "REJECTED", None, message
    job = outcome.get("job") or {}
    state = str(job.get("state") or "")
    url = valid_http_url(str(job.get("published_url") or ""))
    attempt = outcome.get("attempt") or {}
    message = str(outcome.get("message") or attempt.get("message") or state or "Submission finished")
    if state == "PUBLISHED" and url:
        return "PUBLISHED", url, message
    if state == "PUBLISHED" and not url:
        return "SUBMITTED", None, "Creation was reported without a live URL, so the row is SUBMITTED."
    if state in {"SUBMITTED", "PENDING_REVIEW"}:
        return "SUBMITTED", None, message
    if state == "REJECTED":
        return "REJECTED", None, message
    if state == "FAILED":
        return "FAILED", None, message
    if state == "AWAITING_APPROVAL":
        return "AWAITING_APPROVAL", None, message
    if state in {"BLOCKED", "NEEDS_VERIFICATION"}:
        return "MANUAL_ACTION_REQUIRED", None, message
    return "FAILED", None, message or "The site did not confirm creation or publication."


def _external_id(outcome: dict[str, Any]) -> str | None:
    job = outcome.get("job") or {}
    value = job.get("job_id")
    return str(value) if value else None


def _header_error(rows: list[list[str]], expected: list[str], tab: str) -> dict[str, Any] | None:
    if not rows:
        return {
            "error": "validation_error",
            "message": f"Tab {tab} is empty. Add the header row before reading it.",
        }
    actual = [_norm(cell) for cell in _pad(rows[0], len(expected))[: len(expected)]]
    if actual != expected:
        return {
            "error": "validation_error",
            "message": f"Tab {tab} headers do not match the expected column order.",
        }
    return None


def _error(exc: SheetsError) -> dict[str, Any]:
    return {"error": exc.code, "message": str(exc)}


def _pad(row: list[str], width: int) -> list[str]:
    cells = [str(cell) for cell in row]
    if len(cells) < width:
        cells.extend([""] * (width - len(cells)))
    return cells


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _host(value: str) -> str:
    parsed = urlsplit((value or "").strip())
    host = parsed.netloc or parsed.path
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split("/")[0].split(":")[0]


def _site_key(website: str, site_name: str) -> str:
    host = _host(website)
    if host:
        return f"host:{host}"
    return f"name:{_norm(site_name)}"


def _row_number(updated_range: str) -> int:
    match = re.search(r"(\d+)", updated_range.split(":")[0])
    if not match:
        raise SheetsApiError(502, "append")
    return int(match.group(1))
