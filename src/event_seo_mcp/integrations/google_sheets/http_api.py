"""Authenticated HTTP bridge for Gemini and other non-MCP callers.

Gemini workflows should call these routes. They are not a substitute for an
MCP connector, and they always require MCP_AUTH_TOKEN.
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from event_seo_mcp.security.redaction import redact_mapping
from event_seo_mcp.settings import Settings
from event_seo_mcp.tools.handlers import ToolService

logger = logging.getLogger(__name__)


def register_sheets_http(mcp: Any, service: ToolService, settings: Settings) -> None:
    @mcp.custom_route("/api/submission-targets", methods=["GET"])
    async def list_submission_targets(request: Request) -> JSONResponse:
        denied = _authorize(request, settings)
        if denied is not None:
            return denied
        return _json(service.list_submission_targets())

    @mcp.custom_route("/api/submissions", methods=["POST"])
    async def submit_event_to_site(request: Request) -> JSONResponse:
        denied = _authorize(request, settings)
        if denied is not None:
            return denied
        payload, error = await _json_body(request)
        if error is not None:
            return error
        result = service.submit_event_to_site(
            event_name=str(payload.get("event_name") or ""),
            event_description=str(payload.get("event_description") or ""),
            landing_page_url=str(payload.get("landing_page_url") or ""),
            event_datetime=str(payload.get("event_datetime") or ""),
            target_site=str(payload.get("target_site") or ""),
            registration_url=str(payload.get("registration_url") or ""),
            location=_optional_str(payload.get("location")),
            virtual_event_details=_optional_str(payload.get("virtual_event_details")),
            dry_run=payload.get("dry_run", True),
            authorize_publication=bool(payload.get("authorize_publication", False)),
            event_id=_optional_str(payload.get("event_id")),
        )
        return _json(result)

    @mcp.custom_route("/api/publication-updates", methods=["POST"])
    async def record_publication_update(request: Request) -> JSONResponse:
        denied = _authorize(request, settings)
        if denied is not None:
            return denied
        payload, error = await _json_body(request)
        if error is not None:
            return error
        result = service.record_publication_update(
            event_id=str(payload.get("event_id") or ""),
            publication_status=str(payload.get("publication_status") or ""),
            site_name=_optional_str(payload.get("site_name")),
            website=_optional_str(payload.get("website")),
            published_url=_optional_str(payload.get("published_url")),
            published_date=_optional_str(payload.get("published_date")),
            external_submission_id=_optional_str(payload.get("external_submission_id")),
        )
        return _json(result)


def _authorize(request: Request, settings: Settings) -> JSONResponse | None:
    expected = (settings.mcp_auth_token or "").strip()
    if not expected:
        return JSONResponse(
            {
                "error": "auth_not_configured",
                "message": "Set MCP_AUTH_TOKEN. The Gemini HTTP bridge rejects unauthenticated calls.",
            },
            status_code=503,
        )
    header = request.headers.get("authorization") or ""
    provided = ""
    if header.lower().startswith("bearer "):
        provided = header[7:].strip()
    elif request.headers.get("x-api-key"):
        provided = (request.headers.get("x-api-key") or "").strip()
    if not provided or provided != expected:
        logger.info("sheets_http unauthorized path=%s", request.url.path)
        return JSONResponse(
            {"error": "unauthorized", "message": "Valid Bearer token required"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return None


async def _json_body(request: Request) -> tuple[dict[str, Any], JSONResponse | None]:
    try:
        payload = await request.json()
    except Exception:
        return {}, JSONResponse(
            {"error": "validation_error", "message": "Request body must be JSON"},
            status_code=400,
        )
    if not isinstance(payload, dict):
        return {}, JSONResponse(
            {"error": "validation_error", "message": "Request body must be a JSON object"},
            status_code=400,
        )
    return payload, None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json(result: dict[str, Any]) -> JSONResponse:
    safe = redact_mapping(result)
    status = _status_code(safe if isinstance(safe, dict) else result)
    return JSONResponse(safe, status_code=status)


def _status_code(result: dict[str, Any]) -> int:
    error = result.get("error")
    if error in {"sheets_not_configured", "auth_not_configured"}:
        return 503
    if error == "sheets_timeout":
        return 504
    if error in {"submission_not_found", "target_not_found"}:
        return 404
    if error == "ambiguous_match":
        return 409
    if error in {"validation_error", "sheets_api_error", "sheets_error"}:
        return 400
    return 200
