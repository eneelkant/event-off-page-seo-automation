#!/usr/bin/env python3
"""Smoke test: list tools, check DB, adapters. Never publishes."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def main() -> int:
    from event_seo_mcp.server import create_server
    from event_seo_mcp.settings import get_settings

    settings = get_settings()
    settings.ensure_runtime_dirs()
    mcp, service = create_server(settings)
    tools = await mcp.list_tools()
    health = service.health_check()
    adapters = service.check_adapter_health()
    print(
        json.dumps(
            {
                "ok": True,
                "tool_count": len(tools),
                "tools": sorted(t.name for t in tools),
                "health_status": health.get("status"),
                "database": health.get("database"),
                "adapter_count": len(adapters.get("adapters", [])),
                "integrations": [
                    {
                        "name": i["integration"],
                        "enabled": i["enabled"],
                        "installed": i.get("installed"),
                        "healthy": i.get("healthy"),
                    }
                    for i in adapters.get("integrations", [])
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
