"""Privileged publication and pricing verification.

Caller citations and verification flags stay untrusted. A trusted record is
written only after this module fetches the platform's registered HTTPS
documentation URL and reads a structured document. HTML, free text, and
model output are not proof. Live fetching is disabled unless
LIVE_SOURCE_VERIFICATION_ENABLED is set, and the call must present the
server-side operator token. Planning tools cannot write these records.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPSConnection
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

from event_seo_mcp.database.repository import Repository
from event_seo_mcp.discovery.platform_discovery import load_platforms_file
from event_seo_mcp.settings import Settings

STRUCTURED_DOCUMENT = "structured_official_document"
PUBLICATION = "publication_window"
PRICING = "pricing"
MAX_HOURS = 24 * 366
MAX_BUSINESS_DAYS = 366
_SUMMARY_MIN = 12
_SUMMARY_MAX = 500
_FORBIDDEN_KEYS = frozenset(
    {
        "source_verification_status",
        "human_verified",
        "machine_verified",
        "machine_verification_performed",
        "timing_live_verified",
        "verified",
        "pricing_source_verification_status",
        "pricing_live_verified",
        "pricing_verified",
        "human_verification",
    }
)
_BLOCKED_SUFFIXES = (".internal", ".local", ".localhost", ".localdomain")
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.google.com",
        "instance-data",
        "instance-data.ec2.internal",
    }
)
_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("100.100.100.200/32"),
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("169.254.170.2/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)


@dataclass(frozen=True)
class UrlCheck:
    ok: bool
    url: str
    host: str
    reason: str


@dataclass(frozen=True)
class FetchResult:
    outcome: str
    reason: str
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    retrieved_at: str | None = None


Resolver = Callable[[str], list[ipaddress.IPv4Address | ipaddress.IPv6Address]]
Opener = Callable[[str, float], tuple[int, dict[str, str], bytes]]


def inspect_https_url(value: str) -> UrlCheck:
    """Accept only a public HTTPS URL. Reject credentials, odd ports, and metadata hosts."""
    if not isinstance(value, str) or not value.strip():
        return UrlCheck(False, "", "", "source URL is missing")
    raw = value.strip()
    if any(mark in raw for mark in ("\\", " ", "\t", "\r", "\n")):
        return UrlCheck(False, "", "", "source URL contains a disallowed character")
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https":
        return UrlCheck(False, "", "", "source URL must use https")
    if parts.username or parts.password:
        return UrlCheck(False, "", "", "source URL must not contain credentials")
    raw_host = parts.hostname or ""
    if raw_host.endswith("."):
        return UrlCheck(False, "", "", "source host is not allowed")
    host = raw_host.lower()
    if not host or "%" in host or host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        return UrlCheck(False, "", "", "source host is not allowed")
    if parts.port not in (None, 443):
        return UrlCheck(False, "", "", "source URL must use port 443")
    ip = _literal_ip(host)
    if ip is not None and _disallowed_ip(ip):
        return UrlCheck(False, "", "", "source address is not allowed")
    if ip is None and not _public_hostname(host):
        return UrlCheck(False, "", "", "source host is not a public DNS name")
    return UrlCheck(True, raw, host, "")


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host.isdigit():
        number = int(host)
        if 0 <= number <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(number)
    return None


def _public_hostname(host: str) -> bool:
    labels = host.split(".")
    if len(labels) < 2:
        return False
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        return False
    return all(character.isalnum() or character == "-" for label in labels for character in label)


def _disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _disallowed_ip(mapped)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    return any(ip in network for network in _EXTRA_BLOCKED_NETWORKS)


def _default_resolver(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        addresses.append(ipaddress.ip_address(info[4][0]))
    return addresses


class _PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, host: str, pinned_ip: str, timeout: float) -> None:
        super().__init__(host, port=443, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, 443), self.timeout)
        context = ssl.create_default_context()
        self.sock = context.wrap_socket(sock, server_hostname=self.host)


def _pinned_open(url: str, timeout: float, pinned_ip: str, max_bytes: int) -> tuple[int, dict[str, str], bytes]:
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    connection = _PinnedHTTPSConnection(parts.hostname or "", pinned_ip, timeout)
    try:
        connection.request(
            "GET",
            path,
            headers={"Accept": "application/json", "User-Agent": "EventSeoMCP-source-verification/0.1"},
        )
        response = connection.getresponse()
        status = response.status
        headers = {key.lower(): value for key, value in response.getheaders()}
        body = response.read(max_bytes + 1)
    finally:
        connection.close()
    return status, headers, body


class SourceFetcher:
    """Fetch one HTTPS URL with redirect, DNS, and size limits. Does not follow blindly."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        opener: Opener | None = None,
        timeout: float = 5.0,
        max_bytes: int = 262144,
        max_redirects: int = 3,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.resolver = resolver or _default_resolver
        self.opener = opener
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.now = now or (lambda: datetime.now(timezone.utc))

    def fetch(self, url: str) -> FetchResult:
        retrieved_at = self.now().isoformat()
        current = url
        original_host: str | None = None
        for _hop in range(self.max_redirects + 1):
            checked = inspect_https_url(current)
            if not checked.ok:
                return FetchResult("blocked", checked.reason, retrieved_at=retrieved_at)
            if original_host is None:
                original_host = checked.host
            elif checked.host != original_host:
                return FetchResult(
                    "blocked",
                    "redirect left the registered official host",
                    retrieved_at=retrieved_at,
                )
            try:
                addresses = self.resolver(checked.host)
            except OSError:
                return FetchResult("unavailable", "the source host could not be resolved", retrieved_at=retrieved_at)
            if not addresses or any(_disallowed_ip(address) for address in addresses):
                return FetchResult("blocked", "source address is not allowed", retrieved_at=retrieved_at)
            try:
                status, headers, body = self._request(checked.url, str(addresses[0]))
            except TimeoutError:
                return FetchResult("unavailable", "the source request timed out", retrieved_at=retrieved_at)
            except OSError:
                return FetchResult("unavailable", "the source could not be fetched", retrieved_at=retrieved_at)
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location:
                    return FetchResult("unavailable", "redirect had no location", final_url=checked.url, status_code=status, retrieved_at=retrieved_at)
                current = urljoin(checked.url, location.strip())
                continue
            if status != 200:
                return FetchResult(
                    "unavailable",
                    f"source responded with HTTP {status}",
                    final_url=checked.url,
                    status_code=status,
                    retrieved_at=retrieved_at,
                )
            if len(body) > self.max_bytes:
                return FetchResult(
                    "unavailable",
                    "response exceeded the size limit",
                    final_url=checked.url,
                    status_code=status,
                    retrieved_at=retrieved_at,
                )
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            return FetchResult(
                "ok",
                "fetched",
                final_url=checked.url,
                status_code=status,
                content_type=content_type,
                body=body,
                retrieved_at=retrieved_at,
            )
        return FetchResult("blocked", "too many redirects", retrieved_at=retrieved_at)

    def _request(self, url: str, pinned_ip: str) -> tuple[int, dict[str, str], bytes]:
        if self.opener is not None:
            return self.opener(url, self.timeout)
        return _pinned_open(url, self.timeout, pinned_ip, self.max_bytes)


