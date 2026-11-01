# UTM links and GA4 reporting

This project can decorate an event landing page with UTM parameters and, when explicitly enabled, read a Google Analytics 4 property. Both features are read-only with respect to directories and GA4. Dry-run remains the default. Nothing in this flow submits a listing or edits a GA4 property.

GA4 measures reported traffic. It does not independently verify that a backlink exists or that a directory listing is live.

## UTM names

| Parameter | Value |
| --- | --- |
| `utm_source` | Normalized destination platform, such as `eventbrite`, `10times`, or `dev_events`. Case is folded. Spaces, dots, and hyphens become underscores. |
| `utm_medium` | `event_directory` unless `UTM_DEFAULT_MEDIUM` or the tool argument overrides it. |
| `utm_campaign` | The campaign text supplied by the caller, with surrounding whitespace removed. The text is not lowercased or slugified. |
| `utm_content` | `event_submission_link` unless overridden. |

Existing non-UTM query parameters and the URL fragment are kept. Managed UTM keys are emitted once. `UTM_CONFLICT_POLICY=replace` (the default) overwrites `utm_source`, `utm_medium`, `utm_campaign`, and `utm_content` when they are already present. `preserve` keeps the first existing value and fills only the missing keys. Other `utm_*` keys, such as `utm_term`, are kept once. The same inputs always produce the same URL.

Only `http` and `https` URLs are accepted. Userinfo, whitespace, and other schemes are rejected. The original event URL in storage is not modified.

Example, with the default replace policy:

```text
https://events.example.com/summit?ref=newsletter#register
```

becomes:

```text
https://events.example.com/summit?ref=newsletter&utm_source=dev_events&utm_medium=event_directory&utm_campaign=Spring%20Launch&utm_content=event_submission_link#register
```

`recommend_submission_targets` and `preview_submission_plan` add these URLs only when `landing_page_url` and `campaign_name` are both supplied. Each planned target gets its own `utm_source`. The response keeps `canonical_landing_page_url` separate from `tracked_landing_page_url`. `utm_parameter_preservation` is `unknown`: a directory may discard query parameters, so a generated URL is not evidence that the published listing will retain the tags.

`preview_event_tracking_url` previews one URL and does not write it.

## GA4 setup

Leave reporting off unless you intend to query a property:

```text
GA4_ENABLED=false
GA4_PROPERTY_ID=
GA4_START_DATE=30daysAgo
GA4_END_DATE=today
GA4_INCLUDE_CONVERSIONS=false
```

When you enable it:

1. In Google Analytics, grant the caller the Viewer role on the property. Editor access is not required.
2. Enable the Google Analytics Data API for the Google Cloud project that owns the credentials.
3. Provide Application Default Credentials, or set `GOOGLE_APPLICATION_CREDENTIALS` to a service-account JSON file. Do not commit that file.
4. Install the optional client: `pip install -e ".[ga4]"`. The default image does not include it.
5. Set `GA4_ENABLED=true` and `GA4_PROPERTY_ID` to the numeric property id.

`query_ga4_campaign_performance` calls `RunReportRequest` with `sessionSource`, `sessionMedium`, `sessionCampaignName`, and `pagePath`, and with `sessions`, `activeUsers`, `screenPageViews`, and `eventCount`. `conversions` is sent only when `GA4_INCLUDE_CONVERSIONS=true` or the tool asks for it. If the property rejects that metric, the result is `metric_not_supported` and no numbers are substituted.

The report filters with exact matches. `source` uses the same platform normalization as `utm_source`. A page argument may be a path (`/summit`) or an `http(s)` URL; the query uses the path. Results are paged, up to `GA4_PAGE_SIZE` rows (maximum 10000) and `GA4_MAX_PAGES` pages (maximum 20). A truncated report says `complete: false` and does not present a partial sum as the property total.

An empty successful report has `rows: []`, `row_count: 0`, `data_state: "empty"`, and `error: null`. An authentication failure, quota error, timeout, or API error has `rows: null` and a non-null `error`. Those are not zero-session results. The tools do not accept credential JSON and do not return credential-file contents.

## Attribution audit

`audit_campaign_attribution` compares the expected campaign, source, medium, and page path with the rows GA4 returned.

- Facts describe the report: whether it was returned, which values appeared, and how many sessions the returned rows contained.
- Inferences describe what those values might mean. They are labeled as potential discrepancies.
- `backlink_verified`, `listing_verified`, `tracking_verified`, and `tracking_broken` stay false.

No recorded sessions can mean delay, consent, low traffic, attribution rules, a date range that misses the visit, or a directory that removed the UTM parameters. It does not prove that tracking is broken. A matching session does not prove that a particular listing is live.

The audit does not update listings or GA4 settings.

## Local tests

No Google credentials or network access are required:

```bash
uv sync --extra dev
uv run pytest -q
uv run python scripts/smoke_test.py
```

The GA4 tests use a fake client. `GA4_ENABLED` stays false in that run.

## Troubleshooting

| Result | Meaning |
| --- | --- |
| `ga4_disabled` | `GA4_ENABLED` is not true. No request was sent. |
| `configuration_error` | The property id, date, campaign, or page path is missing or invalid. |
| `ga4_client_missing` | Install the `ga4` extra. |
| `authentication_error` | Credentials are missing or were rejected. The file contents are not printed. |
| `quota_exceeded` | The Data API quota was consumed. Wait and retry. |
| `timeout` | The read exceeded the configured timeout. This is not a zero result. |
| `metric_not_supported` | The property rejected a dimension or metric. Conversions are the usual cause. |
| `data_state: empty` | The API returned no rows. Tracking is not declared broken. |
