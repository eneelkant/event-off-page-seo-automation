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

That shape sets `citation_validity` to `complete`. It does not check the page. `source_verification_status` stays `unverified`. `kind: "guarantee"` does not make the window a checked guarantee. A nested `human_verification` object, including a verifier name, timestamp, URL, and written claim, is not authentication. That object cannot set `human_verified` and cannot make a target `ELIGIBLE`. `machine_verified` is produced only by the privileged structured-document tools. Incomplete citations stay `unknown`. `research_timestamp` stays null because no live research ran. `machine_verification_performed` is false.

`refresh_target_research` writes those registry snapshots to SQLite at `DATABASE_PATH`. The count `live_researched` stays 0. Fly.io has no volume in `fly.toml`, so a machine restart can drop that file. Google Sheets remains the reporting workbook, not the transactional store.

Account requirements, moderation duration, internal site search, and Google indexing stay `unknown` unless a future citation stores them separately. Indexing is never used as publication time.

Automated extraction from official pages is not implemented. Guessing a number from page text would invent a timeline, so the tools leave the value `unknown` instead.

## Free, paid, and unknown

`paid_submission_possible: false` is only a registry flag. It is not proof that a public listing is free, and it is not proof that paid options are absent. `paid_submission_possible: true` does not by itself verify a paid product.

Pricing uses four separate fields:

| Field | Meaning |
| --- | --- |
| `pricing_citation_validity` | `complete` when a citation has an `http` or `https` URL, an ISO-8601 date, a written reason, and a free or paid statement. `absent` when no citation was supplied. `invalid` when the packet could not be read. Structural completeness is not verification. |
| `pricing_source_verification_status` | `unverified` for a citation. `machine_verified` only when a stored trusted pricing record exists. |
| `pricing_status` | A citation is `unknown`, `claimed_free`, `claimed_paid`, or `claimed_not_free`. `verified_free` is never copied from caller input. A trusted record uses `trusted_free` or `trusted_not_free`. |
| `pricing_live_verified` | False for citations. True only when the stored pricing record came from a live structured-document fetch. |

A citation leaves `free_submission_available` and `paid_options_available` null. The claim itself is `claimed_free_submission`, `claimed_paid_options`, and `claimed_free_conditions`. `free_listing_conditions` stays null. Those booleans become true or false only when a trusted pricing record says so explicitly.

For a citation, `pricing_verified_at` stays null. The date written on the citation is `pricing_citation_recorded_at`. `pricing_evidence_url` is the supplied URL, and `pricing_reason` states that the citation was not authenticated. A trusted record sets `pricing_verified_at` to the server's retrieval time, not to a date inside the caller's packet.

A caller flag such as `pricing_live_verified`, `pricing_verified`, `pricing_source_verification_status`, `human_verified`, or `verified` is rejected as `validation_error` by analysis, recommendation, and preview. The same flag stored in the registry is not accepted, so that row stays `unknown` rather than `claimed_free`. A `verified_free` classification that also sets `free_submission_available` to false, or a `paid_option` classification that sets `paid_options_available` to false, is invalid and stays `unknown`.

Unknown, claimed free, claimed paid, and claimed not-free pricing are excluded from `recommended_submission_order`. When a window would otherwise fit, the timing result is `MANUAL_REVIEW_REQUIRED` and the calculated deadline stays visible. `NOT_FREE` is reserved for a trusted record of `free_submission_available: false`. A paid citation is not labeled `NOT_FREE`. `free_targets` counts only trusted free availability.

## Citation validity and source verification

These fields are separate:

| Field | Meaning |
| --- | --- |
| `citation_validity` | `complete` when the URL, date, summary, and window are structurally present. `absent` when no citation was supplied. `invalid` when a stored citation could not be read. |
| `source_verification_status` | `unverified` for a citation. A caller-supplied name is not `human_verified`. `machine_verified` is set only from a stored structured-document publication record. |
| `timing_kind` | `guarantee` or `estimate` as written on the citation, or `caller_supplied` / `heuristic` when there is no citation. |
| `eligibility_status` | The planning result. It is not a synonym for any of the fields above. |

`unverified` means the source has not been checked. A caller boolean such as `human_verified: true` or `source_verification_status: "machine_verified"` is rejected. It is not proof.

`human_verified` is not produced by this server. Supplying `human_verification` does not create a trusted record. The fields in that object are checked only so a mismatched or boolean forgery is rejected. A structurally complete forgery stays `unverified`, `human_verification` in the result is null, and the warning says the name and claim were not authenticated.

`machine_verified` means a privileged tool fetched the registered official URL and accepted a structured document. Planning, research, and preview calls do not fetch, so they keep `machine_verification_performed` and `live_research_performed` false even when they report a stored record.

