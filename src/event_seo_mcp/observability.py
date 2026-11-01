"""Operation audit rows and GA4 configuration status.

Audit persistence uses Repository.audit. A failed insert does not change the
tool result. Status checks do not construct a Google client or open a network
connection.
"""

from __future__ import annotations

import logging
import re
import time

from event_seo_mcp.database.repository import Repository
from event_seo_mcp.reporting.ga4 import ga4_client_importable, ga4_property_id_valid
from event_seo_mcp.settings import Settings

logger = logging.getLogger(__name__)

_SUMMARY = re.compile(r"^[a-z0-9_]{1,64}$")
_STARTUP_WARNING = (
    "GA4 is enabled but not configured. Reporting queries will fail until "
    "GA4_PROPERTY_ID is set and the ga4 extra is installed."
)


def elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def ga4_runtime_status(settings: Settings) -> str:
    """Return disabled, configured, or misconfigured without contacting Google."""
    if not settings.ga4_enabled:
        return "disabled"
    if not ga4_property_id_valid(settings.ga4_property_id):
        return "misconfigured"
    if not ga4_client_importable():
        return "misconfigured"
    return "configured"


def warn_if_ga4_misconfigured(settings: Settings) -> None:
    """Log one fixed warning. Startup continues, including when GA4 is disabled."""
    if ga4_runtime_status(settings) == "misconfigured":
        logger.warning("%s", _STARTUP_WARNING)


def operation_summary(result: object, *, success_code: str) -> tuple[str, str]:
    """Map a tool result to an outcome and a short summary code."""
    if not isinstance(result, dict):
        return "failure", "unreadable_result"
    error = result.get("error")
    if error in (None, ""):
        return "success", _safe_summary(success_code)
    if isinstance(error, str) and _SUMMARY.fullmatch(error):
        return "failure", error
    return "failure", "failure"


def record_operation(
    repo: Repository,
    action: str,
    *,
    outcome: str,
    duration_ms: int,
    summary: str,
    entity_id: str | None = None,
) -> None:
    """Store one redacted audit row. Persistence errors are logged and swallowed."""
    try:
        details = {
            "outcome": "success" if outcome == "success" else "failure",
            "duration_ms": max(0, int(duration_ms)),
            "summary": _safe_summary(summary),
        }
        repo.audit("system", action, "operation", _event_id(entity_id), details)
    except Exception:
        logger.warning("operation audit could not be stored")


def _safe_summary(summary: str) -> str:
    if isinstance(summary, str) and _SUMMARY.fullmatch(summary):
        return summary
    return "redacted"


def _event_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 128 or "://" in text or any(character.isspace() for character in text):
        return None
    return text
