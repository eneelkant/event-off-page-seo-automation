# Platform adapters

All platforms in `config/platforms.json` ship as `NEEDS_VERIFICATION` until a workflow is live-tested.

## Adapter map

| Adapter | Platforms / category | Live status |
| --- | --- | --- |
| `eventbrite` | Eventbrite | API v3 create/ticket/publish wired; dry-run default; mocked tests; **NEEDS_VERIFICATION** until human live proof |
| `meetup` | Meetup | Dry-run only |
| `directory_browser` | 10Times, AllEvents, calendars, etc. | Playwright probe dry-run when URL verified |
| `partner` | Google Cloud, Azure, Databricks, Snowflake | Outreach copy only |
| `community` | Reddit, HN, DEV, Indie Hackers | Policy-safe drafts; automation blocked for strict subs |
| `digital_pr` | PR Newswire, Business Wire, GlobeNewswire | Release drafts only |
| `guest_post` | DZone, TechTarget, CMSWire, InformationWeek | Pitch/article drafts only |
| `linkedin` | LinkedIn thought-leadership variants | Drafts only; OAuth posting not verified |

## Shared interface

Every adapter implements:

- `check_capabilities()`
- `validate_submission()`
- `prepare_submission()`
- `submit()`
- `verify_submission()`
- `capture_evidence()`

## Activating a platform

1. Confirm homepage vs submission endpoint (do not invent URLs).
2. Run `discover_platform_submission`.
3. Document auth method and required fields.
4. Live-test with a non-production account where allowed.
5. Only then set `automation_status` to `READY` and record `last_verified_at`.

## Eventbrite (Step 2)

Official docs: [Platform API](https://www.eventbrite.com/platform/api), [Authentication](https://www.eventbrite.com/platform/docs/authentication), [Create events](https://www.eventbrite.com/platform/docs/create-events), [Organizations](https://www.eventbrite.com/platform/docs/organizations).

| Item | Verified detail |
| --- | --- |
| Base URL | `https://www.eventbriteapi.com/v3` |
| Auth | `Authorization: Bearer <private_token>` from [API Keys](https://www.eventbrite.com/platform/api-keys/) (account private token; App Partner OAuth also yields a private token) |
| Scopes | Private token is account-scoped; org membership + create/publish permissions apply at the organization level (no separate public “sandbox scope” documented) |
| Create | `POST /organizations/{organization_id}/events/` — required: `event.name.html`, `event.start.timezone`+`utc`, `event.end.timezone`+`utc`, `event.currency` |
| Ticket | `POST /events/{event_id}/ticket_classes/` — required before publish (`name`, `quantity_total`, `free` or `cost`) |
| Publish | `POST /events/{event_id}/publish/` — optional; gated by `EVENTBRITE_PUBLISH_ON_CREATE` |
| Org ID | `GET /users/me/organizations/` or Eventbrite UI |
| Sandbox | **None documented** — live calls hit production API |

### Local token config

1. Copy `.env.example` → `.env`.
2. Set `EVENTBRITE_API_TOKEN=` (private token) and `EVENTBRITE_ORGANIZATION_ID=`.
3. Keep `DRY_RUN_DEFAULT=true` and `REQUIRE_PUBLICATION_AUTHORIZATION=true`.
4. Leave `EVENTBRITE_PUBLISH_ON_CREATE=false` unless you intentionally want publish after create.

### Live submit (explicit approval required)

Live create is refused unless **all** of:

- `dry_run=false`
- `authorize_publication=true` (MCP tool / orchestrator)
- `EVENTBRITE_API_TOKEN` and `EVENTBRITE_ORGANIZATION_ID` set
- Event fields validate (future start/end, currency, etc.)

Do **not** mark `automation_status` `READY` or set Fly secrets / deploy from this Step 2 work without a separate human-approved live proof.
