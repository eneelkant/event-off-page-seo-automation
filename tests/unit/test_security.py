"""Security helper tests."""

from __future__ import annotations

import pytest

from event_seo_mcp.security.auth import SecurityError, require_http_auth, validate_bind_address
from event_seo_mcp.security.redaction import redact_mapping, redact_secrets
from event_seo_mcp.settings import Settings


def test_redact_secrets() -> None:
    text = "Authorization: Bearer sk-abc123456789 and api_key=supersecret"
    redacted = redact_secrets(text)
    assert "supersecret" not in redacted
    assert "sk-abc123456789" not in redacted or "***REDACTED***" in redacted


def test_redact_mapping() -> None:
    data = {"token": "abc", "nested": {"password": "x"}, "ok": "visible"}
    out = redact_mapping(data)
    assert out["token"] == "***REDACTED***"
    assert out["nested"]["password"] == "***REDACTED***"
    assert out["ok"] == "visible"


def test_refuse_remote_bind_without_flag(settings: Settings) -> None:
    settings.mcp_http_host = "0.0.0.0"
    settings.mcp_allow_remote_bind = False
    settings.mcp_auth_token = None
    with pytest.raises(SecurityError):
        validate_bind_address(settings)


def test_auth_required_when_token_set(settings: Settings) -> None:
    settings.mcp_auth_token = "secret"
    with pytest.raises(SecurityError):
        require_http_auth(settings, None)
    require_http_auth(settings, "secret")