def verify_publication_source(
    repo: Repository,
    settings: Settings,
    platform_id: str,
    verification_authorization: str | None = None,
    *,
    fetcher: Any | None = None,
) -> dict[str, Any]:
    return verify_source(
        repo,
        settings,
        PUBLICATION,
        platform_id,
        verification_authorization,
        fetcher=fetcher,
    )


def verify_pricing_source(
    repo: Repository,
    settings: Settings,
    platform_id: str,
    verification_authorization: str | None = None,
    *,
    fetcher: Any | None = None,
) -> dict[str, Any]:
    return verify_source(
        repo,
        settings,
        PRICING,
        platform_id,
        verification_authorization,
        fetcher=fetcher,
    )


def verify_source(
    repo: Repository,
    settings: Settings,
    evidence_type: str,
    platform_id: str,
    verification_authorization: str | None = None,
    *,
    fetcher: Any | None = None,
) -> dict[str, Any]:
    secret = settings.verification_operator_token
    actor, auth_error = _authorize(verification_authorization, secret)
    if auth_error:
        return _finish(
            repo,
            secret,
            actor=actor,
            operation=evidence_type,
            platform_id=_safe_id(platform_id),
            source_url=None,
            retrieved_at=None,
            outcome=auth_error,
            summary=None,
            method=None,
            detail="Verification was not authorized.",
            extra={"message": "Verification was not authorized."},
        )
    if not settings.live_source_verification_enabled:
        return _finish(
            repo,
            secret,
            actor=actor,
            operation=evidence_type,
            platform_id=_safe_id(platform_id),
            source_url=None,
            retrieved_at=None,
            outcome="disabled",
            summary=None,
            method=None,
            detail="Live source verification is disabled.",
            extra={
                "message": "Live source verification is disabled.",
                "live_source_verification_enabled": False,
            },
        )
    if _safe_id(platform_id) is None:
        return _finish(
            repo,
            secret,
            actor=actor,
            operation=evidence_type,
            platform_id=None,
            source_url=None,
            retrieved_at=None,
            outcome="unknown",
            summary=None,
            method=None,
            detail="platform_id is not a registry id",
            error="validation_error",
            extra={"message": "platform_id is not a registry id", "live_source_verification_enabled": True},
        )
    registry = load_platforms_file(settings.resolved_platforms_path)
    platform = registry.by_id(platform_id)
    if platform is None or platform.is_workflow:
        return _finish(
            repo,
            secret,
            actor=actor,
            operation=evidence_type,
            platform_id=platform_id,
            source_url=None,
            retrieved_at=None,
            outcome="unknown",
            summary=None,
            method=None,
            detail="platform was not found",
            error="platform_not_found",
            extra={"message": "platform was not found", "live_source_verification_enabled": True},
        )
    source_url = _official_https_url(platform.documentation_url, platform.official_homepage)
    if source_url is None:
        return _finish(
            repo,
            secret,
            actor=actor,
            operation=evidence_type,
            platform_id=platform_id,
            source_url=None,
            retrieved_at=None,
            outcome="unknown",
            summary=None,
            method=None,
            detail="No allowed https official source URL is registered.",
            extra={
                "message": "No allowed https official source URL is registered.",
                "manual_review_required": True,
                "live_source_verification_enabled": True,
            },
        )
    active = fetcher or SourceFetcher(
        timeout=settings.source_verification_timeout_seconds,
        max_bytes=settings.source_verification_max_bytes,
        max_redirects=settings.source_verification_max_redirects,
    )
    fetched = active.fetch(source_url)
    if fetched.outcome != "ok":
        _delete_trusted(repo, platform_id, evidence_type)
        return _finish(
            repo,
            secret,
            actor=actor,
            operation=evidence_type,
            platform_id=platform_id,
            source_url=source_url,
            retrieved_at=fetched.retrieved_at,
            outcome=fetched.outcome,
            summary=None,
            method=None,
            detail=fetched.reason,
            live_fetch_attempted=True,
            prior_removed=True,
            extra={
                "message": fetched.reason,
                "manual_review_required": True,
                "live_source_verification_enabled": True,
                "prior_trusted_record_removed": True,
            },
        )
    interpreted = _interpret(fetched, evidence_type, platform_id)
    if interpreted is None:
        _delete_trusted(repo, platform_id, evidence_type)
        reason = _interpret_problem(fetched, evidence_type, platform_id)
        return _finish(
            repo,
            secret,
            actor=actor,
            operation=evidence_type,
            platform_id=platform_id,
            source_url=fetched.final_url or source_url,
            retrieved_at=fetched.retrieved_at,
            outcome="unknown",
            summary=None,
            method="uninterpreted_response",
            detail=reason,
            live_fetch_attempted=True,
            prior_removed=True,
            extra={
                "message": reason,
                "manual_review_required": True,
                "live_source_verification_enabled": True,
                "prior_trusted_record_removed": True,
            },
        )
    _save_trusted(repo, platform_id, evidence_type, fetched, interpreted)
    return _finish(
        repo,
        secret,
        actor=actor,
        operation=evidence_type,
        platform_id=platform_id,
        source_url=fetched.final_url or source_url,
        retrieved_at=fetched.retrieved_at,
        outcome="verified",
        summary=interpreted["evidence_summary"],
        method=STRUCTURED_DOCUMENT,
        detail="Structured official document matched the requested evidence type.",
        live_fetch_attempted=True,
        machine_verification_performed=True,
        trusted_record_updated=True,
        extra={
            "message": "Structured official document verified.",
            "manual_review_required": False,
            "live_source_verification_enabled": True,
            "record": interpreted,
        },
    )


