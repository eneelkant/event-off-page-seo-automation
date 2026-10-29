"""MCP server entrypoint (stdio + Streamable HTTP)."""

from __future__ import annotations

import logging
import sys
from typing import Any

import uvicorn
from mcp.server import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from event_seo_mcp import __version__
from event_seo_mcp.database.connection import Database, get_database
from event_seo_mcp.database.repository import Repository
from event_seo_mcp.security.auth import SecurityError, validate_bind_address
from event_seo_mcp.security.http_middleware import BearerTokenMiddleware
from event_seo_mcp.settings import Settings, get_settings, reset_settings_cache
from event_seo_mcp.tools.handlers import ToolService
from event_seo_mcp.tools.register import register_tools


def create_server(
    settings: Settings | None = None, database: Database | None = None
) -> tuple[MCPServer, ToolService]:
    settings = settings or get_settings()
    settings.ensure_runtime_dirs()
    db = database or get_database(settings.resolved_database_path)
    service = ToolService(Repository(db), settings)
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


def build_http_app(
    mcp: MCPServer, settings: Settings, service: ToolService | None = None
) -> Starlette:
    """Build Streamable HTTP ASGI app with /healthz and Bearer auth when configured."""

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "event-off-page-seo-automation",
                "version": __version__,
                "dry_run_default": settings.dry_run_default,
            }
        )

    if service is not None:
        from event_seo_mcp.integrations.google_sheets.http_api import register_sheets_http

        register_sheets_http(mcp, service, settings)

    app = mcp.streamable_http_app(
        streamable_http_path=settings.mcp_http_path,
        json_response=True,
        stateless_http=True,
        host=settings.mcp_http_host,
    )

    if settings.mcp_auth_token:
        app.add_middleware(
            BearerTokenMiddleware,
            token=settings.mcp_auth_token,
            public_paths={"/healthz"},
        )
        logging.info("Bearer authentication enabled for Streamable HTTP (except /healthz)")
    else:
        host = settings.mcp_http_host.strip().lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise SecurityError("MCP_AUTH_TOKEN is required for non-localhost Streamable HTTP")
        logging.warning("Streamable HTTP running without auth token (localhost only)")

    return app


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

    mcp, service = create_server(settings)

    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    if transport == "streamable-http":
        try:
            validate_bind_address(settings)
            app = build_http_app(mcp, settings, service)
        except SecurityError as exc:
            logging.error("Refusing to start HTTP transport: %s", exc)
            raise SystemExit(2) from exc

        logging.info(
            "Starting Streamable HTTP on http://%s:%s%s (healthz=/healthz)",
            settings.mcp_http_host,
            settings.mcp_http_port,
            settings.mcp_http_path,
        )
        uvicorn.run(
            app,
            host=settings.mcp_http_host,
            port=settings.mcp_http_port,
            log_level=settings.log_level.lower(),
        )
        return

    raise SystemExit(f"Unsupported transport: {transport}")


if __name__ == "__main__":
    main()
