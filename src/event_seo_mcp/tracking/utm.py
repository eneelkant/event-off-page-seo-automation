"""GA4-compatible UTM landing URLs for event directory submissions.

The builder decorates a copy of the event URL. It does not fetch the URL,
does not submit a listing, and does not write the canonical landing page.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

MANAGED_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
CONFLICT_POLICIES = frozenset({"preserve", "replace"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PLATFORM = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class UtmUrlError(ValueError):
    """A tracked URL could not be built. The original URL is left unchanged."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_platform(platform: str) -> str:
    """Normalize a destination platform id without changing campaign text.

    Spaces, hyphens, and dots become underscores. Case is folded. The result
    matches registry ids such as ``eventbrite``, ``10times``, and ``dev_events``.
    """
    if not isinstance(platform, str):
        raise UtmUrlError("invalid_platform", "platform must be a string")
    text = platform.strip().lower()
    text = re.sub(r"[\s.\-]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text or not _PLATFORM.fullmatch(text) or len(text) > 64:
        raise UtmUrlError("invalid_platform", "platform must normalize to a short slug")
    return text


def build_event_utm_url(
    base_url: str,
    platform: str,
    campaign_name: str,
    *,
    medium: str = "event_directory",
    content: str = "event_submission_link",
    conflict_policy: str = "replace",
) -> str:
    """Return a deterministic tracked URL for one directory submission.

    Existing non-UTM query parameters and the fragment are kept. Managed UTM
    keys are never emitted twice. ``conflict_policy`` chooses the only two
    behaviors for keys that are already present: ``preserve`` keeps the first
    existing value, and ``replace`` writes the generated value. Campaign,
    medium, and content text are stripped but otherwise unchanged.
    """
    parts = _validate_url(base_url)
    source = normalize_platform(platform)
    campaign = _label(campaign_name, field="campaign_name", limit=100)
    medium_value = _label(medium, field="utm_medium", limit=40)
    content_value = _label(content, field="utm_content", limit=100)
    policy = _policy(conflict_policy)
    generated = {
        "utm_source": source,
        "utm_medium": medium_value,
        "utm_campaign": campaign,
        "utm_content": content_value,
    }
    try:
        existing = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=False, errors="strict")
    except UnicodeError as exc:
        raise UtmUrlError("invalid_url", "the URL query string could not be decoded") from exc
    query = _merge_query(existing, generated, policy)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, _encode(query), parts.fragment))


def preview_event_utm_url(
    base_url: str,
    platform: str,
    campaign_name: str,
    *,
    medium: str = "event_directory",
    content: str = "event_submission_link",
    conflict_policy: str = "replace",
) -> dict[str, object]:
    """Dry-run preview. Nothing is stored and nothing is published."""
    preview: dict[str, object] = {
        "original_url": base_url if isinstance(base_url, str) else None,
        "tracked_url": None,
        "platform": None,
        "campaign_name": campaign_name if isinstance(campaign_name, str) else None,
        "utm_source": None,
        "utm_medium": medium,
        "utm_campaign": campaign_name if isinstance(campaign_name, str) else None,
        "utm_content": content,
        "conflict_policy": conflict_policy,
        "dry_run": True,
        "would_publish": False,
        "stored_landing_page_modified": False,
        "utm_parameter_preservation": "unknown",
        "preservation_note": _PRESERVATION_NOTE,
        "error": None,
        "message": None,
    }
    try:
        tracked = build_event_utm_url(
            base_url,
            platform,
            campaign_name,
            medium=medium,
            content=content,
            conflict_policy=conflict_policy,
        )
    except UtmUrlError as exc:
        preview["error"] = exc.code
        preview["message"] = exc.message
        return preview
    source = normalize_platform(platform)
    preview.update(
        {
            "tracked_url": tracked,
            "platform": source,
            "campaign_name": _label(campaign_name, field="campaign_name", limit=100),
            "utm_source": source,
            "utm_medium": _label(medium, field="utm_medium", limit=40),
            "utm_campaign": _label(campaign_name, field="campaign_name", limit=100),
            "utm_content": _label(content, field="utm_content", limit=100),
            "conflict_policy": _policy(conflict_policy),
        }
    )
    return preview


_PRESERVATION_NOTE = (
    "Directory sites are not assumed to keep query parameters. "
    "A generated URL is a tracking candidate. It is not proof the listing will retain UTM tags, "
    "and it is not proof a backlink exists."
)


def _validate_url(base_url: str):
    if not isinstance(base_url, str) or not base_url.strip():
        raise UtmUrlError("invalid_url", "base_url must be an http or https URL")
    if any(ch.isspace() for ch in base_url) or _CONTROL.search(base_url):
        raise UtmUrlError("invalid_url", "base_url contains unsupported characters")
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc or not parts.hostname:
        raise UtmUrlError("invalid_url", "base_url must be an http or https URL")
    if parts.username or parts.password:
        raise UtmUrlError("invalid_url", "base_url must not include userinfo")
    return parts


def _label(value: str, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise UtmUrlError("invalid_input", f"{field} must be a string")
    text = value.strip()
    if not text:
        raise UtmUrlError("invalid_input", f"{field} is required")
    if _CONTROL.search(text):
        raise UtmUrlError("invalid_input", f"{field} contains unsupported characters")
    if len(text) > limit:
        raise UtmUrlError("invalid_input", f"{field} is longer than {limit} characters")
    return text


def _policy(value: str) -> str:
    if not isinstance(value, str):
        raise UtmUrlError("invalid_policy", "conflict_policy must be preserve or replace")
    text = value.strip().lower()
    if text not in CONFLICT_POLICIES:
        raise UtmUrlError("invalid_policy", "conflict_policy must be preserve or replace")
    return text


def _merge_query(
    existing: list[tuple[str, str]],
    generated: Mapping[str, str],
    policy: str,
) -> list[tuple[str, str]]:
    plain: list[tuple[str, str]] = []
    found: dict[str, str] = {}
    extras: list[tuple[str, str]] = []
    for key, value in existing:
        if key in MANAGED_UTM_KEYS:
            found.setdefault(key, value)
            continue
        if key.startswith("utm_"):
            if key not in {item[0] for item in extras}:
                extras.append((key, value))
            continue
        plain.append((key, value))
    managed: list[tuple[str, str]] = []
    for key in MANAGED_UTM_KEYS:
        if policy == "preserve" and key in found:
            managed.append((key, found[key]))
        else:
            managed.append((key, generated[key]))
    return plain + managed + extras


def _encode(pairs: list[tuple[str, str]]) -> str:
    return "&".join(f"{quote(key, safe='')}={quote(value, safe='')}" for key, value in pairs)
