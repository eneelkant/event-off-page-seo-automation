# Google Sheets and Gemini

The MCP can read approved submission sites from Google Sheets and record every attempt on a `Submissions` tab. Gemini, and any other caller that is not an MCP client, uses the HTTP bridge below. Cursor and other MCP clients call the tools directly.

Dry-run is the default. The server does not log in with sheet passwords, does not bypass CAPTCHA or MFA, and does not mark a row published until a live http(s) URL is confirmed.

## Spreadsheet

Spreadsheet ID: `1yJa403y9bDLorNG-ahv2SArlYe5MiUSNgwd7TpoPC0M`

| Tab | Columns, in order |
| --- | --- |
| `Site Login Credentials` | Site Category, Site Name, Website, Username, Password, Page Rank |
| `Submissions` | Site Category, Submission Date, Submission Status, Published Date, Site Name, Website, Published URL |

Do not reorder these columns. The tools reject a header row that does not match.

`Submissions` statuses:

`PENDING`, `DRY_RUN`, `SUBMITTED`, `AWAITING_APPROVAL`, `PUBLISHED`, `REJECTED`, `FAILED`, `MANUAL_ACTION_REQUIRED`

`Published Date` and `Published URL` stay empty until a live publication is confirmed.

The sheet has no event column. The server stores the event id to row mapping in SQLite so a retry updates the same row instead of appending another one. `record_publication_update` uses that mapping. If the event and site do not match a tracked row, it returns an error and does not change a different row.

## Google Cloud setup

1. In Google Cloud, create or choose a project.
2. Enable the **Google Sheets API**.
3. Create a service account and a JSON key.
4. Copy the service account email (`client_email`).
5. Share the spreadsheet with that email as **Editor**. Viewer is not enough, because submission tracking appends and updates rows.
6. Keep the spreadsheet private. Do not publish it to the web.

Store the key in one of these places, never in git:

- `GOOGLE_SHEETS_CREDENTIALS_JSON`: the JSON object as a single environment variable or secret-manager value.
- `GOOGLE_APPLICATION_CREDENTIALS`: a file path to the JSON key. The key file is gitignored when named `service-account*.json`, `google-service-account.json`, or `*-service-account.json`.

Also set:

```bash
GOOGLE_SHEETS_SPREADSHEET_ID=1yJa403y9bDLorNG-ahv2SArlYe5MiUSNgwd7TpoPC0M
GOOGLE_SHEETS_CREDENTIALS_TAB=Site Login Credentials
GOOGLE_SHEETS_SUBMISSIONS_TAB=Submissions
MCP_AUTH_TOKEN=replace-with-a-long-random-token
```

## Passwords

Prefer a secret reference in the Password column:

- `env:EVENTBRITE_API_TOKEN`
- `secret:site-10times`
- `projects/<project>/secrets/<name>/versions/latest`

The tool reports `credential_storage` as `secret_reference`, `legacy_cell`, or `missing`. It does not return the password or the username. A legacy password cell still counts as present, and the response tells you to move it. Do not paste passwords into prompts.

Official API tokens such as `EVENTBRITE_API_TOKEN` stay in environment variables. The sheet reference only names them.

## What can be submitted automatically

`list_submission_targets` matches each website or site name to the local platform registry.

- Eventbrite is the only registry adapter that calls a documented official API. A live call still needs `dry_run=false`, `authorize_publication=true`, `EVENTBRITE_API_TOKEN`, and `EVENTBRITE_ORGANIZATION_ID`. The existing publishing rules apply. A draft without a public URL is `SUBMITTED`, not `PUBLISHED`.
- Every other site, including browser and editorial targets, returns `MANUAL_ACTION_REQUIRED` with instructions. The server does not submit those forms and does not type stored passwords into them.
- Dry-run validates the event first. A valid dry-run writes one `DRY_RUN` row and does not contact the site. A validation failure returns `validation_error` and does not append or update a tracking row.

`submit_event_to_site` fields:

- `event_name`
- `event_description`
- `landing_page_url` (http or https)
- `event_datetime` (ISO-8601)
- `location` or `virtual_event_details`
- `registration_url` (http or https)
- `target_site` (site name or website)
- `dry_run` (default `true`)
- `authorize_publication` (default `false`; ignored while dry-run is true)
- `event_id` (optional stable id; otherwise one is derived and returned)

`event_name`, `event_description`, `landing_page_url`, `event_datetime`, `registration_url`, and `target_site` are required. One of `location` or `virtual_event_details` is required. URLs must be `http` or `https` with no embedded username or password. `event_datetime` must be ISO-8601, including a time.

