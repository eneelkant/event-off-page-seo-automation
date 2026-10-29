#!/usr/bin/env python3
"""Local stdio MCP proxy → remote Streamable HTTP (Bearer via env).

Preferred Cursor config (no proxy) uses header interpolation:

  Authorization: Bearer ${env:MCP_AUTH_TOKEN}

Use this stdio proxy when the Cursor desktop process cannot see shell env vars
(so header interpolation sends the literal `${env:MCP_AUTH_TOKEN}`). Stdio
`env` interpolation still works because Cursor launches the command itself.

  {
    "command": "python",
    "args": ["${workspaceFolder}/scripts/cursor_remote_mcp_proxy.py"],
    "env": {
      "MCP_REMOTE_URL": "https://event-seo-mcp.fly.dev/mcp",
      "MCP_AUTH_TOKEN": "${env:MCP_AUTH_TOKEN}"
    }
  }

Never hardcode the token.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any


async def _amain() -> int:
    token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    url = os.environ.get("MCP_REMOTE_URL", "https://event-seo-mcp.fly.dev/mcp").strip()
    if not token:
        print("MCP_AUTH_TOKEN is required for the remote proxy", file=sys.stderr)
        return 2

    import httpx2
    from mcp import ClientSession, types
    from mcp.client.streamable_http import streamable_http_client
    from mcp.server.lowlevel import NotificationOptions, Server
    from mcp.server.stdio import stdio_server

    http_client = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx2.Timeout(60.0, read=120.0),
        follow_redirects=True,
    )

    try:
        async with streamable_http_client(url, http_client=http_client) as streams:
            read_remote, write_remote = streams
            async with ClientSession(read_remote, write_remote) as remote:
                await remote.initialize()
                listed = await remote.list_tools()
                cached_tools = list(listed.tools)

                async def on_list_tools(_ctx, _params) -> types.ListToolsResult:
                    return types.ListToolsResult(tools=cached_tools)

                async def on_call_tool(_ctx, params: types.CallToolRequestParams):
                    result = await remote.call_tool(params.name, params.arguments or {})
                    return result

                server = Server(
                    "event-off-page-seo-proxy",
                    on_list_tools=on_list_tools,
                    on_call_tool=on_call_tool,
                )

                async with stdio_server() as (read_local, write_local):
                    await server.run(
                        read_local,
                        write_local,
                        server.create_initialization_options(
                            notification_options=NotificationOptions(),
                        ),
                    )
    finally:
        await http_client.aclose()
    return 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_amain()))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"proxy_error: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