A publication citation does not become `ELIGIBLE`. `ELIGIBLE` requires a stored machine-verified guarantee and trusted free pricing. Those records are independent. One without the other stays out of the default plan, except that trusted free pricing with caller-supplied or heuristic timing can be `ELIGIBLE_WITH_RISK`.

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
| `documented_hours_by_platform` or `documented_business_days_by_platform` | not a citation | unknown or any claim | `MANUAL_REVIEW_REQUIRED`. |
| Caller hours or business days | not a citation | `trusted_free` | `ELIGIBLE_WITH_RISK`. The window is still not an official guarantee. |
| `conservative_fallback_hours` | heuristic | unknown or any claim | `MANUAL_REVIEW_REQUIRED`. |
| Heuristic hours | heuristic | `trusted_free` | `ELIGIBLE_WITH_RISK`. |
| Stored machine-verified guarantee | `machine_verified` | `trusted_free` | `ELIGIBLE`. |
| Stored machine-verified guarantee | `machine_verified` | unknown, claimed, or `trusted_not_free` | `MANUAL_REVIEW_REQUIRED`, or `NOT_FREE` when trusted pricing says free is false. |
| none of the above | unknown timeline | any | `PUBLICATION_TIME_UNKNOWN`, excluded from the default plan. |

A pricing citation, URL, date, reason, or boolean flag does not set trusted free availability. Negative numbers, booleans, strings, values above 366 days, conflicting windows, pricing verification flags, and invalid verification metadata are `validation_error` on all three planning tools. Caller timing or pricing evidence for a target that already has a trusted record is also `validation_error`; it does not overwrite that record. Business-day windows skip weekends. An event start that is not after the planning time is `EVENT_PAST`.

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
- `verify_publication_source`
- `verify_pricing_source`

`verify_publication_source` and `verify_pricing_source` are privileged and independent. Both fail closed unless `LIVE_SOURCE_VERIFICATION_ENABLED` is true and the caller presents `VERIFICATION_OPERATOR_TOKEN`. They fetch only the platform's registered HTTPS documentation URL, or the official homepage when that documentation URL is missing. They pin DNS to a public address, refuse redirects to another host or to a private, loopback, link-local, multicast, or metadata address, and limit lookup time, transfer time, size, and redirects. A lookup that exceeds the timeout is discarded. If any resolved address is unsafe, the request is blocked. The connection uses the first validated address and does not look the name up again. Abbreviated, octal, and hexadecimal hosts such as `127.1` are rejected before DNS. IPv4-mapped IPv6 addresses are rejected. HTML and unstructured text stay `unknown`. A document verifies only when it is JSON `schema_version` 1, names the same platform, and states the requested evidence. A `verified_at` or `retrieved_at` field inside that document is ignored; the stored time is the server clock at fetch. Pricing must include an explicit `free_submission_available` boolean. A missing paid option does not prove that submission is free. Control characters are removed from `evidence_summary`. That text is not compared with the structured fields and cannot change the result. A failed fetch removes that evidence type's trusted record so a stale success cannot keep a target eligible. That removal and its audit row commit in one transaction. `prior_trusted_record_removed` is true only when a row was deleted. Unauthorized and disabled calls do not fetch and do not remove a record. On later reads, a stored row is ignored unless its URL is still on the registered official host, its retrieval time is timezone-aware, and its payload passes the same publication or pricing checks. Audit rows record the actor, URL, retrieval time, outcome, summary, and method, and they do not store the operator token.

`submit_event_dry_run` calls the existing submit path with dry-run forced on and `authorize_publication` forced off. Live publishing stays disabled unless a later, explicit authorization path is used. Existing Sheets tools and `/api/submissions` are unchanged.

## Still required before production

- Live publication remains off by default. Do not send `authorize_publication: true` while testing.
- Live source verification is off by default. Leave `LIVE_SOURCE_VERIFICATION_ENABLED` false until an operator sets it and a token deliberately.
- A publication citation still does not become `ELIGIBLE`, and a pricing citation still does not become trusted free.
- HTML and unstructured pages stay `unknown`. Eventbrite's public documentation is HTML, so turning the live flag on does not verify those pages.
- DNS lookup uses the verification timeout, default five seconds. A timed-out lookup thread may finish later; its result is ignored. Planning tools do not resolve DNS.
- `evidence_summary` prose is not proof. It cannot override the explicit boolean or the publication window.
- The SQLite file is the trust store for rows that already passed these checks. A structurally valid row for the registered host is applied. Invalid, off-host, and non-canonical URL rows are ignored. The trusted-row change and its audit insert commit or roll back together.
- The operator token is one shared secret, compared by a SHA-256 digest. It is not a user directory.
- Human verification is still not implemented. A name stored in the registry or in a tool argument is not a verifier.
- Live source verification remains disabled by default and is not deployed.
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
