"""Bearer auth middleware and HTTP app security tests."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from event_seo_mcp.database.connection import Database
from event_seo_mcp.security.auth import SecurityError
from event_seo_mcp.server import build_http_app, create_server
from event_seo_mcp.settings import Settings


def test_bearer_required_for_mcp_path(settings: Settings, tmp_path) -> None:
    settings.mcp_auth_token = "prod-secret-token"
    settings.mcp_http_host = "0.0.0.0"
    settings.mcp_allow_remote_bind = True
    db = Database(tmp_path / "auth.db")
    mcp, _ = create_server(settings, database=db)
    app = build_http_app(mcp, settings)

    with TestClient(app) as client:
        denied = client.post("/mcp", json={})
        assert denied.status_code == 401

        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        ok = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer prod-secret-token",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert ok.status_code != 401


def test_remote_bind_without_token_refused(settings: Settings, tmp_path) -> None:
    settings.mcp_auth_token = None
    settings.mcp_http_host = "0.0.0.0"
    settings.mcp_allow_remote_bind = True
    db = Database(tmp_path / "auth2.db")
    mcp, _ = create_server(settings, database=db)
    with pytest.raises(SecurityError):
        build_http_app(mcp, settings)
