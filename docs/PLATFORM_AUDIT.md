# Platform & capability audit — Event Off-Page SEO Automation MCP

**Audit date:** 2026-10-29  
**Scope:** Read-only inspection of repo + safe live probes against `https://event-seo-mcp.fly.dev`.  
**Constraints honored:** No application code changes, no Fly secret/redeploy changes, no real publications, no invented URLs/APIs/capabilities.

**Evidence sources**
- `config/platforms.json` (35 platforms)
- Adapters under `src/event_seo_mcp/adapters/`
- Tools in `src/event_seo_mcp/tools/register.py`
- Providers / optional integrations / `.env.example`
- Live: `GET /healthz`, unauthenticated `/mcp` → 401, authenticated `tools/list`, and read-only tools (`health_check`, `list_platforms`, `get_platform_details`, `validate_event`, `get_event`, `check_adapter_health`, `get_campaign_report`)

---

## 1. Executive summary

The hosted MCP is **operational as a dry-run / content-prep control plane**, not as a live off-page publisher.

| Area | Finding |
| --- | --- |
| MCP transport | Streamable HTTP live; Bearer auth required on `/mcp`; `/healthz` public |
| Tools | **21/21** registered and discoverable live |
| Platforms | **35/35** `automation_status: NEEDS_VERIFICATION` |
| Live publish | **0** platforms READY; adapters block live submit |
| Dry-run / drafts | Supported in code for all adapter categories (payload/content prep) |
| AI | Only **template** provider available live; OpenAI/Anthropic/Gemini keys absent |
| Optional frameworks | Agno / Crawl4AI / browser-use disabled & not installed; Skyvern HTTP client present but not configured |
| Credentials gap | No Eventbrite/Meetup/LinkedIn/DEV/wire/partner tokens configured on the live host (per `health_check` / adapter `configured` flags) |

**Bottom line:** Safe to use for validation, content drafting, eligibility checks, and reporting scaffolds. **Not** ready for automated directory/community/PR posting without per-platform verification and credentials.

---

## 2. Counts (audit classifications)

Definitions used in this audit (not inventing extra statuses beyond registry + code behavior):

| Class | Meaning | Count |
| --- | --- | --- |
| **Full** | Live submit path verified & marked operational (`READY` + tested publish) | **0** |
| **Partial** | Adapter present; dry-run / content prep / draft path exists; live blocked | **29** |
| **Placeholder** | In registry but homepage and/or submission method unknown/null — discovery required before useful automation | **6** |
| **Missing** | Expected strategy surface with no adapter *or* no live credential/integration where an official API is the intended path | see §6 (credential/integration gaps); **0** platforms missing from registry vs the master build list |
| **Unverified** | Explicit `NEEDS_VERIFICATION` in registry | **35** (all) |

Placeholder set (null/`unknown` homepage or method):  
`event_always`, `events_org`, `global_conference_alliance`, `dev_events`, `cio_events`, plus calendars that only have a brand homepage without a verified submission endpoint (counted as **partial** for draft prep, still unverified for submit). Strict “null homepage” = **5**; including `dev_events`/`cio_events` with unknown method → **6** in placeholder column above.

---

## 3. Category-wise platform table (every listed site)

Legend for **Impl depth**:  
`dry-run draft` = adapter prepares content/payload only · `live blocked` = authorize/live path returns BLOCKED/NEEDS_VERIFICATION · `policy block` = non-dry live blocked for ToS reasons · `no submit URL` = `verified_submission_url` null

### Event directories (8)

