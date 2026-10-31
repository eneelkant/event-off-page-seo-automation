# Publishing engine

This layer plans submissions. It does not publish, and it does not invent publication times.

`generate_seo_event_content` accepts only `content_source=template`. `seo-agent` is disconnected: the tool returns `seo_agent_not_configured` and does not invent a provider, credentials, or a model response. Any other `content_source` returns `unsupported_content_source` and is not relabeled as template output.

## What is read, and what is researched

`get_target_publication_policy`, `research_target_publication_time`, and `refresh_target_research` read `config/platforms.json`. They do not fetch official websites. Every research response sets `live_research_performed` to false and `research_status` to `registry_only` or `not_live_researched`.

A stored citation can be reported when a registry row, or a caller packet, includes all of the following:

- an `http` or `https` official source URL
- an ISO-8601 date
- a written reason or summary
- an explicit free/paid statement, or a publication window with `kind` of `guarantee` or `estimate`

That shape sets `citation_validity` to `complete`. It does not check the page. `source_verification_status` stays `unverified`. `kind: "guarantee"` does not make the window a checked guarantee. A nested `human_verification` object, including a verifier name, timestamp, URL, and written claim, is not authentication. This server has no trusted verification workflow, so that object cannot set `human_verified` and cannot make a target `ELIGIBLE`. Incomplete citations stay `unknown`. `research_timestamp` stays null because no live research ran. `machine_verification_performed` is false.

`refresh_target_research` writes those registry snapshots to SQLite at `DATABASE_PATH`. The count `live_researched` stays 0. Fly.io has no volume in `fly.toml`, so a machine restart can drop that file. Google Sheets remains the reporting workbook, not the transactional store.

Account requirements, moderation duration, internal site search, and Google indexing stay `unknown` unless a future citation stores them separately. Indexing is never used as publication time.

Automated extraction from official pages is not implemented. Guessing a number from page text would invent a timeline, so the tools leave the value `unknown` instead.

## Free, paid, and unknown

`paid_submission_possible: false` is only a registry flag. It is not proof that a public listing is free, and it is not proof that paid options are absent. `paid_submission_possible: true` does not by itself verify a paid product.

Pricing uses four separate fields:

| Field | Meaning |
| --- | --- |
| `pricing_citation_validity` | `complete` when a citation has an `http` or `https` URL, an ISO-8601 date, a written reason, and a free or paid statement. `absent` when no citation was supplied. `invalid` when the packet could not be read. Structural completeness is not verification. |
| `pricing_source_verification_status` | `unverified` for every citation this server can read. No trusted pricing workflow is configured. |
| `pricing_status` | What the evidence claims: `unknown`, `claimed_free`, `claimed_paid`, or `claimed_not_free`. The input classification `verified_free` is a claim. It is never copied into this field. |
| `pricing_live_verified` | Always false. This server does not fetch the pricing page. |

`free_submission_available` and `paid_options_available` stay null on policy results and on deadline decisions. A citation does not set them. The claim itself is `claimed_free_submission`, `claimed_paid_options`, and `claimed_free_conditions`. `free_listing_conditions` stays null because those conditions were not authenticated.

`pricing_verified_at` stays null. The date written on the citation is `pricing_citation_recorded_at`. `pricing_evidence_url` is the supplied URL, and `pricing_reason` repeats the supplied reason and states that the citation was not authenticated.

A caller flag such as `pricing_live_verified`, `pricing_verified`, `pricing_source_verification_status`, `human_verified`, or `verified` is rejected as `validation_error` by analysis, recommendation, and preview. The same flag stored in the registry is not accepted, so that row stays `unknown` rather than `claimed_free`. A `verified_free` classification that also sets `free_submission_available` to false, or a `paid_option` classification that sets `paid_options_available` to false, is invalid and stays `unknown`.

Unknown, claimed free, claimed paid, and claimed not-free pricing are excluded from `recommended_submission_order`. When a window would otherwise fit, the timing result is `MANUAL_REVIEW_REQUIRED` and the calculated deadline stays visible. `NOT_FREE` is reserved for a trusted record of `free_submission_available: false`. No current input creates that record, so a paid citation is not labeled `NOT_FREE`. `free_targets` counts only trusted free availability, which stays 0.

