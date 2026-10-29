# Client setup

## Production remote MCP (Cursor) — recommended

Hosted endpoint: `https://event-seo-mcp.fly.dev/mcp`

Project config is in [`.cursor/mcp.json`](../.cursor/mcp.json) (safe to commit — uses env interpolation, no hardcoded token):

```json
{
  "mcpServers": {
    "event-off-page-seo": {
      "url": "https://event-seo-mcp.fly.dev/mcp",
      "headers": {
        "Authorization": "Bearer ${env:MCP_AUTH_TOKEN}"
      }
    }
  }
}
```

Cursor officially resolves `${env:NAME}` in `url` and `headers` ([Cursor MCP docs](https://cursor.com/docs/mcp)).

### Make the token available to Cursor

1. Export in your shell (do not commit):
   ```bash
   export MCP_AUTH_TOKEN="$(cat /path/to/secret)"   # or your password manager
   ```
2. **Launch Cursor from that same shell** (`cursor .`) so the desktop process inherits the variable.
3. If you start Cursor from a desktop icon, shell RC exports may not apply. Then either:
   - set `MCP_AUTH_TOKEN` in a system/user environment that GUI apps see, or
   - use the **stdio proxy fallback** below.

### Manual Cursor UI steps

1. Open this repo in Cursor.
2. Ensure `.cursor/mcp.json` is present (committed) and `MCP_AUTH_TOKEN` is in the environment Cursor inherits.
3. Open **Customize → MCP** (or Settings → MCP) and confirm `event-off-page-seo` appears and is enabled.
4. Check **Output → MCP Logs** if the server fails to connect (401 usually means missing/unresolved token).
5. In chat, ask to run `health_check` (read-only). Do not run submit tools unless intentional.

### Stdio proxy fallback (when header `${env:…}` does not resolve)

Cursor staff note that remote header interpolation can fail if the GUI process lacks the env var; stdio `env` interpolation still works because Cursor launches the command ([forum](https://forum.cursor.com/t/config-interpolation-env-name-not-working-in-headers-for-remote-mcp-servers/156069)).

Use the `event-off-page-seo-stdio-proxy` entry from `.cursor/mcp.json.example`, or:

```json
{
  "mcpServers": {
    "event-off-page-seo": {
      "command": "python",
      "args": ["${workspaceFolder}/scripts/cursor_remote_mcp_proxy.py"],
      "env": {
        "MCP_REMOTE_URL": "https://event-seo-mcp.fly.dev/mcp",
        "MCP_AUTH_TOKEN": "${env:MCP_AUTH_TOKEN}"
      }
    }
  }
}
```

Requires the project venv on `PATH` (`python` with `mcp` installed) or point `command` at `.venv/bin/python`.

## Local stdio (no remote host)

See `.cursor/mcp.json.example` → `event-off-page-seo-stdio-local`.

```bash
MCP_TRANSPORT=stdio python -m event_seo_mcp.server
```

## Auth reminder

- Production `/mcp` requires `Authorization: Bearer <MCP_AUTH_TOKEN>`.
- `GET /healthz` is public for probes.
- Never commit real tokens. Prefer `${env:MCP_AUTH_TOKEN}`.
- Dry-run remains the server default.

## Verify without Cursor UI

```bash
export MCP_AUTH_TOKEN=...   # from your secret store
python scripts/verify_remote_mcp.py
```

This checks `/healthz`, rejects unauthenticated `/mcp`, lists tools, and calls **only** `health_check`.
