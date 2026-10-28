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
| `MCP_AUTH_TOKEN` | **Yes** | Bearer secret for `/mcp` |
| `MCP_ALLOW_REMOTE_BIND` | Yes (`true`) | With `MCP_HTTP_HOST=0.0.0.0` |
| `DRY_RUN_DEFAULT` | Recommended `true` | Prevents accidental live publishes |
| `AI_PROVIDER` + provider key | For LLM content | `template` works offline |
| `EVENTBRITE_API_TOKEN` etc. | Optional | Live adapters still `NEEDS_VERIFICATION` |

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
