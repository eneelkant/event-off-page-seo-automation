# Publishing engine

This layer plans submissions. It does not publish, and it does not invent publication times.

`seo-agent` is not connected. `generate_seo_event_content` uses the offline `template` source unless `content_source` is `seo-agent`, which returns `seo_agent_not_configured`.

## What is already known

Policies are built from `config/platforms.json` for every platform and workflow. Official URLs already stored on a row are copied into the policy. Approval hours, search-visibility time, and indexing time stay null or `unknown`. `paid_submission_possible: false` is recorded as a registry statement, not as proof that a public listing is free.

Fly.io still has no volume. `refresh_target_research` writes SQLite snapshots at `DATABASE_PATH`. A machine restart can drop that file. Google Sheets remains the reporting workbook, not the transactional store.

## Tools

Read-only planning:

- `get_target_publication_policy`
- `research_target_publication_time`
- `refresh_target_research`
- `generate_seo_event_content`
- `analyze_event_publishing_deadlines`
- `recommend_submission_targets`
- `preview_submission_plan`

`submit_event_dry_run` calls the existing submit path with dry-run forced on and `authorize_publication` forced off.

Existing Sheets tools and `/api/submissions` are unchanged.

## Deadlines

`latest_safe_submission = event_start - documented_window - safety_buffer`

Without a documented window, the target is `PUBLICATION_TIME_UNKNOWN` and is left out of the default plan. A caller may pass `conservative_fallback_hours`; that result is `ELIGIBLE_WITH_RISK` and labeled `heuristic`. Indexing time is reported separately and is never treated as publication.

## Client matrix

Verified in this repository means automated protocol or unit coverage, not a live login to the vendor UI.

| Client | Connection | Authentication | Configuration | Verified |
| --- | --- | --- | --- | --- |
| Cursor | Remote Streamable HTTP at `/mcp`, or stdio | Bearer `MCP_AUTH_TOKEN` | `.cursor/mcp.json` and `docs/CLIENT_SETUP.md` | Remote HTTP is deployed. This change did not retest the Cursor UI. |
| Gemini | Existing REST bridge, not a native MCP session | Bearer on `/api/*` | `docs/GOOGLE_SHEETS.md` | Sheets routes were deployed earlier. New planning tools are MCP-only until a Gemini MCP client is configured. |
| Claude | Remote MCP or local stdio, using the same `/mcp` endpoint | Bearer header | Claude custom connector or desktop stdio config | Not verified in the Claude app. |
| ChatGPT | Developer-mode MCP connector where the account supports it | Bearer header | ChatGPT app connector UI | Not verified in ChatGPT. |

Do not send `authorize_publication: true` while testing any client.
