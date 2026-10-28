#!/usr/bin/env python3
"""Probe a deployed Streamable HTTP MCP endpoint.

Usage:
  python scripts/prod_healthcheck.py https://example.com
  MCP_AUTH_TOKEN=... python scripts/prod_healthcheck.py https://example.com
"""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urljoin

import httpx


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: prod_healthcheck.py <base-url>", file=sys.stderr)
        return 2
    base = sys.argv[1].rstrip("/") + "/"
    token = os.getenv("MCP_AUTH_TOKEN")
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        health = client.get(urljoin(base, "healthz"))
        print("healthz", health.status_code, health.text[:300])
        if health.status_code != 200:
            return 1

        mcp_headers = dict(headers)
        mcp_headers["Content-Type"] = "application/json"
        init = client.post(
            urljoin(base, "mcp"),
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "prod-healthcheck", "version": "0.1"},
                },
            },
        )
        print("mcp_initialize", init.status_code, init.text[:500])
        if init.status_code == 401:
            print("Unauthorized — set MCP_AUTH_TOKEN to match the server.", file=sys.stderr)
            return 1
        if init.status_code >= 400:
            return 1

        # Best-effort tools/list (may need session header depending on server mode)
        tools = client.post(
            urljoin(base, "mcp"),
            headers=mcp_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        print("tools_list", tools.status_code, tools.text[:500])

    print(json.dumps({"ok": True, "base_url": base.rstrip("/")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