Validation runs before any spreadsheet write. The HTTP bridge returns `400` with `error` set to `validation_error`, `tracked` set to `false`, and `sheet_row` set to `null`. That response is not a submission. `sheet_row` is only present with a number after the Sheets API accepts an append or update. It is the 1-based row on `Submissions` (row 1 is the header, so the first tracked attempt is row 2). It is not a placeholder.

A later valid request for the same event and site updates that tracked row. It does not turn an earlier validation error into a row, because the invalid request never created one.

## Tracking and errors

| Response | HTTP status | Spreadsheet write |
| --- | --- | --- |
| `validation_error` | 400 | None. Fields were rejected before tracking. |
| `target_not_found` | 404 | None. No credentials row matched the site. |
| `sheets_not_configured` | 503 | None. Spreadsheet id or credentials are missing. |
| `sheets_timeout` | 504 | Uncertain. The append may have landed; a retry adopts one matching unclaimed row instead of guessing. |
| `sheets_api_error` or `sheets_error` | 400 | None when the API rejects the call before accepting the row. |
| `DRY_RUN` | 200 | One `Submissions` row, or an update of the existing event+site row. Published Date and Published URL stay empty. |
| `submission_not_found` | 404 | None. Publication update did not match a tracked event and site. |

`published: false` means the site was not marked published. It does not by itself mean the spreadsheet was left unchanged. Use `tracked` and `sheet_row` on validation errors, and the `Submissions` status on a successful dry-run.

Safe test: omit `dry_run` or set it to `true`, do not send `authorize_publication`, and use a fictional event. Expect `status` `DRY_RUN`, `published` `false`, and a real `sheet_row`. A validation error keeps `sheet_row` null. A numeric `sheet_row` means a `Submissions` row was written.

## Publication updates

`record_publication_update` is how Gemini records a listing that is actually live.

Required to set `PUBLISHED`:

- `event_id` returned by the submit call
- `site_name` or `website`
- `publication_status`: `PUBLISHED`
- `published_url`: http or https, without embedded userinfo
- `published_date`: `YYYY-MM-DD` or an ISO-8601 datetime

An approval email, without that URL, is rejected and the row is left unchanged. Calling it again with the same URL is a no-op.

`REJECTED` updates the status and clears any published URL and date.

## Gemini HTTP bridge

Gemini does not automatically speak MCP. Point a Gemini workflow, Cloud Function, or HTTPS tool at this server:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/submission-targets` | Read sites. No passwords. |
| `POST` | `/api/submissions` | Same body as `submit_event_to_site`. |
| `POST` | `/api/publication-updates` | Same body as `record_publication_update`. |

`GET /healthz` stays public. The three routes above require `Authorization: Bearer <MCP_AUTH_TOKEN>` even on localhost. If the token is unset they return `503`.

```bash
curl -fsS http://127.0.0.1:8000/api/submission-targets \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN"

curl -fsS http://127.0.0.1:8000/api/submissions \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "Example Summit",
    "event_description": "Fictional event for a dry-run.",
    "landing_page_url": "https://example.com/events/example",
    "event_datetime": "2027-06-15T09:00:00Z",
    "location": "San Francisco",
    "registration_url": "https://example.com/events/example/register",
    "target_site": "https://10times.com",
    "dry_run": true,
    "event_id": "evt-example-1"
  }'

# Same dry-run shape when the event has no physical location.
curl -fsS http://127.0.0.1:8000/api/submissions \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "event_name": "Example Summit",
    "event_description": "Fictional event for a dry-run.",
    "landing_page_url": "https://example.com/events/example",
    "event_datetime": "2027-06-15T09:00:00Z",
    "virtual_event_details": "Zoom room 12",
    "registration_url": "https://example.com/events/example/register",
    "target_site": "https://10times.com",
    "dry_run": true,
    "event_id": "evt-example-virtual"
  }'

curl -fsS http://127.0.0.1:8000/api/publication-updates \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-example-1",
    "website": "https://10times.com",
    "publication_status": "PUBLISHED",
    "published_url": "https://10times.com/events/example",
    "published_date": "2027-06-20"
  }'
```

MCP clients keep using `/mcp` (or stdio) and the tool names `list_submission_targets`, `submit_event_to_site`, and `record_publication_update`.

Do not deploy this, and do not send `authorize_publication=true`, until the service account, sheet sharing, tests, and an explicit decision to publish are in place.
