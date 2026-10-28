"""MCP server entrypoint (stdio + Streamable HTTP)."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server import MCPServer

from event_seo_mcp.database.connection import Database, get_database, reset_database_singleton
from event_seo_mcp.database.repository import Repository
from event_seo_mcp.security.auth import SecurityError, validate_bind_address
from event_seo_mcp.settings import get_settings, reset_settings_cache
from event_seo_mcp.tools.handlers import ToolService
from event_seo_mcp.tools.register import register_tools
from event_seo_mcp import __version__


def create_server(settings=None, database: Database | None = None) -> tuple[MCPServer, ToolService]:
    settings = settings or get_settings()
    settings.ensure_runtime_dirs()
    db = database or get_database(settings.resolved_database_path)
    repo = Repository(db)
    service = ToolService(repo, settings)
    service.load_example_event_if_needed()

    mcp = MCPServer(
        name="event-off-page-seo-automation",
        version=__version__,
        instructions=(
            "Off-page SEO automation for events: validate events, discover platforms, "
            "generate content, dry-run submissions, track jobs, and verify backlinks. "
            "Live publication requires explicit authorize_publication and verified adapters. "
            "Optional frameworks (Agno, Crawl4AI, browser-use, Skyvern) soft-fail when unavailable."
        ),
    )
    register_tools(mcp, service)
    return mcp, service


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    reset_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    transport = settings.mcp_transport
    if "--http" in argv or "--streamable-http" in argv:
        transport = "streamable-http"
    if "--stdio" in argv:
        transport = "stdio"

    mcp, _service = create_server(settings)

    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    if transport == "streamable-http":
        try:
            validate_bind_address(settings)
        except SecurityError as exc:
            logging.error("Refusing to start HTTP transport: %s", exc)
            raise SystemExit(2) from exc
        kwargs: dict[str, Any] = {
            "transport": "streamable-http",
            "host": settings.mcp_http_host,
            "port": settings.mcp_http_port,
            "streamable_http_path": settings.mcp_http_path,
            "stateless_http": True,
            "json_response": True,
        }
        # Auth token is validated at bind policy level; clients should send it as Bearer.
        if settings.mcp_auth_token:
            os.environ.setdefault("MCP_AUTH_TOKEN", settings.mcp_auth_token)
        logging.info(
            "Starting Streamable HTTP on http://%s:%s%s",
            settings.mcp_http_host,
            settings.mcp_http_port,
            settings.mcp_http_path,
        )
        mcp.run(**kwargs)
        return

    raise SystemExit(f"Unsupported transport: {transport}")


if __name__ == "__main__":
    main()