| platform_id | Name | Adapter | Homepage | Verified submit URL | Auth (registry) | Status | Impl depth |
| --- | --- | --- | --- | --- | --- | --- | --- |
| eventbrite | Eventbrite | eventbrite | https://www.eventbrite.com | null | oauth_or_api_key | NEEDS_VERIFICATION | dry-run draft; live blocked; docs URL present; `EVENTBRITE_API_TOKEN` not configured live |
| meetup | Meetup | meetup | https://www.meetup.com | null | oauth | NEEDS_VERIFICATION | dry-run draft; live blocked; no docs URL in registry |
| 10times | 10Times | directory_browser | https://10times.com | null | account_login | NEEDS_VERIFICATION | no submit URL → dry-run cannot probe form |
| allevents | AllEvents | directory_browser | https://allevents.in | null | account_login | NEEDS_VERIFICATION | no submit URL |
| conference_alerts | Conference Alerts | directory_browser | https://conferencealerts.com | null | unknown | NEEDS_VERIFICATION | no submit URL |
| event_always | Event Always | directory_browser | null | null | unknown | NEEDS_VERIFICATION | **placeholder** — homepage unconfirmed |
| events_org | Events.org | directory_browser | null | null | unknown | NEEDS_VERIFICATION | **placeholder** |
| global_conference_alliance | Global Conference Alliance | directory_browser | null | null | unknown | NEEDS_VERIFICATION | **placeholder** |

### AI / technology calendars (5)

| platform_id | Name | Adapter | Homepage | Verified submit URL | Method | Status | Impl depth |
| --- | --- | --- | --- | --- | --- | --- | --- |
| techmeme_events | Techmeme Events | directory_browser | https://www.techmeme.com/events | null | manual_or_editorial | NEEDS_VERIFICATION | draft only; editorial path |
| data_science_salon | Data Science Salon | partner | https://www.datascience.salon | null | partner_or_editorial | NEEDS_VERIFICATION | partner outreach draft |
| infoworld_events | InfoWorld Events | directory_browser | https://www.infoworld.com | null | editorial | NEEDS_VERIFICATION | draft only |
| dev_events | Dev Events | directory_browser | null | null | unknown | NEEDS_VERIFICATION | **placeholder** |
| cio_events | CIO Events | directory_browser | null | null | unknown | NEEDS_VERIFICATION | **placeholder** |

### Partner marketing (4)

| platform_id | Name | Adapter | Homepage | Submit URL | Status | Impl depth |
| --- | --- | --- | --- | --- | --- | --- |
| google_cloud_partner | Google Cloud | partner | https://cloud.google.com | null | NEEDS_VERIFICATION | outreach/email draft only |
| microsoft_azure_partner | Microsoft Azure | partner | https://azure.microsoft.com | null | NEEDS_VERIFICATION | draft only |
| databricks_partner | Databricks | partner | https://www.databricks.com | null | NEEDS_VERIFICATION | draft only |
| snowflake_partner | Snowflake | partner | https://www.snowflake.com | null | NEEDS_VERIFICATION | draft only |

### Industry communities (5)

| platform_id | Name | Adapter | Homepage | Verified submit URL | Status | Impl depth |
| --- | --- | --- | --- | --- | --- | --- |
| reddit_artificial | Reddit r/artificial | community | https://www.reddit.com/r/artificial | null | NEEDS_VERIFICATION | dry-run draft; **live policy-blocked** |
| reddit_machinelearning | Reddit r/MachineLearning | community | https://www.reddit.com/r/MachineLearning | null | NEEDS_VERIFICATION | dry-run draft; **live policy-blocked** |
| hacker_news | Hacker News | community | https://news.ycombinator.com | https://news.ycombinator.com/submit | NEEDS_VERIFICATION | only registry entry with verified submit URL; dry-run draft; live still blocked / guidelines caution |
| dev_community | DEV Community | community | https://dev.to | null | NEEDS_VERIFICATION | Forem API docs referenced; not live-tested; no API key configured |
| indie_hackers | Indie Hackers | community | https://www.indiehackers.com | null | NEEDS_VERIFICATION | browser path; no verified URL |

### Digital PR (3)

| platform_id | Name | Adapter | Homepage | Status | Impl depth |
| --- | --- | --- | --- | --- | --- |
| pr_newswire | PR Newswire | digital_pr | https://www.prnewswire.com | NEEDS_VERIFICATION | paid portal; release **draft only** |
| business_wire | Business Wire | digital_pr | https://www.businesswire.com | NEEDS_VERIFICATION | draft only |
| globenewswire | GlobeNewswire | digital_pr | https://www.globenewswire.com | NEEDS_VERIFICATION | draft only |

### Guest posting (4)

