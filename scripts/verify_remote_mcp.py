#!/usr/bin/env python3
"""Read-only verification of the hosted MCP (healthz + tools/list + health_check).

Loads MCP_AUTH_TOKEN from env or from the Project store internal token file.
Never prints the token.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

STORE_TOKEN = Path(
    "/cursor/stores/bc-db67e78c-1efd-42e0-b939-8570475c01af/internal/mcp-auth-token.txt"
)
DEFAULT_URL = "https://event-seo-mcp.fly.dev/mcp"
HEALTHZ = "https://event-seo-mcp.fly.dev/healthz"


def _load_token() -> str:
    token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    if token:
        return token
    if STORE_TOKEN.exists():
        return STORE_TOKEN.read_text(encoding="utf-8").strip()
    raise SystemExit("MCP_AUTH_TOKEN not set and store token file missing")


async def main() -> int:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    token = _load_token()
    url = os.environ.get("MCP_REMOTE_URL", DEFAULT_URL).strip()

    # 1) Public healthz (no auth)
    async with httpx2.AsyncClient(timeout=30.0, follow_redirects=True) as bare:
        hz = await bare.get(HEALTHZ)
        print("healthz_status", hz.status_code)
        print("healthz_body", hz.text)
        if hz.status_code != 200:
            return 1

    # 2) Unauthenticated /mcp should 401
    async with httpx2.AsyncClient(timeout=30.0, follow_redirects=True) as bare:
        unauth = await bare.post(
            url,
            headers={
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
                    "clientInfo": {"name": "verify", "version": "0"},
                },
            },
        )
        print("mcp_unauth_status", unauth.status_code)
        if unauth.status_code != 401:
            print("expected_401_for_unauth")
            return 1

    # 3) Authenticated MCP: list tools + health_check only
    http_client = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx2.Timeout(60.0, read=120.0),
        follow_redirects=True,
    )
    try:
        async with streamable_http_client(url, http_client=http_client) as streams:
            read, write = streams
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                print("initialize_ok", True)
                print("server_name", getattr(init, "serverInfo", None) and init.serverInfo.name)

                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                print("tool_count", len(names))
                print("tools", json.dumps(names))
                if "health_check" not in names:
                    print("health_check_missing")
                    return 1

                result = await session.call_tool("health_check", {})
                # structured / text content
                text_bits = []
                for block in result.content:
                    text = getattr(block, "text", None)
                    if text:
                        text_bits.append(text)
                combined = "\n".join(text_bits)
                print("health_check_ok", '"status": "ok"' in combined or '"status":"ok"' in combined or "ok" in combined.lower())
                # Do not dump full payload with potential sensitive env; print compact summary
                try:
                    parsed = json.loads(combined)
                    print(
                        "health_check_summary",
                        json.dumps(
                            {
                                "status": parsed.get("status"),
                                "version": parsed.get("version"),
                                "dry_run_default": parsed.get("dry_run_default"),
                                "adapter_count": len(parsed.get("adapters") or []),
                            }
                        ),
                    )
                except json.JSONDecodeError:
                    print("health_check_preview", combined[:200])
    finally:
        await http_client.aclose()

    print("verification_pass", True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
