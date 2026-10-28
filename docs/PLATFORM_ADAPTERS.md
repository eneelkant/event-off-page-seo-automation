# Platform adapters

All platforms in `config/platforms.json` ship as `NEEDS_VERIFICATION` until a workflow is live-tested.

## Adapter map

| Adapter | Platforms / category | Live status |
| --- | --- | --- |
| `eventbrite` | Eventbrite | Dry-run scaffold; official API docs referenced; create-event not live-tested |
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
