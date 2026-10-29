"""Official Google Sheets API client.

Uses a service-account credential and the Sheets v4 REST API. Secret material
is never logged. Callers must drop password cells before returning tool output.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from event_seo_mcp.settings import Settings

logger = logging.getLogger(__name__)

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


class SheetsError(RuntimeError):
    """Base error for Sheets operations. Messages must not contain secrets."""

    code = "sheets_error"


class SheetsNotConfigured(SheetsError):
    code = "sheets_not_configured"


class SheetsTimeoutError(SheetsError):
    code = "sheets_timeout"


class SheetsApiError(SheetsError):
    code = "sheets_api_error"

    def __init__(self, status_code: int, operation: str) -> None:
        super().__init__(f"Google Sheets API {operation} failed with HTTP {status_code}")
        self.status_code = status_code
        self.operation = operation


class SheetsGateway(Protocol):
    def get_values(self, range_name: str) -> list[list[str]]: ...

    def update_row(self, range_name: str, row: list[str]) -> None: ...

    def append_row(self, range_name: str, row: list[str]) -> str: ...


def quote_sheet(tab: str) -> str:
    escaped = tab.replace("'", "''")
    return f"'{escaped}'"


def credentials_range(tab: str) -> str:
    return f"{quote_sheet(tab)}!A:F"


def submissions_range(tab: str) -> str:
    return f"{quote_sheet(tab)}!A:G"


def row_range(tab: str, row_number: int) -> str:
    return f"{quote_sheet(tab)}!A{row_number}:G{row_number}"


class GoogleSheetsApiClient:
    """Sheets v4 values API authenticated as a Google service account."""

    def __init__(self, settings: Settings) -> None:
        spreadsheet_id = (settings.google_sheets_spreadsheet_id or "").strip()
        if not spreadsheet_id:
            raise SheetsNotConfigured(
                "GOOGLE_SHEETS_SPREADSHEET_ID is not set. Share the spreadsheet with "
                "the service account and set the spreadsheet id."
            )
        self.spreadsheet_id = spreadsheet_id
        self.timeout = float(settings.google_sheets_timeout_seconds or 20.0)
        self._info = _load_service_account_info(settings)

    def get_values(self, range_name: str) -> list[list[str]]:
        payload = self._request("GET", range_name, operation="read")
        raw_rows = payload.get("values") or []
        return [[str(cell) for cell in row] for row in raw_rows]

    def update_row(self, range_name: str, row: list[str]) -> None:
        self._request(
            "PUT",
            range_name,
            operation="update",
            params={"valueInputOption": "USER_ENTERED"},
            json_body={"range": range_name, "majorDimension": "ROWS", "values": [row]},
        )

    def append_row(self, range_name: str, row: list[str]) -> str:
        payload = self._request(
            "POST",
            range_name,
            operation="append",
            method_suffix=":append",
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json_body={"majorDimension": "ROWS", "values": [row]},
        )
        updates = payload.get("updates") or {}
        updated = str(updates.get("updatedRange") or "")
        if not updated:
            raise SheetsApiError(502, "append")
        return updated

    def _request(
        self,
        method: str,
        range_name: str,
        *,
        operation: str,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        method_suffix: str = "",
    ) -> dict[str, Any]:
        token = _access_token(self._info)
        url = (
            f"{SHEETS_BASE}/{quote(self.spreadsheet_id, safe='')}/values/"
            f"{quote(range_name, safe='')}{method_suffix}"
        )
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        logger.info("sheets_api operation=%s method=%s", operation, method)
        try:
            response = httpx.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise SheetsTimeoutError(f"Google Sheets API {operation} timed out") from exc
        except httpx.HTTPError as exc:
            raise SheetsApiError(0, operation) from exc
        if response.status_code >= 400:
            raise SheetsApiError(response.status_code, operation)
        if not response.content:
            return {}
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise SheetsApiError(response.status_code, operation) from exc
        if not isinstance(body, dict):
            raise SheetsApiError(response.status_code, operation)
        return body


def _load_service_account_info(settings: Settings) -> dict[str, Any]:
    raw = settings.google_sheets_credentials_json
    if raw:
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SheetsNotConfigured(
                "GOOGLE_SHEETS_CREDENTIALS_JSON is not valid JSON"
            ) from exc
    else:
        path = (settings.google_application_credentials or "").strip()
        if not path:
            raise SheetsNotConfigured(
                "Set GOOGLE_SHEETS_CREDENTIALS_JSON or GOOGLE_APPLICATION_CREDENTIALS "
                "to a Google service-account key. Do not commit the key."
            )
        try:
            info = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise SheetsNotConfigured(
                "Service-account credential file could not be read"
            ) from exc
        except json.JSONDecodeError as exc:
            raise SheetsNotConfigured(
                "Service-account credential file is not valid JSON"
            ) from exc
    if not isinstance(info, dict) or not info.get("client_email") or not info.get("private_key"):
        raise SheetsNotConfigured(
            "Service-account credentials are missing client_email or private_key"
        )
    return info


class _HttpxAuthResponse:
    """Response shape expected by google.auth.transport.Request."""

    def __init__(self, response: httpx.Response) -> None:
        self.status = response.status_code
        self.headers = {key.lower(): value for key, value in response.headers.items()}
        self.data = response.content


class _HttpxAuthRequest:
    """google-auth refresh transport that uses the already-installed httpx client."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        del kwargs
        response = httpx.request(
            method,
            url,
            content=body,
            headers=headers,
            timeout=timeout or 20.0,
        )
        return _HttpxAuthResponse(response)


def _access_token(info: dict[str, Any]) -> str:
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise SheetsNotConfigured(
            "google-auth is not installed. Install the project dependencies and retry."
        ) from exc
    credentials = service_account.Credentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
    credentials.refresh(_HttpxAuthRequest())
    token = credentials.token
    if not token:
        raise SheetsNotConfigured("Google service-account token was empty")
    return str(token)