| platform_id | Name | Adapter | Homepage | Status | Impl depth |
| --- | --- | --- | --- | --- | --- |
| dzone | DZone | guest_post | https://dzone.com | NEEDS_VERIFICATION | pitch/article draft only |
| techtarget | TechTarget | guest_post | https://www.techtarget.com | NEEDS_VERIFICATION | draft only |
| cmswire | CMSWire | guest_post | https://www.cmswire.com | NEEDS_VERIFICATION | draft only |
| informationweek | InformationWeek | guest_post | https://www.informationweek.com | NEEDS_VERIFICATION | draft only |

### LinkedIn thought leadership (6)

| platform_id | Name | Adapter | Docs hint | Status | Impl depth |
| --- | --- | --- | --- | --- | --- |
| linkedin_speaker_announcement | Speaker announcement | linkedin | learn.microsoft.com/linkedin | NEEDS_VERIFICATION | draft only; OAuth posting not configured/live-tested |
| linkedin_customer_success | Customer success story | linkedin | same | NEEDS_VERIFICATION | draft only |
| linkedin_industry_research | Industry research | linkedin | same | NEEDS_VERIFICATION | draft only; must use approved claims |
| linkedin_agenda_highlights | Agenda highlights | linkedin | same | NEEDS_VERIFICATION | draft only |
| linkedin_executive_poll | Executive poll | linkedin | same | NEEDS_VERIFICATION | draft only |
| linkedin_partner_spotlight | Partner spotlight | linkedin | same | NEEDS_VERIFICATION | draft only |

---

## 4. Twenty-one tool inventory

Live `tools/list` returned **21** tools (matches registration).

| Tool | Class | Live audit | Notes |
| --- | --- | --- | --- |
| health_check | read | **OK** | status ok; dry_run_default true |
| list_platforms | read | **OK** | count 35 |
| get_platform_details | read | **OK** | sampled eventbrite / hacker_news / linkedin |
| discover_platform_submission | read/network | not exercised | may HTTP-fetch homepages; does not invent URLs |
| validate_event | read | **OK** | fictional payload validated |
| create_event | write (DB) | not called | would persist to SQLite |
| get_event | read | **OK** | sample event present on host |
| generate_platform_content | write (content rows) | not called | template/AI generation |
| generate_campaign_content | write | not called | multi-platform generate |
| validate_generated_content | read | not called | schema/soft limits |
| preview_submission | read-ish | not called | may generate content if missing |
| check_submission_eligibility | read | not called | needs stored event |
| submit_event | write / side effects | not called | dry-run default; live requires authorize |
| submit_campaign | write | not called | same guards |
| get_submission_status | read | not called | |
| list_submission_jobs | read | not called | |
| verify_backlink | network read | not called | fixture/HTML override supported in code |
| verify_event_backlinks | network read | not called | |
| get_campaign_report | read | **OK** | planned_submissions 0 |
| export_submission_report | read | not called | json/csv export |
| check_adapter_health | read | **OK** | adapters/providers/integrations |

---

## 5. Confirmed working (this audit)

1. Hosted MCP process + HTTPS hostname `event-seo-mcp.fly.dev`
2. Public `/healthz` → 200, `dry_run_default: true`
3. Bearer gate on `/mcp` → 401 without token
4. Authenticated tool discovery (21 tools)
5. Read-only tools listed above
6. Platform registry sync visible via `list_platforms` (35)
7. Template AI provider available; cloud providers reported unavailable
8. All eight adapters **installed/healthy** as code modules; Eventbrite/Meetup/LinkedIn `configured: false` live (credentials missing)
9. Safety defaults: `DRY_RUN_DEFAULT`, `REQUIRE_PUBLICATION_AUTHORIZATION` (from design + live health)

**Not confirmed:** any live listing creation, API post, browser form submit, wire send, LinkedIn post, or partner portal submit.

---

## 6. Missing integrations & credentials

| Gap | Impact |
| --- | --- |
| `EVENTBRITE_API_TOKEN` unset | Eventbrite adapter `configured: false`; live create blocked |
| Meetup OAuth / API credentials | Live Meetup blocked |
| LinkedIn OAuth app | All six LinkedIn variants draft-only |
| DEV/Forem API key | DEV Community live API unused |
| Wire service customer accounts | PR Newswire / Business Wire / GlobeNewswire draft-only |
| Partner portal eligibility/accounts | Partner adapters draft-only |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | Live content = template only |
| Optional Agno / Crawl4AI / browser-use packages | Soft-fail; discovery/orchestration extras unused |
| Skyvern URL+key | Soft-fail; no verified API calls |
| `verified_submission_url` for 34/35 platforms | Browser dry-run cannot probe forms |
| Persistent volume for SQLite on Fly | Ephemeral disk — jobs/events can reset across Machine replacement |

