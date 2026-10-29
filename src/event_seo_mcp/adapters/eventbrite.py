"""Eventbrite adapter backed by the official API v3 create-event flow.

Verified against Eventbrite Platform docs (no invented endpoints/sandbox):
- Auth: Bearer private token (API Keys page / OAuth private token)
- Create: POST /v3/organizations/{organization_id}/events/
- Ticket: POST /v3/events/{event_id}/ticket_classes/ (required before publish)
- Publish: POST /v3/events/{event_id}/publish/ (optional; gated by settings)

Dry-run is the default path and never calls the network. Live create requires
``authorize_publication=true``, ``EVENTBRITE_API_TOKEN``, and
``EVENTBRITE_ORGANIZATION_ID``. Registry status remains NEEDS_VERIFICATION until
a human confirms a live create against a real account.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from event_seo_mcp.adapters.base import CapabilityReport, PlatformAdapter, SubmissionResult
from event_seo_mcp.adapters.eventbrite_client import EventbriteApiError, EventbriteClient
from event_seo_mcp.schemas.content import GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState
from event_seo_mcp.security.redaction import redact_mapping, redact_secrets
from event_seo_mcp.settings import Settings, get_settings

logger = logging.getLogger(__name__)

DOCS = {
    "platform_api": "https://www.eventbrite.com/platform/api",
    "authentication": "https://www.eventbrite.com/platform/docs/authentication",
    "create_events": "https://www.eventbrite.com/platform/docs/create-events",
    "organizations": "https://www.eventbrite.com/platform/docs/organizations",
}


def _as_utc_z(dt: datetime) -> str:
    """Format datetime as Eventbrite utc string (…Z)."""
    if dt.tzinfo is None:
        aware = dt.replace(tzinfo=timezone.utc)
    else:
        aware = dt.astimezone(timezone.utc)
    return aware.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_eventbrite_create_payload(
    event: EventRecord,
    content: GeneratedContent,
    *,
    currency: str,
) -> dict[str, Any]:
    """Map local event/content into the documented create-event body."""
    start = event.start_datetime
    end = event.end_datetime or (start + timedelta(hours=3))
    tz = event.timezone
    name_html = content.title.strip() or event.event_title
    # description.html is optional/deprecated on newer Create; include when we have body.
    description_html = content.body.strip() or event.event_description
    event_obj: dict[str, Any] = {
        "name": {"html": name_html},
        "start": {"timezone": tz, "utc": _as_utc_z(start)},
        "end": {"timezone": tz, "utc": _as_utc_z(end)},
        "currency": currency.upper(),
        "online_event": bool(event.virtual_event) if event.virtual_event is not None else False,
        "listed": False,  # keep draft listing non-searchable until explicit publish
        "shareable": False,
    }
    if description_html:
        event_obj["description"] = {"html": description_html}
    # Optional summary (≤140) mutually exclusive with some description paths — skip if long.
    summary = (content.title or event.event_title).strip()
    if summary and len(summary) <= 140:
        event_obj["summary"] = summary
    return {"event": event_obj}


def build_default_ticket_class(*, currency: str) -> dict[str, Any]:
    """Free General Admission ticket — sufficient for free-event publish per docs."""
    return {
        "name": "General Admission",
        "quantity_total": 100,
        "free": True,
    }


class EventbriteAdapter(PlatformAdapter):
    name = "eventbrite"

    def __init__(
        self,
        settings: Settings | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory or EventbriteClient

    def _settings_obj(self) -> Settings:
        return self._settings or get_settings()

    def check_capabilities(self) -> CapabilityReport:
        settings = self._settings_obj()
        token_present = bool(settings.eventbrite_api_token)
        org_present = bool(settings.eventbrite_organization_id)
        configured = token_present and org_present
        return CapabilityReport(
            adapter_name=self.name,
            installed=True,
            configured=configured,
            healthy=True,
            supported_operations=[
                "check_capabilities",
                "validate_submission",
                "prepare_submission",
                "submit",
                "verify_submission",
                "capture_evidence",
            ],
            notes=(
                "Official Eventbrite API v3 create/ticket/publish paths wired. "
                "Dry-run default (no network). Live create needs EVENTBRITE_API_TOKEN, "
                "EVENTBRITE_ORGANIZATION_ID, and authorize_publication=true. "
                "Publish is separate (EVENTBRITE_PUBLISH_ON_CREATE). "
                "No public sandbox host is documented — live calls hit production API. "
                "Registry remains NEEDS_VERIFICATION until a human confirms live create."
            ),
            details={
                "eventbrite_token_present": token_present,
                "eventbrite_organization_id_present": org_present,
                "eventbrite_currency": settings.eventbrite_currency,
                "eventbrite_publish_on_create": settings.eventbrite_publish_on_create,
                "eventbrite_api_base_url": settings.eventbrite_api_base_url,
                "documentation": DOCS,
                "create_path": "/organizations/{organization_id}/events/",
                "ticket_path": "/events/{event_id}/ticket_classes/",
                "publish_path": "/events/{event_id}/publish/",
                "auth": "Authorization: Bearer <private_token>",
            },
        )

    def validate_submission(
        self, event: EventRecord, platform: PlatformRecord, content: GeneratedContent
    ) -> list[str]:
        errors = super().validate_submission(event, platform, content)
        settings = self._settings_obj()
        currency = (settings.eventbrite_currency or "").strip().upper()
        if not currency or len(currency) != 3:
            errors.append("EVENTBRITE_CURRENCY must be a 3-letter ISO 4217 code")
        if not event.timezone.strip():
            errors.append("timezone is required for Eventbrite start/end")
        start = event.start_datetime
        end = event.end_datetime or (start + timedelta(hours=3))
        if end < start:
            errors.append("end_datetime must be >= start_datetime")
        # Eventbrite requires future start/end for create; warn-level for dry-run payload prep.
        now = datetime.now(timezone.utc)
        start_utc = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        if start_utc.tzinfo is not None and start_utc.astimezone(timezone.utc) <= now:
            errors.append("Eventbrite requires start datetime in the future")
        return errors

    def prepare_submission(
        self, event: EventRecord, platform: PlatformRecord, content: GeneratedContent
    ) -> dict[str, Any]:
        settings = self._settings_obj()
        base = super().prepare_submission(event, platform, content)
        create_body = build_eventbrite_create_payload(
            event, content, currency=settings.eventbrite_currency
        )
        ticket = build_default_ticket_class(currency=settings.eventbrite_currency)
        return {
            **base,
            "api": {
                "base_url": settings.eventbrite_api_base_url,
                "auth": "Bearer private token (EVENTBRITE_API_TOKEN)",
                "organization_id_configured": bool(settings.eventbrite_organization_id),
                "create_endpoint": (
                    f"{settings.eventbrite_api_base_url.rstrip('/')}"
                    f"/organizations/{{organization_id}}/events/"
                ),
                "ticket_endpoint": (
                    f"{settings.eventbrite_api_base_url.rstrip('/')}"
                    "/events/{event_id}/ticket_classes/"
                ),
                "publish_endpoint": (
                    f"{settings.eventbrite_api_base_url.rstrip('/')}"
                    "/events/{event_id}/publish/"
                ),
                "publish_on_create": settings.eventbrite_publish_on_create,
                "documentation": DOCS,
            },
            "eventbrite_create_body": create_body,
            "eventbrite_ticket_class": ticket,
            "permissions_notes": (
                "Token must belong to a user who can create events in the organization. "
                "Publish additionally requires Manage event status permission and a valid "
                "ticket class (free tickets do not need payout setup)."
            ),
        }

    def _make_client(self) -> EventbriteClient:
        settings = self._settings_obj()
        token = settings.eventbrite_api_token
        if not token:
            raise EventbriteApiError(
                message="EVENTBRITE_API_TOKEN is not configured",
                error_code="NOT_CONFIGURED",
            )
        return self._client_factory(
            token,
            base_url=settings.eventbrite_api_base_url,
            timeout_seconds=settings.eventbrite_timeout_seconds,
        )

    def submit(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content: GeneratedContent,
        *,
        dry_run: bool,
        authorize_publication: bool,
    ) -> SubmissionResult:
        errors = self.validate_submission(event, platform, content)
        prepared = self.prepare_submission(event, platform, content)
        safe_prepared = redact_mapping(prepared)
        if errors:
            return SubmissionResult(
                state=JobState.FAILED,
                message="; ".join(errors),
                dry_run=dry_run,
                error_code="VALIDATION_FAILED",
                response_summary=safe_prepared,
            )

        if dry_run:
            return SubmissionResult(
                state=JobState.CONTENT_PREPARED,
                message=(
                    "Dry-run: Eventbrite create/ticket/publish payload prepared; "
                    "no API call made."
                ),
                dry_run=True,
                response_summary=safe_prepared,
            )

        if not authorize_publication:
            return SubmissionResult(
                state=JobState.AWAITING_APPROVAL,
                message=(
                    "Publication authorization required before live Eventbrite submit. "
                    "Pass authorize_publication=true explicitly."
                ),
                dry_run=False,
                response_summary=safe_prepared,
            )

        settings = self._settings_obj()
        if not settings.eventbrite_api_token:
            return SubmissionResult(
                state=JobState.BLOCKED,
                message=(
                    "Live Eventbrite submit blocked: set EVENTBRITE_API_TOKEN "
                    "(private token from Eventbrite API Keys)."
                ),
                dry_run=False,
                error_code="NOT_CONFIGURED",
                response_summary=safe_prepared,
            )
        org_id = (settings.eventbrite_organization_id or "").strip()
        if not org_id:
            return SubmissionResult(
                state=JobState.BLOCKED,
                message=(
                    "Live Eventbrite submit blocked: set EVENTBRITE_ORGANIZATION_ID "
                    "(from GET /v3/users/me/organizations/ or Eventbrite account UI)."
                ),
                dry_run=False,
                error_code="NOT_CONFIGURED",
                response_summary=safe_prepared,
            )

        # Live path — production API only (no documented sandbox). Caller must have
        # explicitly authorized; still may fail if account lacks permissions.
        client: EventbriteClient | None = None
        try:
            client = self._make_client()
            create_body = prepared["eventbrite_create_body"]
            created = client.create_event(org_id, create_body)
            eb_event_id = str(created.get("id") or "")
            public_url = created.get("url")
            summary: dict[str, Any] = {
                **safe_prepared,
                "live_create": {
                    "organization_id": org_id,
                    "eventbrite_event_id": eb_event_id or None,
                    "status": created.get("status"),
                    "url": public_url,
                    "published": False,
                },
            }
            if not eb_event_id:
                return SubmissionResult(
                    state=JobState.FAILED,
                    message="Eventbrite create returned no event id",
                    dry_run=False,
                    error_code="CREATE_MISSING_ID",
                    response_summary=redact_mapping(summary),
                )

            ticket_resp = client.create_ticket_class(
                eb_event_id, prepared["eventbrite_ticket_class"]
            )
            summary["live_create"]["ticket_class_id"] = ticket_resp.get("id")

            if settings.eventbrite_publish_on_create:
                publish_resp = client.publish_event(eb_event_id)
                summary["live_create"]["published"] = bool(
                    publish_resp.get("published", True)
                )
                # Re-read URL if publish response includes it; else keep create URL.
                if publish_resp.get("url"):
                    public_url = publish_resp["url"]
                    summary["live_create"]["url"] = public_url
                return SubmissionResult(
                    state=JobState.PUBLISHED if public_url else JobState.SUBMITTED,
                    message=(
                        f"Eventbrite event {eb_event_id} created, ticketed, and publish called."
                    ),
                    dry_run=False,
                    published_url=str(public_url) if public_url else None,
                    response_summary=redact_mapping(summary),
                )

            return SubmissionResult(
                state=JobState.SUBMITTED,
                message=(
                    f"Eventbrite draft event {eb_event_id} created with free ticket class; "
                    "not published (EVENTBRITE_PUBLISH_ON_CREATE=false). "
                    "Publish requires a separate authorized step."
                ),
                dry_run=False,
                published_url=None,
                response_summary=redact_mapping(summary),
            )
        except EventbriteApiError as exc:
            logger.error("Eventbrite live submit failed: %s", redact_secrets(str(exc)))
            return SubmissionResult(
                state=JobState.FAILED,
                message=redact_secrets(str(exc)),
                dry_run=False,
                error_code=exc.error_code or "EVENTBRITE_API_ERROR",
                response_summary=redact_mapping(
                    {
                        **safe_prepared,
                        "api_error": {
                            "status_code": exc.status_code,
                            "error_code": exc.error_code,
                            "details": exc.details,
                        },
                    }
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Eventbrite unexpected error: %s", redact_secrets(str(exc)))
            return SubmissionResult(
                state=JobState.FAILED,
                message=redact_secrets(f"Unexpected Eventbrite adapter error: {exc}"),
                dry_run=False,
                error_code="ADAPTER_ERROR",
                response_summary=safe_prepared,
            )
        finally:
            if client is not None:
                client.close()