## Citation validity and source verification

These fields are separate:

| Field | Meaning |
| --- | --- |
| `citation_validity` | `complete` when the URL, date, summary, and window are structurally present. `absent` when no citation was supplied. `invalid` when a stored citation could not be read. |
| `source_verification_status` | `unverified` for every citation this server can read today. `human_verified` would require a trusted workflow that authenticates the verifier. That workflow is not configured, and a caller-supplied name is not it. `machine_verified` is reserved for a fetch-and-check process that this server does not run. |
| `timing_kind` | `guarantee` or `estimate` as written on the citation, or `caller_supplied` / `heuristic` when there is no citation. |
| `eligibility_status` | The planning result. It is not a synonym for any of the fields above. |

`unverified` means the source has not been checked. A caller boolean such as `human_verified: true` or `source_verification_status: "machine_verified"` is rejected. It is not proof.

`human_verified` is not produced by this server. Supplying `human_verification` does not create a trusted record. The fields in that object are checked only so a mismatched or boolean forgery is rejected. A structurally complete forgery stays `unverified`, `human_verification` in the result is null, and the warning says the name and claim were not authenticated.

`machine_verified` would mean this process fetched the page and confirmed the claim. That process is not implemented. Every planning and research response sets `machine_verification_performed` and `live_research_performed` to false.

A target can become `ELIGIBLE` only after a trusted verification workflow exists and records a checked guarantee. No such workflow is configured, so publication citations do not become `ELIGIBLE`.

## Publication windows

`latest_safe_submission = event_start - publication_window - safety_buffer`

`event_start_datetime` must include a time and a valid IANA timezone. A naive datetime is interpreted in `event_timezone`, then converted to UTC. Date-only values are rejected. The safety buffer is `publication_deadline_buffer_hours`. Google indexing and internal search stay separate from this deadline.

The same arguments are accepted by:

- `analyze_event_publishing_deadlines`
- `recommend_submission_targets`
- `preview_submission_plan`

| Input | Publication verification | Pricing this server can produce | Result when the deadline fits |
| --- | --- | --- | --- |
| Complete citation with `kind: "guarantee"` | `unverified` | unknown or any claim | `MANUAL_REVIEW_REQUIRED`. The calculated window stays visible, with a warning. It is not `ELIGIBLE`. |
| Complete citation with `kind: "estimate"` | `unverified` | unknown or any claim | `MANUAL_REVIEW_REQUIRED`. |
| Same citation plus a `human_verification` name, timestamp, and claim | `unverified` | unknown or any claim | `MANUAL_REVIEW_REQUIRED`. The supplied record is not authenticated. |
| `documented_hours_by_platform` or `documented_business_days_by_platform` | not a citation | unknown, `claimed_free`, `claimed_paid`, or `claimed_not_free` | `MANUAL_REVIEW_REQUIRED`. The caller window is not an official guarantee, and the pricing claim is not trusted. |
| `conservative_fallback_hours` | heuristic | unknown or any claim | `MANUAL_REVIEW_REQUIRED` for the same pricing reason. |
| none of the above | unknown timeline | any | `PUBLICATION_TIME_UNKNOWN`, excluded from the default plan. |

`ELIGIBLE` and `ELIGIBLE_WITH_RISK` would require trusted free availability. No configured workflow sets `free_submission_available` to true, so those states are not produced from a pricing citation, a URL, a date, a reason, or a boolean flag. Negative numbers, booleans, strings, values above 366 days, conflicting windows, pricing verification flags, and invalid verification metadata are `validation_error` on all three tools. Business-day windows skip weekends. An event start that is not after the planning time is `EVENT_PAST`.

`recommend_submission_targets` and `preview_submission_plan` use those same states. The preview sets `would_publish` to false.

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
- No trusted verification workflow is configured, so no publication citation becomes `ELIGIBLE` and no pricing citation becomes trusted free.
- Official pages are not fetched. `machine_verified` stays unused until a reviewed extractor confirms the claim and otherwise returns `unknown`.
- A future trusted workflow has to authenticate the verifier. Storing a name in the registry or in a tool argument is not that workflow.
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