def load_trusted_record(repo: Repository, platform_id: str, evidence_type: str) -> dict[str, Any] | None:
    row = repo.db.fetchone(
        """
        SELECT source_url, retrieved_at, outcome, evidence_summary, verification_method, payload_json
        FROM trusted_source_verifications
        WHERE platform_id = ? AND evidence_type = ?
        """,
        (platform_id, evidence_type),
    )
    if row is None or row["outcome"] != "verified" or row["verification_method"] != STRUCTURED_DOCUMENT:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload["source_url"] = row["source_url"]
    payload["retrieved_at"] = row["retrieved_at"]
    payload["evidence_summary"] = row["evidence_summary"]
    payload["verification_method"] = row["verification_method"]
    return payload


def apply_trusted_records(repo: Repository, policy: dict[str, Any]) -> None:
    """Overlay stored trusted records. Caller packets cannot create these rows."""
    publication = load_trusted_record(repo, policy["target_id"], PUBLICATION)
    if publication:
        policy["official_publication_hours"] = publication.get("hours")
        policy["official_publication_business_days"] = publication.get("business_days")
        policy["official_publication_kind"] = publication.get("kind")
        policy["official_publication_source_url"] = publication.get("source_url")
        policy["official_publication_verified_at"] = publication.get("retrieved_at")
        policy["official_publication_summary"] = publication.get("evidence_summary")
        policy["citation_validity"] = "complete"
        policy["source_verification_status"] = "machine_verified"
        policy["publication_verification_method"] = STRUCTURED_DOCUMENT
        policy["publication_retrieved_at"] = publication.get("retrieved_at")
        policy["timing_live_verified"] = True
        policy["verification_warning"] = None
        policy["human_verification"] = None
        policy["verifier"] = None
        policy["claim_checked"] = None
        policy["untrusted_verification_supplied"] = False
        policy["trusted_publication_locked"] = True
        policy["publication_evidence_note"] = None
        policy["publication_time_confidence"] = (
            "machine_verified_guarantee" if publication.get("kind") == "guarantee" else "machine_verified_estimate"
        )
    pricing = load_trusted_record(repo, policy["target_id"], PRICING)
    if not pricing:
        return
    free = pricing.get("free_submission_available")
    paid = pricing.get("paid_options_available")
    policy["free_submission_available"] = free if isinstance(free, bool) else None
    policy["paid_options_available"] = paid if isinstance(paid, bool) else None
    if free is True:
        policy["pricing_status"] = "trusted_free"
    elif free is False:
        policy["pricing_status"] = "trusted_not_free"
    else:
        return
    policy["pricing_reason"] = (
        str(pricing.get("evidence_summary") or "").strip()
        + " Trusted pricing came from a structured official document fetched by this server."
    )
    policy["pricing_evidence_url"] = pricing.get("source_url")
    policy["pricing_url"] = pricing.get("source_url")
    policy["pricing_verified_at"] = pricing.get("retrieved_at")
    policy["pricing_source_verification_status"] = "machine_verified"
    policy["pricing_verification_method"] = STRUCTURED_DOCUMENT
    policy["pricing_retrieved_at"] = pricing.get("retrieved_at")
    policy["pricing_live_verified"] = True
    policy["pricing_confidence"] = "machine_verified"
    policy["trusted_pricing_locked"] = True
    policy["free_listing_conditions"] = None


