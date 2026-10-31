# Publishing engine

This layer plans submissions. It does not publish, and it does not invent publication times.

`generate_seo_event_content` accepts only `content_source=template`. `seo-agent` is disconnected: the tool returns `seo_agent_not_configured` and does not invent a provider, credentials, or a model response. Any other `content_source` returns `unsupported_content_source` and is not relabeled as template output.

## What is read, and what is researched

`get_target_publication_policy`, `research_target_publication_time`, and `refresh_target_research` read `config/platforms.json`. They do not fetch official websites. Every research response sets `live_research_performed` to false and `research_status` to `registry_only` or `not_live_researched`.

A stored citation can be reported when a registry row, or a caller packet, includes all of the following:

- an `http` or `https` official source URL
- an ISO-8601 verification date
- a written reason or summary
- an explicit free/paid statement, or a publication window with `kind` of `guarantee` or `estimate`

Incomplete citations stay `unknown`. A registry citation is not a live fetch and is not a new guarantee. `confidence` is `none` when nothing was cited and `registry_citation` when a stored window is copied through. `research_timestamp` stays null because no live research ran.

`refresh_target_research` writes those registry snapshots to SQLite at `DATABASE_PATH`. The count `live_researched` stays 0. Fly.io has no volume in `fly.toml`, so a machine restart can drop that file. Google Sheets remains the reporting workbook, not the transactional store.

Account requirements, moderation duration, internal site search, and Google indexing stay `unknown` unless a future citation stores them separately. Indexing is never used as publication time.

Automated extraction from official pages is not implemented. Guessing a number from page text would invent a timeline, so the tools leave the value `unknown` instead.

## Free, paid, and unknown

`paid_submission_possible: false` is only a registry flag. It is not proof that a public listing is free, and it is not proof that paid options are absent. `paid_submission_possible: true` does not by itself verify a paid product.

`free_submission_available` is true only when a complete official citation says a free submission exists. `paid_options_available` is true only when a complete citation says a paid option exists. Otherwise both stay null and `pricing_status` is `unknown`.

Policy results include `pricing_reason`, `pricing_evidence_url`, and `pricing_verified_at`. Invalid evidence records the rejection reason and leaves the target unknown.

Unknown pricing is excluded from the default recommended plan, even when a publication window is available. The timing result is then `MANUAL_REVIEW_REQUIRED`. A citation that says free submission is unavailable is `NOT_FREE` while paid options are disabled.

## Publication windows

`latest_safe_submission = event_start - publication_window - safety_buffer`

`event_start_datetime` must include a time and a valid IANA timezone. A naive datetime is interpreted in `event_timezone`, then converted to UTC. Date-only values are rejected. The safety buffer is `publication_deadline_buffer_hours`.

The same arguments are accepted by:

- `analyze_event_publishing_deadlines`
- `recommend_submission_targets`
- `preview_submission_plan`

| Input | Meaning | Result label |
| --- | --- | --- |
| `official_publication_windows_by_platform` | Caller cites an official URL, verification date, summary, `kind` (`guarantee` or `estimate`), and exactly one of `hours` or `business_days` | `timing_source=official_evidence`. A guarantee that fits can be `ELIGIBLE`. An estimate that fits is `ELIGIBLE_WITH_RISK`. |
| `documented_hours_by_platform` and `documented_business_days_by_platform` | Caller-supplied integers. Not an official source. | `timing_source=caller_supplied` and `ELIGIBLE_WITH_RISK` when free submission is also verified. |
| `conservative_fallback_hours` | Heuristic used only where no window was supplied | `timing_source=heuristic` and `ELIGIBLE_WITH_RISK` when free submission is verified. |
| none of the above | No usable window | `PUBLICATION_TIME_UNKNOWN`, excluded from the default plan. |

Negative numbers, booleans, strings, values above 366 days, and conflicting windows for the same target are `validation_error` on all three tools. Business-day windows skip weekends. An event start that is not after the planning time is `EVENT_PAST`.

`recommend_submission_targets` and `preview_submission_plan` keep paid submissions out of the default plan. Unknown timelines and unverified pricing stay out of `recommended_submission_order`. The preview sets `would_publish` to false.

## SEO drafts

The template writer uses only the fields supplied for that call. It does not add speakers, agendas, backlinks, or ranking claims.

The official event name is copied into the title, body, and structured-data `name`. If the name is longer than `title_limit` (default 70), the title is kept intact, `seo_title_within_limit` is false, and the quality report says the title does not meet the limit. Meta descriptions that exceed `description_limit` (default 160) are also kept intact and warned. Required checks cover the event name, description, organizer, timezone-aware start, optional end, `http` or `https` landing and registration URLs, and either a location or virtual details.

## Tools

Read-only planning:

- `get_target_publication_policy`
- `research_target_publication_time`
- `refresh_target_research`
- `generate_seo_event_content`
- `analyze_event_publishing_deadlines`
- `recommend_submission_targets`
- `preview_submission_plan`

`submit_event_dry_run` calls the existing submit path with dry-run forced on and `authorize_publication` forced off. Live publishing stays disabled unless a later, explicit authorization path is used. Existing Sheets tools and `/api/submissions` are unchanged.

## Still required before production

- Live publication remains off by default. Do not send `authorize_publication: true` while testing.
- No target in the current registry has a verified free citation or an official publication window, so the default plan is empty until those citations exist.
- Official pages are not fetched. Adding that later needs a reviewed extractor that returns `unknown` whenever the page does not state a value.
- `seo-agent` is not configured.
- SQLite on Fly.io is ephemeral until a volume is approved. This change does not add one.
- Client UIs in the matrix below were not retested as part of this change.

## Client matrix

Verified in this repository means automated protocol or unit coverage, not a live login to the vendor UI.

| Client | Connection | Authentication | Configuration | Verified |
| --- | --- | --- | --- | --- |
| Cursor | Remote Streamable HTTP at `/mcp`, or stdio | Bearer `MCP_AUTH_TOKEN` | `.cursor/mcp.json` and `docs/CLIENT_SETUP.md` | Remote HTTP is deployed for the earlier Sheets server. This planning change is not deployed. |
| Gemini | Existing REST bridge, not a native MCP session | Bearer on `/api/*` | `docs/GOOGLE_SHEETS.md` | Sheets routes were deployed earlier. New planning tools are MCP-only until a Gemini MCP client is configured. |
| Claude | Remote MCP or local stdio, using the same `/mcp` endpoint | Bearer header | Claude custom connector or desktop stdio config | Not verified in the Claude app. |
| ChatGPT | Developer-mode MCP connector where the account supports it | Bearer header | ChatGPT app connector UI | Not verified in ChatGPT. |
