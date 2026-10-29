# Troubleshooting

## MCP server does not start

- Confirm Python ≥ 3.11 and install with `uv sync` or `pip install -e ".[dev]"`.
- Ensure `DATABASE_PATH` parent directory is writable.
- For HTTP mode, check bind/auth policy errors in stderr.

## Tools missing in client

- Confirm the client launches `python -m event_seo_mcp.server` with the project venv.
- Run `python scripts/smoke_test.py` and verify `tool_count` is 21.

## Content generation empty / provider errors

- Default `AI_PROVIDER=template` works offline.
- For OpenAI/Anthropic/Gemini, install extras (`pip install -e ".[ai]"`) and set the matching API key.
- Provider failures raise clear errors; orchestrator can fall back only when `AI_FALLBACK_PROVIDER` is set.

## Playwright issues

- Install with `pip install -e ".[browser]"` then `playwright install chromium`.
- CAPTCHA/login walls stop automation by design (`human_verification_required`).

## Optional frameworks unavailable

- Expected. Agno, Crawl4AI, browser-use, and Skyvern soft-fail.
- Core MCP and dry-run adapters continue to work.

## Duplicate submission errors

- Idempotency keys are `event_id::platform_id::content_type` (plus `::dry_run` for dry runs).
- Re-running the same live submission returns `DUPLICATE` instead of creating another listing.

## Google Sheets

- `sheets_not_configured` means the spreadsheet id or service-account key is missing.
- Share the spreadsheet with the service account email as Editor. Viewer cannot append to `Submissions`.
- Header cells must stay in the documented order. The tools refuse a sheet whose headers do not match.
- `list_submission_targets` never includes username or password values. Move legacy password cells to `env:NAME` or `secret:NAME`.
- Dry-run does not contact the website. Live publication still requires `authorize_publication=true` and a confirmed official API. Other sites return `MANUAL_ACTION_REQUIRED`.
- `record_publication_update` will not mark `PUBLISHED` without an http(s) URL and a publication date.

## Platform still NEEDS_VERIFICATION

- By design until a human verifies the real submission URL/API.
- Do not invent endpoints to force `READY`.
