# Security

## Secrets

- Keep `.env` out of Git (see `.gitignore`).
- Use `.env.example` placeholders only (including empty `EVENTBRITE_API_TOKEN`).
- Application logs and audit details pass through secret redaction (Bearer headers, `eventbrite_api_token`, provider keys).
- Never send passwords, cookies, or access tokens to AI providers.
- Google Sheets site passwords are not returned by tools or the HTTP bridge. Prefer `env:NAME` or `secret:NAME` cells. A legacy password cell is detected and discarded.
- Do not commit service-account JSON. `GOOGLE_SHEETS_CREDENTIALS_JSON` and `GOOGLE_APPLICATION_CREDENTIALS` stay in the secret store.
- The Gemini routes `/api/submission-targets`, `/api/submissions`, and `/api/publication-updates` require `MCP_AUTH_TOKEN` even on localhost.
- Eventbrite live create uses the production API host only; never log the private token.

## HTTP deployment

- Default bind is `127.0.0.1`.
- Binding to `0.0.0.0` / `::` requires `MCP_ALLOW_REMOTE_BIND=true` **and** `MCP_AUTH_TOKEN`.
- Clients should present the token as a Bearer credential when configured.

## Platform compliance

- Respect robots.txt, rate limits, and site terms.
- Do not bypass CAPTCHA, MFA, paywalls, or bot detection.
- Do not use stealth plugins, rotating proxies, or CAPTCHA-solving services to evade restrictions.
- Pause for human verification when challenged.
- Require explicit `authorize_publication=true` for irreversible/live actions.
- Avoid unauthorized account creation and mass unsolicited submissions.

## Data

- SQLite path is configurable; protect runtime DB and browser-session directories.
- Store only operational fields needed for SEO workflows; avoid unnecessary personal data.
- Use parameterized SQL throughout the repository layer.
