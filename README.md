# event-off-page-seo-automation

AI-powered off-page SEO automation using Cursor, a custom MCP server, Playwright, and browser-use to manage event directory submissions, digital PR, guest posting, partner promotion, and backlink tracking.

This repository implements a production-oriented **Model Context Protocol (MCP)** server that:

- Validates event records
- Loads a platform registry (directories, calendars, partners, communities, PR, guest posts, LinkedIn)
- Generates platform-specific content (template engine by default; OpenAI / Anthropic / Gemini optional)
- Dry-runs submissions through capability-routed adapters
- Tracks jobs in SQLite with idempotency
- Verifies backlinks against published pages / fixtures
- Soft-fails optional frameworks (Agno, Crawl4AI, browser-use, Skyvern) when unavailable

**Important:** Platforms ship as `NEEDS_VERIFICATION`. This project does not invent submission URLs/APIs and does not publish real listings in tests.

## Requirements

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) recommended (lockfile included) or pip

## Quick start

```bash
uv sync --all-extras
cp .env.example .env
python scripts/init_db.py
python scripts/smoke_test.py
```

### stdio (Cursor / local MCP clients)

```bash
export MCP_TRANSPORT=stdio
python -m event_seo_mcp.server
```

Example Cursor config: `.cursor/mcp.json.example`

### Streamable HTTP

```bash
export MCP_TRANSPORT=streamable-http
export MCP_HTTP_HOST=127.0.0.1
export MCP_HTTP_PORT=8000
python -m event_seo_mcp.server --http
# endpoint: http://127.0.0.1:8000/mcp
```

Remote binds require `MCP_ALLOW_REMOTE_BIND=true` and `MCP_AUTH_TOKEN`.

### Tests

```bash
pytest -q
```

Tests use fixtures/mocks only — they never submit real event listings.

### Docker (production-shaped)

```bash
export MCP_AUTH_TOKEN="$(openssl rand -hex 32)"
docker compose up --build -d
curl -fsS http://127.0.0.1:8000/healthz
# MCP tools require: Authorization: Bearer $MCP_AUTH_TOKEN → /mcp
```

Local loopback override: `docker compose -f compose.yaml -f compose.dev.yaml up --build`

There is **no hosted public URL in this repository by default**. Deploy the image to Fly/Railway/Render/Cloud Run (or your VM) with `MCP_AUTH_TOKEN` set. See `docs/CLIENT_SETUP.md` and the production deploy notes in the project store after release.

## MCP tools

`health_check`, `list_platforms`, `get_platform_details`, `discover_platform_submission`, `validate_event`, `create_event`, `get_event`, `generate_platform_content`, `generate_campaign_content`, `validate_generated_content`, `preview_submission`, `check_submission_eligibility`, `submit_event`, `submit_campaign`, `get_submission_status`, `list_submission_jobs`, `verify_backlink`, `verify_event_backlinks`, `get_campaign_report`, `export_submission_report`, `check_adapter_health`

`submit_event` / `submit_campaign` default to **dry-run**. Live publication requires `authorize_publication=true` and will still block unverified platforms.

Planning tools: `get_target_publication_policy`, `research_target_publication_time`, `refresh_target_research`, `generate_seo_event_content`, `analyze_event_publishing_deadlines`, `recommend_submission_targets`, `preview_submission_plan`, and `submit_event_dry_run`. A complete citation is not source verification, and a verifier name is not authentication. A `verified_free` classification is a claim: it does not set trusted free availability and does not place a target in the default plan. Publication citations stay unverified and out of `ELIGIBLE`. `content_source` accepts only `template`. See [Publishing engine](docs/PUBLISHING_ENGINE.md).

Google Sheets tools: `list_submission_targets`, `submit_event_to_site`, `record_publication_update`. They read the credentials tab without returning passwords, track rows on the `Submissions` tab, and default to dry-run. Gemini and other HTTP clients use `/api/submission-targets`, `/api/submissions`, and `/api/publication-updates` with `Authorization: Bearer $MCP_AUTH_TOKEN`. See [Google Sheets and Gemini](docs/GOOGLE_SHEETS.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Registry](docs/REGISTRY.md)
- [Platform adapters](docs/PLATFORM_ADAPTERS.md)
- [Eventbrite setup](docs/EVENTBRITE.md)
- [Eventbrite local setup](docs/eventbrite-setup.md)
- [Security](docs/SECURITY.md)
- [Client setup](docs/CLIENT_SETUP.md)
- [Deploy](docs/DEPLOY.md)
- [Google Sheets and Gemini](docs/GOOGLE_SHEETS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## License

Apache License 2.0 — see [LICENSE](LICENSE).