def _official_https_url(documentation: Any, homepage: Any) -> str | None:
    for candidate in (documentation, homepage):
        if candidate is None:
            continue
        checked = inspect_https_url(str(candidate))
        if checked.ok:
            return checked.url
    return None


def _interpret(fetched: FetchResult, evidence_type: str, platform_id: str) -> dict[str, Any] | None:
    problem = _interpret_problem(fetched, evidence_type, platform_id)
    if problem:
        return None
    assert fetched.body is not None
    document = json.loads(fetched.body.decode("utf-8"))
    summary = str(document["evidence_summary"]).strip()[:_SUMMARY_MAX]
    if evidence_type == PUBLICATION:
        return {
            "kind": document["kind"],
            "hours": document.get("hours"),
            "business_days": document.get("business_days"),
            "evidence_summary": summary,
        }
    paid = document.get("paid_options_available")
    return {
        "free_submission_available": document["free_submission_available"],
        "paid_options_available": paid if isinstance(paid, bool) else None,
        "evidence_summary": summary,
    }


def _interpret_problem(fetched: FetchResult, evidence_type: str, platform_id: str) -> str | None:
    content_type = fetched.content_type or ""
    if content_type not in {"application/json", "application/vnd.event-seo.verification+json"}:
        return "response was not a structured verification document"
    if not fetched.body:
        return "response body was empty"
    try:
        document = json.loads(fetched.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "response was not valid JSON"
    if not isinstance(document, dict):
        return "verification document must be an object"
    present = _FORBIDDEN_KEYS.intersection(document)
    if present:
        return "verification document contained an untrusted verification flag"
    if document.get("schema_version") != 1 or isinstance(document.get("schema_version"), bool):
        return "schema_version must be 1"
    if document.get("evidence_type") != evidence_type:
        return "evidence_type did not match the requested verification"
    if document.get("platform_id") != platform_id:
        return "platform_id did not match the requested target"
    summary = document.get("evidence_summary")
    if not isinstance(summary, str) or not (_SUMMARY_MIN <= len(summary.strip()) <= _SUMMARY_MAX):
        return "evidence_summary must explain the official statement"
    if evidence_type == PUBLICATION:
        return _publication_problem(document)
    return _pricing_problem(document)


def _publication_problem(document: dict[str, Any]) -> str | None:
    hours = document.get("hours")
    days = document.get("business_days")
    has_hours = "hours" in document and hours is not None
    has_days = "business_days" in document and days is not None
    if has_hours == has_days:
        return "provide exactly one of hours or business_days"
    if has_hours and not _plain_int(hours, MAX_HOURS):
        return "hours are outside the accepted range"
    if has_days and not _plain_int(days, MAX_BUSINESS_DAYS):
        return "business_days are outside the accepted range"
    if document.get("kind") not in {"guarantee", "estimate"}:
        return "kind must be guarantee or estimate"
    return None


def _pricing_problem(document: dict[str, Any]) -> str | None:
    if "free_submission_available" not in document:
        return "free submission was not explicitly stated; absence of a paid option is not proof that submission is free"
    free = document.get("free_submission_available")
    paid = document.get("paid_options_available")
    if not isinstance(free, bool):
        return "free_submission_available must be an explicit boolean"
    if "paid_options_available" in document and paid is not None and not isinstance(paid, bool):
        return "paid_options_available must be a boolean when supplied"
    classification = document.get("classification")
    if classification is not None and classification not in {"verified_free", "paid_option", "not_free"}:
        return "pricing classification conflicts with the explicit boolean"
    if classification == "verified_free" and free is False:
        return "pricing statements conflict"
    if classification == "not_free" and free is True:
        return "pricing statements conflict"
    if classification == "paid_option" and paid is False:
        return "pricing statements conflict"
    return None


def _plain_int(value: Any, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


def _authorize(presented: str | None, configured: str | None) -> tuple[str, str | None]:
    if not configured:
        return "unconfigured", "not_configured"
    if not isinstance(presented, str) or not presented:
        return "anonymous", "unauthorized"
    presented_hash = hashlib.sha256(presented.encode("utf-8")).digest()
    configured_hash = hashlib.sha256(configured.encode("utf-8")).digest()
    if not hmac.compare_digest(presented_hash, configured_hash):
        return "anonymous", "unauthorized"
    return "operator", None


def _safe_id(platform_id: Any) -> str | None:
    if not isinstance(platform_id, str):
        return None
    if not platform_id or len(platform_id) > 80:
        return None
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in platform_id):
        return None
    return platform_id


def _save_trusted(
    repo: Repository,
    platform_id: str,
    evidence_type: str,
    fetched: FetchResult,
    interpreted: dict[str, Any],
) -> None:
    repo.db.execute(
        """
        INSERT INTO trusted_source_verifications (
            platform_id, evidence_type, source_url, retrieved_at, outcome,
            evidence_summary, verification_method, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform_id, evidence_type) DO UPDATE SET
            source_url = excluded.source_url,
            retrieved_at = excluded.retrieved_at,
            outcome = excluded.outcome,
            evidence_summary = excluded.evidence_summary,
            verification_method = excluded.verification_method,
            payload_json = excluded.payload_json
        """,
        (
            platform_id,
            evidence_type,
            fetched.final_url,
            fetched.retrieved_at,
            "verified",
            interpreted["evidence_summary"],
            STRUCTURED_DOCUMENT,
            json.dumps(interpreted),
        ),
    )


def _delete_trusted(repo: Repository, platform_id: str, evidence_type: str) -> None:
    repo.db.execute(
        "DELETE FROM trusted_source_verifications WHERE platform_id = ? AND evidence_type = ?",
        (platform_id, evidence_type),
    )


def _scrub(value: str | None, secret: str | None) -> str | None:
    if value is None:
        return None
    if secret:
        value = value.replace(secret, "[redacted]")
    return value[:500]


def _finish(
    repo: Repository,
    secret: str | None,
    *,
    actor: str,
    operation: str,
    platform_id: str | None,
    source_url: str | None,
    retrieved_at: str | None,
    outcome: str,
    summary: str | None,
    method: str | None,
    detail: str,
    extra: dict[str, Any],
    live_fetch_attempted: bool = False,
    machine_verification_performed: bool = False,
    trusted_record_updated: bool = False,
    prior_removed: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    clean_detail = _scrub(detail, secret)
    clean_summary = _scrub(summary, secret)
    platform_id = _scrub(platform_id, secret)
    source_url = _scrub(source_url, secret)
    repo.db.execute(
        """
        INSERT INTO verification_audit_log (
            created_at, actor, operation, platform_id, source_url, retrieved_at,
            outcome, evidence_summary, verification_method, detail
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            actor,
            operation,
            platform_id,
            source_url,
            retrieved_at,
            outcome,
            clean_summary,
            method,
            clean_detail,
        ),
    )
    body = {
        "error": error or (f"verification_{outcome}" if outcome in {"unauthorized", "not_configured", "disabled"} else None),
        "outcome": outcome,
        "evidence_type": operation,
        "platform_id": platform_id,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "verification_method": method,
        "evidence_summary": clean_summary,
        "trusted_record_updated": trusted_record_updated,
        "prior_trusted_record_removed": prior_removed,
        "machine_verification_performed": machine_verification_performed,
        "live_fetch_attempted": live_fetch_attempted,
        "live_research_performed": live_fetch_attempted and outcome == "verified",
        "would_publish": False,
        "dry_run": True,
    }
    body.update(extra)
    if secret:
        encoded = json.dumps(body)
        if secret in encoded:
            body = json.loads(encoded.replace(secret, "[redacted]"))
    return body
