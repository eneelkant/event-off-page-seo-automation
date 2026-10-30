"""Google Sheets submission tracking with a mocked Sheets API."""

from __future__ import annotations

import json
import re

import pytest
from starlette.testclient import TestClient

from event_seo_mcp.database.connection import Database
from event_seo_mcp.integrations.google_sheets.client import (
    SheetsApiError,
    SheetsNotConfigured,
    SheetsTimeoutError,
)
from event_seo_mcp.integrations.google_sheets.service import classify_password, valid_http_url
from event_seo_mcp.server import build_http_app, create_server
from event_seo_mcp.settings import Settings, reset_settings_cache
from event_seo_mcp.tools.handlers import ToolService

CREDENTIALS = [
    ["Site Category", "Site Name", "Website", "Username", "Password", "Page Rank"],
    [
        "event_directory",
        "Eventbrite",
        "https://www.eventbrite.com",
        "hidden-user@example.com",
        "env:EVENTBRITE_API_TOKEN",
        "5",
    ],
    [
        "event_directory",
        "10Times",
        "https://10times.com",
        "directory-editor",
        "super-secret-password",
        "4",
    ],
    ["guest_posting", "Unknown Blog", "https://example.com/submit", "", "", "1"],
]

SUBMISSIONS = [[
    "Site Category",
    "Submission Date",
    "Submission Status",
    "Published Date",
    "Site Name",
    "Website",
    "Published URL",
]]

SECRET = "super-secret-password"
USERNAME = "hidden-user@example.com"


class FakeSheets:
    def __init__(self) -> None:
        self.credentials = [list(row) for row in CREDENTIALS]
        self.submissions = [list(row) for row in SUBMISSIONS]
        self.append_calls = 0
        self.reads = 0
        self.writes = 0
        self.timeout_once = False
        self.timeout_keeps_row = False
        self.fail_configured = False
        self.api_error = False

    def get_values(self, range_name: str) -> list[list[str]]:
        self.reads += 1
        if self.fail_configured:
            raise SheetsNotConfigured("GOOGLE_SHEETS_SPREADSHEET_ID is not set")
        if range_name.endswith("!A:F"):
            return [list(row) for row in self.credentials]
        row_match = re.search(r"!A(\d+):G\d+", range_name)
        if row_match:
            number = int(row_match.group(1))
            if 1 <= number <= len(self.submissions):
                return [list(self.submissions[number - 1])]
            return []
        return [list(row) for row in self.submissions]

    def update_row(self, range_name: str, row: list[str]) -> None:
        self.writes += 1
        number = int(re.search(r"!A(\d+)", range_name).group(1))
        while len(self.submissions) < number:
            self.submissions.append([""] * 7)
        self.submissions[number - 1] = list(row)

    def append_row(self, range_name: str, row: list[str]) -> str:
        self.append_calls += 1
        self.writes += 1
        if self.api_error:
            raise SheetsApiError(500, "append")
        if self.timeout_once:
            self.timeout_once = False
            if self.timeout_keeps_row:
                self.submissions.append(list(row))
            raise SheetsTimeoutError("Google Sheets API append timed out")
        self.submissions.append(list(row))
        number = len(self.submissions)
        return f"'Submissions'!A{number}:G{number}"


def _dump(payload: object) -> str:
    return json.dumps(payload)


def _block_adapter(service: ToolService) -> dict[str, int]:
    calls = {"count": 0}

    def _boom(*_args, **_kwargs):
        calls["count"] += 1
        raise AssertionError("publication adapter must not run")

    service.sheets._dispatch_authorized_api = _boom  # type: ignore[method-assign]
    return calls


def _submission_json(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "event_name": "Builders Summit",
        "event_description": "A fictional event used only in tests.",
        "landing_page_url": "https://example.com/events/builders",
        "event_datetime": "2027-06-15T09:00:00Z",
        "target_site": "https://10times.com",
        "registration_url": "https://example.com/events/builders/register",
        "location": "San Francisco",
        "event_id": "evt-regression-1",
        "dry_run": True,
    }
    body.update(overrides)
    return body


