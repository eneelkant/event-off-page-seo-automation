"""HTTP authentication and bind-address guards."""

from __future__ import annotations

from event_seo_mcp.settings import Settings


class SecurityError(RuntimeError):
    """Raised when a security policy would be violated."""


def validate_bind_address(settings: Settings) -> None:
    host = settings.mcp_http_host.strip().lower()
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if host in local_hosts:
        return
    if host in {"0.0.0.0", "::", "*"} and not settings.mcp_allow_remote_bind:
        raise SecurityError(
            "Refusing to bind Streamable HTTP to a non-loopback interface without "
            "MCP_ALLOW_REMOTE_BIND=true and an auth token."
        )
    if not settings.mcp_auth_token:
        raise SecurityError(
            "MCP_AUTH_TOKEN is required when binding Streamable HTTP beyond localhost."
        )


def require_http_auth(settings: Settings, provided_token: str | None) -> None:
    expected = settings.mcp_auth_token
    if not expected:
        host = settings.mcp_http_host.strip().lower()
        if host in {"127.0.0.1", "localhost", "::1"}:
            return
        raise SecurityError("Authentication token is required for remote HTTP access.")
    if not provided_token or provided_token != expected:
        raise SecurityError("Invalid or missing authentication token.")
