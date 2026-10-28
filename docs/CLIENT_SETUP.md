# Client setup

## Local stdio (Cursor / Claude Desktop)

1. Create a virtualenv and install the package.
2. Copy `.env.example` → `.env` and set `MCP_TRANSPORT=stdio`.
3. Point the client at:

```bash
python -m event_seo_mcp.server
```

See `.cursor/mcp.json.example` for a Cursor-ready snippet (`uv run` recommended).

## Streamable HTTP

```bash
export MCP_TRANSPORT=streamable-http
export MCP_HTTP_HOST=127.0.0.1
export MCP_HTTP_PORT=8000
python -m event_seo_mcp.server --http
```

Clients connect to `http://127.0.0.1:8000/mcp`.

For remote deployment:

- Set `MCP_ALLOW_REMOTE_BIND=true`
- Set a strong `MCP_AUTH_TOKEN`
- Terminate TLS at a reverse proxy
- Do not expose write-capable MCP without authentication

## ChatGPT / remote MCP notes

- Provide a hosted Streamable HTTP endpoint with auth.
- Not every ChatGPT plan/interface supports unrestricted write-capable custom MCP apps.
- Prefer dry-run tools until the client path is confirmed.

## Gemini

- Gemini consumer apps may not connect directly to arbitrary custom MCP servers.
- Supported route in this project: configure `AI_PROVIDER=gemini` for content generation, and/or call the same MCP tools from an MCP-compatible client that Gemini can use via tool-calling.
- Do not assume the Gemini consumer app can attach this server natively.

## Claude remote

- Use Streamable HTTP with authentication when deploying remotely.
- Keep publication tools dry-run by default.


## Production Streamable HTTP auth

Production deployments require `MCP_AUTH_TOKEN`. Clients must send:

```
Authorization: Bearer <MCP_AUTH_TOKEN>
```

`GET /healthz` is unauthenticated for load-balancer probes. The MCP endpoint `/mcp` rejects missing/invalid tokens with HTTP 401.

See `docs/DEPLOY.md` for Fly.io / Docker hosting steps.
