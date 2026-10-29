# Production deploy

## Current status

- Code on `main` supports **Streamable HTTP** with **Bearer auth**, `/healthz`, dry-run defaults, and Docker/`fly.toml`.
- A **public hosted URL is not provisioned from this agent environment** (no Fly/Railway/Render/Cloud Run credentials, no Docker daemon).

## Fastest path to a live URL (Fly.io)

```bash
# 1. Install flyctl and authenticate (human step)
curl -L https://fly.io/install.sh | sh
fly auth login

# 2. From the repo root
export MCP_AUTH_TOKEN="$(openssl rand -hex 32)"
fly apps create event-seo-mcp   # choose a unique name if taken
fly secrets set MCP_AUTH_TOKEN="$MCP_AUTH_TOKEN" \
  DRY_RUN_DEFAULT=true \
  AI_PROVIDER=template \
  REQUIRE_PUBLICATION_AUTHORIZATION=true
fly deploy

# 3. Verify
curl -fsS "https://event-seo-mcp.fly.dev/healthz"
MCP_AUTH_TOKEN="$MCP_AUTH_TOKEN" python scripts/prod_healthcheck.py "https://event-seo-mcp.fly.dev"
```

Save `MCP_AUTH_TOKEN` in your password manager. Clients must send `Authorization: Bearer <token>`.

## Docker Compose on a VM

```bash
export MCP_AUTH_TOKEN="$(openssl rand -hex 32)"
docker compose up --build -d
# Put TLS in front (Caddy/nginx/Cloudflare) → https://mcp.example.com
curl -fsS http://127.0.0.1:8000/healthz
```

## Required production env

| Variable | Required | Notes |
| --- | --- | --- |
| `MCP_AUTH_TOKEN` | **Yes** | Bearer secret for `/mcp` and the Gemini routes `/api/*` |
| `MCP_ALLOW_REMOTE_BIND` | Yes (`true`) | With `MCP_HTTP_HOST=0.0.0.0` |
| `DRY_RUN_DEFAULT` | Recommended `true` | Prevents accidental live publishes |
| `AI_PROVIDER` + provider key | For LLM content | `template` works offline |
| `EVENTBRITE_API_TOKEN` | Optional | Private token; dry-run works without it |
| `EVENTBRITE_ORGANIZATION_ID` | Optional for dry-run; **required** for live create | From `/users/me/organizations/` |
| `EVENTBRITE_CURRENCY` | Optional (`USD`) | ISO 4217 for create-event |
| `EVENTBRITE_PUBLISH_ON_CREATE` | Optional (`false`) | If `true`, live authorized submit also calls publish |
| Other platform tokens | Optional | Other adapters still `NEEDS_VERIFICATION` |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | For Sheets tracking | Share the sheet with the service account as Editor |
| `GOOGLE_SHEETS_CREDENTIALS_JSON` or `GOOGLE_APPLICATION_CREDENTIALS` | For Sheets tracking | Service-account key. Never commit it |

Eventbrite remains `NEEDS_VERIFICATION` until a human confirms live create. Do not set Eventbrite Fly secrets or mark `READY` without explicit live approval.

## Client config (after you have a URL)

Cursor / Claude remote MCP:

```json
{
  "mcpServers": {
    "event-off-page-seo": {
      "url": "https://YOUR_HOST/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

Exact client UI fields vary; always use HTTPS and the Bearer token. ChatGPT custom MCP support depends on plan/product surface.