---

## 7. Security & compliance risks

| Risk | Severity | Notes |
| --- | --- | --- |
| Write-capable MCP tools behind shared Bearer | Medium | Anyone with token can create events / attempt submits (still dry-run/blocked for live, but DB writes possible) |
| Token distribution / desktop env interpolation | Medium | Cursor `${env:MCP_AUTH_TOKEN}` can fail if GUI lacks env; avoid committing tokens |
| Ephemeral SQLite | Medium | Operational data loss / unexpected empty state |
| Policy-sensitive communities | High if misused | Reddit live path blocked; still generates promo drafts in dry-run — human review required |
| HN submit URL known | Medium | Automated posting may violate guidelines; live path blocked by design |
| Browser automation | Medium | Must stop on CAPTCHA/MFA; never bypass (code intends this) |
| Paid wire portals | Medium | Accidental live submit currently blocked; keep authorization gates |
| No invented endpoints | Positive | Registry correctly uses nulls + NEEDS_VERIFICATION |

---

## 8. Recommended implementation order

1. **Eventbrite API dry-run → sandbox create (human-approved)** — only official API with docs URL in registry; set token; verify create-event against Eventbrite docs (do not invent paths); then consider `READY` only after live proof.  
2. **Discover/verify submission URLs** for top directories with known homepages (`10times`, `allevents`, `conference_alerts`) via `discover_platform_submission` + human confirmation — never invent.  
3. **DEV Community Forem API** (documented) for article drafts → optional authenticated post after policy review.  
4. **LinkedIn OAuth app** for thought-leadership posts (company page / member share per Microsoft docs).  
5. **Partner outreach workflows** (email/CRM handoff) — automation stops at draft unless partner APIs verified.  
6. **Wire services** — keep human-in-the-loop; integrate only with vendor-provided APIs/portals.  
7. **Resolve placeholder platforms** (`event_always`, `events_org`, GCA, Dev Events, CIO Events) or remove until homepage confirmed.  
8. **Add Fly volume** for SQLite if campaign state must persist (ask before paid resource).  
9. **Enable one AI provider key** for richer content while keeping dry-run default.

---

## 9. Proposed future config layers (do **not** implement in this audit)

### Layer A — Activation / credentials (per platform)

Machine-readable flags such as: credential env var names present, `last_live_tested_at`, `ready_for_dry_run`, `ready_for_live`, verified endpoint fingerprint, max rate, required human approval. Would gate `submit_event` live path without hardcoding secrets.

### Layer B — Policy & campaign controls

Per-platform policy profile (self-promo allowed?, paid?, editorial-only), content-type allowlist, quiet hours, duplicate windows, UTM defaults, and “never auto-post” lists (e.g. Reddit). Separates **capability** (Layer A) from **permission** (Layer B).

---

## 10. Adapter / provider / DB snapshot

| Component | State |
| --- | --- |
| Adapters (8) | eventbrite, meetup, directory_browser, partner, community, digital_pr, guest_post, linkedin — all present |
| Providers | template ✅ · openai/anthropic/gemini ❌ keys |
| Integrations | all soft-fail disabled/unconfigured on live host |
| DB | SQLite schema for events, platforms, content, jobs, attempts, listings, backlinks, audit_logs |
| Env handling | pydantic-settings + Fly secrets; production requires `MCP_AUTH_TOKEN`, path vars `REPO_ROOT` / absolute config paths |

---

## 11. Audit method notes

- No `create_event` / `submit_*` / content generation called against production (avoids DB mutation and accidental publish).  
- Dry-run submit behavior inferred from adapter source + prior unit tests, not re-executed live.  
- No third-party submission pages were scraped beyond what registry already stores.  
- Token used for live reads was loaded from the Project store internal file and **not** written into this document.
