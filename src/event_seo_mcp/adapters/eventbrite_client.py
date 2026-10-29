"""Eventbrite API v3 client — endpoints verified against official docs only.

Sources (2026-10-29 review):
- https://www.eventbrite.com/platform/api
- https://www.eventbrite.com/platform/docs/authentication
- https://www.eventbrite.com/platform/docs/create-events
- https://www.eventbrite.com/platform/docs/organizations
- https://www.eventbrite.com/platform/docs/events

Auth: Authorization: Bearer <private_token> (account private token from API Keys).
There is no separate documented public sandbox host; requests use the production
API base. Do not invent alternate hosts or scopes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from event_seo_mcp.security.redaction import redact_mapping, redact_secrets

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://www.eventbriteapi.com/v3"

# Documented create-event required fields (name.html, start/end tz+utc, currency).
CREATE_EVENT_REQUIRED_KEYS = (
    "name",
    "start",
    "end",
    "currency",
)


@dataclass
class EventbriteApiError(Exception):
    """HTTP or payload error from Eventbrite without leaking secrets."""

    message: str
    status_code: int | None = None
    error_code: str | None = None
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return redact_secrets(self.message)


class EventbriteClient:
    """Thin httpx wrapper for verified Eventbrite v3 paths."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_API_BASE,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not token or not str(token).strip():
            raise ValueError("Eventbrite API token is required")
        self._token = str(token).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client
        self._owns_client = client is None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        self._client = httpx.Client(timeout=self.timeout_seconds)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> EventbriteClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        # Log method + path only — never Authorization or token material.
        logger.info("Eventbrite API %s %s", method.upper(), path)
        try:
            response = self._get_client().request(
                method.upper(),
                url,
                headers=self._headers(),
                json=json_body,
            )
        except httpx.HTTPError as exc:
            safe = redact_secrets(str(exc))
            logger.error("Eventbrite transport error on %s %s: %s", method.upper(), path, safe)
            raise EventbriteApiError(
                message=f"Eventbrite transport error: {safe}",
                error_code="TRANSPORT_ERROR",
            ) from exc

        payload: dict[str, Any] | list[Any] | None
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {"raw_text": redact_secrets(response.text[:500])}

        if response.status_code >= 400:
            details = redact_mapping(payload) if isinstance(payload, dict) else {"body": payload}
            err_code = None
            err_msg = f"Eventbrite HTTP {response.status_code} on {method.upper()} {path}"
            if isinstance(payload, dict):
                err_code = payload.get("error_description") or payload.get("error") or payload.get(
                    "status_code"
                )
                if isinstance(err_code, (dict, list)):
                    err_code = str(err_code)
                desc = payload.get("error_description") or payload.get("error") or payload.get(
                    "error_message"
                )
                if desc:
                    err_msg = f"{err_msg}: {redact_secrets(str(desc))}"
            logger.error(err_msg)
            raise EventbriteApiError(
                message=err_msg,
                status_code=response.status_code,
                error_code=str(err_code) if err_code else f"HTTP_{response.status_code}",
                details=details if isinstance(details, dict) else {"body": details},
            )

        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    def list_organizations(self) -> dict[str, Any]:
        """GET /v3/users/me/organizations/ — resolve org IDs for the token owner."""
        return self._request("GET", "/users/me/organizations/")

    def create_event(self, organization_id: str, event_payload: dict[str, Any]) -> dict[str, Any]:
        """POST /v3/organizations/{organization_id}/events/

        ``event_payload`` must include documented required fields under key ``event``.
        """
        if "event" not in event_payload:
            raise ValueError("create_event requires an 'event' object wrapper")
        event_obj = event_payload["event"]
        missing = [k for k in CREATE_EVENT_REQUIRED_KEYS if k not in event_obj]
        if missing:
            raise ValueError(f"Eventbrite create-event missing required keys: {', '.join(missing)}")
        name = event_obj.get("name") or {}
        if not isinstance(name, dict) or not str(name.get("html") or "").strip():
            raise ValueError("event.name.html is required")
        for when in ("start", "end"):
            block = event_obj.get(when) or {}
            if not isinstance(block, dict) or not block.get("timezone") or not block.get("utc"):
                raise ValueError(f"event.{when}.timezone and event.{when}.utc are required")
        org = str(organization_id).strip()
        if not org:
            raise ValueError("organization_id is required")
        return self._request(
            "POST",
            f"/organizations/{org}/events/",
            json_body=event_payload,
        )

    def create_ticket_class(
        self, event_id: str, ticket_class: dict[str, Any]
    ) -> dict[str, Any]:
        """POST /v3/events/{event_id}/ticket_classes/

        Documented required: name, quantity_total, and either free=true or cost.
        """
        if "name" not in ticket_class or "quantity_total" not in ticket_class:
            raise ValueError("ticket_class requires name and quantity_total")
        if not ticket_class.get("free") and not ticket_class.get("cost"):
            raise ValueError("ticket_class requires free=true or cost")
        eid = str(event_id).strip()
        if not eid:
            raise ValueError("event_id is required")
        return self._request(
            "POST",
            f"/events/{eid}/ticket_classes/",
            json_body={"ticket_class": ticket_class},
        )

    def publish_event(self, event_id: str) -> dict[str, Any]:
        """POST /v3/events/{event_id}/publish/

        Publish requires name/description, organizer, ≥1 ticket, and valid payment
        options per Eventbrite docs. Free-only events do not need payout setup.
        """
        eid = str(event_id).strip()
        if not eid:
            raise ValueError("event_id is required")
        return self._request("POST", f"/events/{eid}/publish/")