def _http_app(settings: Settings, service: ToolService, token: str | None):
    settings.mcp_auth_token = token
    database = Database(settings.resolved_database_path)
    mcp, _ = create_server(settings, database=database)
    return build_http_app(mcp, settings, service)


def _submit(service: ToolService, **overrides: object) -> dict:
    payload = {
        "event_name": "Builders Summit",
        "event_description": "A fictional event used only in tests.",
        "landing_page_url": "https://example.com/events/builders",
        "event_datetime": "2027-06-15T09:00:00+00:00",
        "target_site": "https://10times.com",
        "registration_url": "https://example.com/events/builders/register",
        "location": "San Francisco",
        "event_id": "evt-sheets-1",
    }
    payload.update(overrides)
    return service.submit_event_to_site(**payload)  # type: ignore[arg-type]


@pytest.fixture()
def sheets_service(service: ToolService) -> tuple[ToolService, FakeSheets]:
    fake = FakeSheets()
    service.sheets._client = fake
    return service, fake


def test_auth_transport_uses_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    from event_seo_mcp.integrations.google_sheets.client import _HttpxAuthRequest

    captured: dict[str, object] = {}

    class _Response:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        content = b"{}"

    def _request(method, url, content=None, headers=None, timeout=None):
        captured["method"] = method
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(
        "event_seo_mcp.integrations.google_sheets.client.httpx.request",
        _request,
    )
    response = _HttpxAuthRequest()(
        "https://oauth2.googleapis.com/token",
        method="POST",
        body=b"grant_type=jwt-bearer",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    assert response.status == 200
    assert response.data == b"{}"
    assert response.headers["content-type"] == "application/json"
    assert captured["method"] == "POST"
    assert "oauth2.googleapis.com" in str(captured["url"])


def test_password_classifier_never_returns_secret() -> None:
    assert classify_password("") == "missing"
    assert classify_password("env:EVENTBRITE_API_TOKEN") == "secret_reference"
    assert classify_password("secret:site-10times") == "secret_reference"
    assert classify_password("projects/p/secrets/site/versions/1") == "secret_reference"
    assert classify_password(SECRET) == "legacy_cell"
    assert valid_http_url("javascript:alert(1)") is None
    assert valid_http_url("https://user:pass@example.com/a") is None
    assert valid_http_url("https://example.com/live") == "https://example.com/live"


def test_list_targets_hides_passwords_and_usernames(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, _fake = sheets_service
    result = service.list_submission_targets()
    text = _dump(result)
    assert SECRET not in text
    assert USERNAME not in text
    assert "directory-editor" not in text
    assert result["passwords_exposed"] is False
    by_name = {row["site_name"]: row for row in result["targets"]}
    assert by_name["Eventbrite"]["credential_storage"] == "secret_reference"
    assert by_name["Eventbrite"]["submission_method"] == "api_preferred"
    assert by_name["Eventbrite"]["password_returned"] is False
    assert by_name["10Times"]["credential_storage"] == "legacy_cell"
    assert by_name["10Times"]["readiness"] == "MANUAL_ACTION_REQUIRED"
    assert by_name["10Times"]["eligibility"] == "manual_only"
    assert by_name["Unknown Blog"]["credential_storage"] == "missing"
    assert by_name["Unknown Blog"]["platform_id"] is None


def test_missing_sheet_credentials(service: ToolService) -> None:
    result = service.list_submission_targets()
    assert result["error"] == "sheets_not_configured"
    assert "password" not in result["message"].lower()


def test_dry_run_is_default_and_does_not_publish(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, fake = sheets_service
    called = {"live": 0}

    def _boom(*_args, **_kwargs):
        called["live"] += 1
        raise AssertionError("dry-run must not dispatch a live adapter")

    service.sheets._dispatch_authorized_api = _boom  # type: ignore[method-assign]
    result = _submit(service)
    assert result["status"] == "DRY_RUN"
    assert result["dry_run"] is True
    assert result["published"] is False
    assert result["sheet_row"] == 2
    assert called["live"] == 0
    assert fake.append_calls == 1
    assert fake.submissions[1][2] == "DRY_RUN"
    assert fake.submissions[1][3] == ""
    assert fake.submissions[1][6] == ""
    assert SECRET not in _dump(result)


def test_string_false_dry_run_is_not_live(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, fake = sheets_service
    result = _submit(service, dry_run="false", authorize_publication="false")
    assert result["status"] == "AWAITING_APPROVAL"
    assert result["published"] is False
    assert fake.submissions[1][2] == "AWAITING_APPROVAL"
    assert fake.submissions[1][6] == ""


def test_invalid_url_does_not_write_a_tracking_row(
    sheets_service: tuple[ToolService, FakeSheets],
) -> None:
    service, fake = sheets_service
    result = _submit(service, landing_page_url="notaurl")
    assert result["error"] == "validation_error"
    assert "landing_page_url" in result["message"]
    assert result["published"] is False
    assert result["tracked"] is False
    assert result["sheet_row"] is None
    assert "status" not in result
    assert fake.append_calls == 0
    assert len(fake.submissions) == 1


def test_dry_run_with_virtual_details_records_one_row(
    sheets_service: tuple[ToolService, FakeSheets],
) -> None:
    service, fake = sheets_service
    called = {"live": 0}

    def _boom(*_args, **_kwargs):
        called["live"] += 1
        raise AssertionError("dry-run must not dispatch a live adapter")

    service.sheets._dispatch_authorized_api = _boom  # type: ignore[method-assign]
    result = _submit(
        service,
        location="",
        virtual_event_details="Zoom room 12",
        event_id="evt-virtual-1",
    )
    assert result["status"] == "DRY_RUN"
    assert result["dry_run"] is True
    assert result["published"] is False
    assert result["sheet_row"] == 2
    assert called["live"] == 0
    assert fake.append_calls == 1
    assert fake.submissions[1][2] == "DRY_RUN"
    assert fake.submissions[1][3] == ""
    assert fake.submissions[1][6] == ""


def test_missing_required_fields_do_not_write(
    sheets_service: tuple[ToolService, FakeSheets],
) -> None:
    service, fake = sheets_service
    result = _submit(
        service,
        event_name=" ",
        event_description="",
        landing_page_url="",
        event_datetime="",
        target_site="",
        registration_url="",
        location=None,
        virtual_event_details=None,
    )
    message = result["message"]
    assert result["error"] == "validation_error"
    assert result["tracked"] is False
    assert result["sheet_row"] is None
    assert result["published"] is False
    for field in (
        "event_name is required",
        "event_description is required",
        "landing_page_url must be an http or https URL",
        "event_datetime must be an ISO-8601 date and time",
        "registration_url must be an http or https URL",
        "location or virtual_event_details is required",
        "target_site is required",
    ):
        assert field in message
    assert fake.append_calls == 0
    assert len(fake.submissions) == 1


def test_missing_location_and_virtual_details_do_not_write(
    sheets_service: tuple[ToolService, FakeSheets],
) -> None:
    service, fake = sheets_service
    result = _submit(service, location=None, virtual_event_details="  ", event_id="evt-api-dry-run-test")
    assert result["error"] == "validation_error"
    assert result["message"] == "location or virtual_event_details is required"
    assert result["event_id"] == "evt-api-dry-run-test"
    assert result["dry_run"] is True
    assert result["published"] is False
    assert result["tracked"] is False
    assert result["sheet_row"] is None
    assert "status" not in result
    assert fake.append_calls == 0
    assert len(fake.submissions) == 1
    again = _submit(service, event_id="evt-api-dry-run-test")
    assert again["status"] == "DRY_RUN"
    assert again["sheet_row"] == 2
    assert fake.append_calls == 1
    assert len(fake.submissions) == 2


def test_invalid_datetime_does_not_write(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, fake = sheets_service
    result = _submit(service, event_datetime="15/06/2027")
    assert result["error"] == "validation_error"
    assert "event_datetime" in result["message"]
    assert result["tracked"] is False
    assert result["sheet_row"] is None
    assert fake.append_calls == 0


def test_sheets_api_failure_is_not_a_successful_submission(
    sheets_service: tuple[ToolService, FakeSheets],
) -> None:
    service, fake = sheets_service
    fake.api_error = True
    result = _submit(service, event_id="evt-api-down")
    assert result["error"] == "sheets_api_error"
    assert result.get("published") is not True
    assert result.get("status") != "DRY_RUN"
    assert result.get("sheet_row") is None
    assert fake.append_calls == 1
    assert len(fake.submissions) == 1


def test_duplicate_submit_updates_same_row(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, fake = sheets_service
    first = _submit(service)
    second = _submit(service)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["sheet_row"] == first["sheet_row"]
    assert fake.append_calls == 1
    assert len(fake.submissions) == 2


def test_manual_site_does_not_claim_success(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, fake = sheets_service
    result = _submit(service, dry_run=False, authorize_publication=True)
    text = _dump(result)
    assert result["status"] == "MANUAL_ACTION_REQUIRED"
    assert result["published"] is False
    assert "manual_instructions" in result
    assert SECRET not in text
    assert "directory-editor" not in text
    assert fake.submissions[1][2] == "MANUAL_ACTION_REQUIRED"
    assert fake.submissions[1][3] == ""
    assert fake.submissions[1][6] == ""


def test_authorized_api_without_live_url_stays_submitted(
    sheets_service: tuple[ToolService, FakeSheets],
) -> None:
    service, fake = sheets_service

    def _submitted(event, platform):
        assert platform.platform_id == "eventbrite"
        return {
            "duplicate": False,
            "job": {"job_id": "job-1", "state": "SUBMITTED", "published_url": None, "dry_run": False},
            "message": "Draft created. The site did not return a public URL.",
        }

    service.sheets._dispatch_authorized_api = _submitted  # type: ignore[method-assign]
    result = _submit(
        service,
        target_site="Eventbrite",
        dry_run=False,
        authorize_publication=True,
        event_id="evt-eb-1",
    )
    assert result["status"] == "SUBMITTED"
    assert result["published"] is False
    assert result["published_url"] is None
    assert fake.submissions[1][2] == "SUBMITTED"
    assert fake.submissions[1][6] == ""


def test_rejected_submission(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, fake = sheets_service

    def _rejected(_event, _platform):
        return {"refused": True, "message": "Site rejected the listing"}

    service.sheets._dispatch_authorized_api = _rejected  # type: ignore[method-assign]
    result = _submit(
        service,
        target_site="https://www.eventbrite.com/organizer",
        dry_run=False,
        authorize_publication=True,
    )
    assert result["status"] == "REJECTED"
    assert result["published"] is False
    assert fake.submissions[1][2] == "REJECTED"


def test_append_timeout_retries_without_a_second_row(
    sheets_service: tuple[ToolService, FakeSheets],
) -> None:
    service, fake = sheets_service
    fake.timeout_once = True
    fake.timeout_keeps_row = True
    first = _submit(service)
    assert first["error"] == "sheets_timeout"
    assert len(fake.submissions) == 2
    second = _submit(service)
    assert second["status"] == "DRY_RUN"
    assert second["duplicate"] is True
    assert fake.append_calls == 1
    assert len(fake.submissions) == 2
    assert fake.submissions[1][2] == "DRY_RUN"


def test_publication_update_requires_live_url(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, fake = sheets_service
    _submit(service)
    denied = service.record_publication_update(
        event_id="evt-sheets-1",
        site_name="10Times",
        publication_status="PUBLISHED",
        published_url="",
        published_date="2027-06-20",
    )
    assert denied["error"] == "validation_error"
    assert "live" in denied["message"].lower() or "http" in denied["message"].lower()
    assert fake.submissions[1][2] == "DRY_RUN"
    assert fake.submissions[1][6] == ""

    missing = service.record_publication_update(
        event_id="evt-does-not-exist",
        website="https://10times.com",
        publication_status="PUBLISHED",
        published_url="https://10times.com/events/builders",
        published_date="2027-06-20",
    )
    assert missing["error"] == "submission_not_found"
    assert fake.submissions[1][2] == "DRY_RUN"

    updated = service.record_publication_update(
        event_id="evt-sheets-1",
        website="https://10times.com/listing",
        publication_status="published",
        published_url="https://10times.com/events/builders",
        published_date="2027-06-20T15:00:00Z",
        external_submission_id="ext-9",
    )
    assert updated["updated"] is True
    assert updated["status"] == "PUBLISHED"
    assert fake.submissions[1][2] == "PUBLISHED"
    assert fake.submissions[1][3] == "2027-06-20"
    assert fake.submissions[1][6] == "https://10times.com/events/builders"

    again = service.record_publication_update(
        event_id="evt-sheets-1",
        site_name="10Times",
        publication_status="PUBLISHED",
        published_url="https://10times.com/events/builders",
        published_date="2027-06-20",
    )
    assert again["idempotent"] is True
    assert again["updated"] is False
    assert len(fake.submissions) == 2


def test_publication_update_does_not_touch_another_event(
    sheets_service: tuple[ToolService, FakeSheets],
) -> None:
    service, fake = sheets_service
    _submit(service, event_id="evt-a")
    _submit(service, event_id="evt-b", target_site="https://www.eventbrite.com")
    result = service.record_publication_update(
        event_id="evt-b",
        site_name="10Times",
        publication_status="PUBLISHED",
        published_url="https://10times.com/wrong",
        published_date="2027-06-21",
    )
    assert result["error"] == "submission_not_found"
    assert fake.submissions[1][2] == "DRY_RUN"
    assert fake.submissions[1][6] == ""
    assert fake.submissions[2][4] == "Eventbrite"
    assert fake.submissions[2][6] == ""


def test_ambiguous_publication_match(sheets_service: tuple[ToolService, FakeSheets]) -> None:
    service, _fake = sheets_service
    service.sheets._save_link(
        event_id="evt-amb",
        site_key="host:a.example",
        sheet_row=2,
        status="DRY_RUN",
        website="https://a.example",
        site_name="Same",
        append_uncertain=False,
        external_submission_id=None,
        published_url=None,
    )
    service.sheets._save_link(
        event_id="evt-amb",
        site_key="host:b.example",
        sheet_row=3,
        status="DRY_RUN",
        website="https://b.example",
        site_name="Same",
        append_uncertain=False,
        external_submission_id=None,
        published_url=None,
    )
    result = service.record_publication_update(
        event_id="evt-amb",
        site_name="Same",
        publication_status="PUBLISHED",
        published_url="https://a.example/live",
        published_date="2027-06-22",
    )
    assert result["error"] == "ambiguous_match"


def test_blank_optional_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_FALLBACK_PROVIDER", "")
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "  ")
    reset_settings_cache()
    settings = Settings(_env_file=None, ai_provider="template")
    assert settings.ai_fallback_provider is None
    assert settings.google_sheets_credentials_json is None


def test_http_bridge_requires_auth_and_updates(
    settings: Settings, repo, sheets_service: tuple[ToolService, FakeSheets]
) -> None:
    service, fake = sheets_service
    settings.mcp_auth_token = "bridge-token"
    db = Database(settings.resolved_database_path)
    mcp, _ = create_server(settings, database=db)
    # Reuse the fixture service so the fake sheet and synced registry stay together.
    app = build_http_app(mcp, settings, service)

    with TestClient(app) as client:
        open_call = client.get("/api/submission-targets")
        assert open_call.status_code == 401

        denied = client.get(
            "/api/submission-targets",
            headers={"Authorization": "Bearer wrong"},
        )
        assert denied.status_code == 401

        ok = client.get(
            "/api/submission-targets",
            headers={"Authorization": "Bearer bridge-token"},
        )
        assert ok.status_code == 200
        assert SECRET not in ok.text

        created = client.post(
            "/api/submissions",
            headers={"Authorization": "Bearer bridge-token"},
            json={
                "event_name": "Bridge Summit",
                "event_description": "Submitted through the HTTP bridge.",
                "landing_page_url": "https://example.com/bridge",
                "event_datetime": "2027-08-01T10:00:00Z",
                "target_site": "https://10times.com",
                "registration_url": "https://example.com/bridge/register",
                "location": "Online hall",
                "event_id": "evt-bridge",
            },
        )
        assert created.status_code == 200
        body = created.json()
        assert body["status"] == "DRY_RUN"
        assert body["dry_run"] is True
        assert body["sheet_row"] == 2
        assert body["published"] is False

        unauthenticated = client.post(
            "/api/submissions",
            json={
                "event_name": "Should Not Track",
                "event_description": "No token was sent.",
                "landing_page_url": "https://example.com/no-auth",
                "event_datetime": "2027-08-01T10:00:00Z",
                "target_site": "https://10times.com",
                "registration_url": "https://example.com/no-auth/register",
                "location": "Hall",
            },
        )
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["error"] == "unauthorized"

        invalid = client.post(
            "/api/submissions",
            headers={"Authorization": "Bearer bridge-token"},
            json={
                "event_name": "Missing Place",
                "event_description": "No location or virtual details.",
                "landing_page_url": "https://example.com/missing-place",
                "event_datetime": "not-a-date",
                "target_site": "https://10times.com",
                "registration_url": "notaurl",
                "event_id": "evt-invalid-http",
            },
        )
        assert invalid.status_code == 400
        invalid_body = invalid.json()
        assert invalid_body["error"] == "validation_error"
        assert invalid_body["tracked"] is False
        assert invalid_body["sheet_row"] is None
        assert "location or virtual_event_details is required" in invalid_body["message"]
        assert "event_datetime" in invalid_body["message"]
        assert "registration_url" in invalid_body["message"]
        assert fake.append_calls == 1
        assert len(fake.submissions) == 2
        assert fake.submissions[1][2] == "DRY_RUN"

        bad = client.post(
            "/api/publication-updates",
            headers={"Authorization": "Bearer bridge-token"},
            json={
                "event_id": "evt-bridge",
                "site_name": "10Times",
                "publication_status": "PUBLISHED",
            },
        )
        assert bad.status_code == 400

        published = client.post(
            "/api/publication-updates",
            headers={"Authorization": "Bearer bridge-token"},
            json={
                "event_id": "evt-bridge",
                "website": "https://10times.com",
                "publication_status": "PUBLISHED",
                "published_url": "https://10times.com/e/bridge",
                "published_date": "2027-08-02",
            },
        )
        assert published.status_code == 200
        assert published.json()["status"] == "PUBLISHED"


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        (
            {"location": None, "virtual_event_details": "  ", "event_id": "evt-no-place"},
            "location or virtual_event_details is required",
        ),
        (
            {"landing_page_url": "notaurl", "event_id": "evt-bad-landing"},
            "landing_page_url must be an http or https URL",
        ),
        (
            {"registration_url": "javascript:alert(1)", "event_id": "evt-bad-registration"},
            "registration_url must be an http or https URL",
        ),
        (
            {"event_datetime": "15/06/2027", "event_id": "evt-bad-when"},
            "event_datetime must be an ISO-8601 date and time",
        ),
    ],
)
def test_invalid_submission_does_not_access_sheets(
    settings: Settings,
    sheets_service: tuple[ToolService, FakeSheets],
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    service, fake = sheets_service
    calls = _block_adapter(service)
    app = _http_app(settings, service, "bridge-token")
    with TestClient(app) as client:
        response = client.post(
            "/api/submissions",
            headers={"Authorization": "Bearer bridge-token"},
            json=_submission_json(**overrides),
        )
    body = response.json()
    assert response.status_code == 400
    assert body["error"] == "validation_error"
    assert expected_message in body["message"]
    assert body["tracked"] is False
    assert body["sheet_row"] is None
    assert body["published"] is False
    assert "status" not in body
    assert fake.reads == 0
    assert fake.writes == 0
    assert fake.append_calls == 0
    assert len(fake.submissions) == 1
    assert calls["count"] == 0


def test_missing_required_fields_do_not_access_sheets(
    settings: Settings, sheets_service: tuple[ToolService, FakeSheets]
) -> None:
    service, fake = sheets_service
    calls = _block_adapter(service)
    app = _http_app(settings, service, "bridge-token")
    with TestClient(app) as client:
        response = client.post(
            "/api/submissions",
            headers={"Authorization": "Bearer bridge-token"},
            json={
                "event_name": " ",
                "event_description": "",
                "landing_page_url": "",
                "event_datetime": "",
                "target_site": "",
                "registration_url": "",
                "dry_run": True,
                "authorize_publication": True,
                "event_id": "evt-missing-fields",
            },
        )
    body = response.json()
    assert response.status_code == 400
    assert body["error"] == "validation_error"
    assert body["tracked"] is False
    assert body["sheet_row"] is None
    for field in (
        "event_name is required",
        "event_description is required",
        "landing_page_url must be an http or https URL",
        "event_datetime must be an ISO-8601 date and time",
        "registration_url must be an http or https URL",
        "location or virtual_event_details is required",
        "target_site is required",
    ):
        assert field in body["message"]
    assert fake.reads == 0
    assert fake.writes == 0
    assert calls["count"] == 0
    assert len(fake.submissions) == 1


@pytest.mark.parametrize(
    ("event_id", "extra"),
    [
        ("evt-dry-location", {"location": "San Francisco"}),
        ("evt-dry-virtual", {"virtual_event_details": "Zoom room 12"}),
    ],
)
def test_dry_run_with_authorization_still_does_not_publish(
    settings: Settings,
    sheets_service: tuple[ToolService, FakeSheets],
    event_id: str,
    extra: dict[str, str],
) -> None:
    service, fake = sheets_service
    calls = _block_adapter(service)
    app = _http_app(settings, service, "bridge-token")
    payload = _submission_json(event_id=event_id, dry_run=True, authorize_publication=True)
    payload.pop("location", None)
    payload.update(extra)
    with TestClient(app) as client:
        response = client.post(
            "/api/submissions",
            headers={"Authorization": "Bearer bridge-token"},
            json=payload,
        )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "DRY_RUN"
    assert body["dry_run"] is True
    assert body["published"] is False
    assert body["sheet_row"] == 2
    assert fake.append_calls == 1
    assert fake.writes == 1
    assert len(fake.submissions) == 2
    assert fake.submissions[1][2] == "DRY_RUN"
    assert fake.submissions[1][3] == ""
    assert fake.submissions[1][6] == ""
    assert calls["count"] == 0


@pytest.mark.parametrize(
    ("headers", "status_code", "error"),
    [
        ({}, 401, "unauthorized"),
        ({"Authorization": "Bearer wrong-token"}, 401, "unauthorized"),
    ],
)
def test_auth_failure_does_not_access_sheets(
    settings: Settings,
    sheets_service: tuple[ToolService, FakeSheets],
    headers: dict[str, str],
    status_code: int,
    error: str,
) -> None:
    service, fake = sheets_service
    calls = _block_adapter(service)
    app = _http_app(settings, service, "bridge-token")
    with TestClient(app) as client:
        response = client.post("/api/submissions", headers=headers, json=_submission_json())
    assert response.status_code == status_code
    assert response.json()["error"] == error
    assert fake.reads == 0
    assert fake.writes == 0
    assert calls["count"] == 0
    assert len(fake.submissions) == 1


def test_http_bridge_without_token_is_unavailable(settings: Settings, tmp_path) -> None:
    settings.mcp_auth_token = None
    db = Database(tmp_path / "bridge.db")
    mcp, service = create_server(settings, database=db)
    app = build_http_app(mcp, settings, service)
    with TestClient(app) as client:
        response = client.get("/api/submission-targets")
        assert response.status_code == 503
        assert response.json()["error"] == "auth_not_configured"
