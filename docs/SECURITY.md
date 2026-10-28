# Security

## Secrets

- Keep `.env` out of Git (see `.gitignore`).
- Use `.env.example` placeholders only.
- Application logs and audit details pass through secret redaction.
- Never send passwords, cookies, or access tokens to AI providers.

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
