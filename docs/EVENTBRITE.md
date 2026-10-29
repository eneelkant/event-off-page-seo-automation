# Eventbrite adapter setup

Step 2 implementation notes for **Eventbrite only**. Status in `config/platforms.json` remains **`NEEDS_VERIFICATION`** until a human confirms a live create.

## What works today (no user token required)

- Dry-run payload prep for create / free ticket class / optional publish
- Field validation (platform required fields + future start + ISO currency)
- Capability report reflecting whether token/org env vars are present
- Unit tests with a **mocked** HTTP client (no real Eventbrite network calls)

## User action required for live create

1. Create or open an Eventbrite organizer account that owns an Organization.
2. Copy your **private token** from the [API Keys](https://www.eventbrite.com/platform/api-keys/) page (see [Authentication](https://www.eventbrite.com/platform/docs/authentication)).
3. Resolve `organization_id` via `GET https://www.eventbriteapi.com/v3/users/me/organizations/` with `Authorization: Bearer <token>`, or from the Eventbrite UI.
4. Put placeholders only in git; real values in local `.env`:

```bash
EVENTBRITE_API_TOKEN=your_private_token_here
EVENTBRITE_ORGANIZATION_ID=your_org_id_here
EVENTBRITE_CURRENCY=USD
EVENTBRITE_PUBLISH_ON_CREATE=false
DRY_RUN_DEFAULT=true
REQUIRE_PUBLICATION_AUTHORIZATION=true
```

5. Live submit still needs **explicit** `authorize_publication=true` on `submit_event` (and `dry_run=false`).
6. With `EVENTBRITE_PUBLISH_ON_CREATE=false` (default), live create makes a **draft** event + free ticket class and does **not** call publish.
7. After a successful human-approved live create, update `automation_status` → `READY` and set `last_verified_at` in a follow-up change. Do not treat mocked tests as live proof.

## Account / permission requirements (from Eventbrite docs)

- Authenticated user must belong to the target Organization.
- Create events under that org; publish additionally needs manage-event-status style permission and ≥1 ticket class.
- Free-only events do not require payout setup; paid tickets need valid payment options before publish.
- **No public sandbox API host** is documented — authorized live calls use production `https://www.eventbriteapi.com/v3`.

## Verified endpoints used by the adapter

| Step | Method + path |
| --- | --- |
| List orgs | `GET /users/me/organizations/` |
| Create event | `POST /organizations/{organization_id}/events/` |
| Create ticket | `POST /events/{event_id}/ticket_classes/` |
| Publish | `POST /events/{event_id}/publish/` |

Auth header on every call: `Authorization: Bearer <private_token>`.

## Safety

- Never commit real tokens; `.env.example` stays empty placeholders.
- Logs and attempt summaries run through secret redaction (`eventbrite_api_token`, Bearer headers).
- This Step 2 change does **not** deploy, change Fly secrets, or modify other platforms.
