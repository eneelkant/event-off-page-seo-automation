# Eventbrite local setup (human credentials)

See also `docs/EVENTBRITE.md` (API details) and the project-store mirror of this guide.

**Adapter registry status:** `NEEDS_VERIFICATION` until a human-approved live create succeeds. Dry-run default. No Fly/deploy in this setup path.

## Prerequisites already in the repo

| Check | Expected |
| --- | --- |
| `.gitignore` | Ignores `.env`, `.env.local`, `.env.*.local` |
| `.env.example` | Empty placeholders for `EVENTBRITE_API_TOKEN` and `EVENTBRITE_ORGANIZATION_ID` |
| Safety defaults | `DRY_RUN_DEFAULT=true`, `REQUIRE_PUBLICATION_AUTHORIZATION=true`, `EVENTBRITE_PUBLISH_ON_CREATE=false` |

## Step-by-step: create local `.env` (you supply credentials)

The agent / CI must **not** invent, fetch, or print your Eventbrite token.

1. From the repo root, copy the template without clobbering an existing file:

   ```bash
   cp -n .env.example .env
   ```

2. Edit `.env` only on your machine (editor or password manager paste). Do not paste secrets into chat, issues, or PRs.

3. Sign in to Eventbrite and open [API Keys](https://www.eventbrite.com/platform/api-keys/). Copy the **private token** into:

   ```bash
   EVENTBRITE_API_TOKEN=
   ```

4. Resolve **organization ID** yourself (token stays local):

   ```bash
   # after exporting EVENTBRITE_API_TOKEN in your shell, or substitute locally
   curl -sS -H "Authorization: Bearer $EVENTBRITE_API_TOKEN" \
     https://www.eventbriteapi.com/v3/users/me/organizations/
   ```

   Set:

   ```bash
   EVENTBRITE_ORGANIZATION_ID=
   ```

5. Leave these until you intentionally run a live draft:

   ```bash
   DRY_RUN_DEFAULT=true
   REQUIRE_PUBLICATION_AUTHORIZATION=true
   EVENTBRITE_PUBLISH_ON_CREATE=false
   EVENTBRITE_CURRENCY=USD
   ```

6. Verify ignore: `git check-ignore -v .env` → should cite `.gitignore`. Never commit `.env`.

7. Dry-run only: use MCP `submit_event` with `dry_run=true` (or keep `DRY_RUN_DEFAULT=true`). No real Eventbrite create.

## When is config ready for a human-approved live test?

**Ready for live draft test** only when:

- `.env` exists locally with a real `EVENTBRITE_API_TOKEN` and `EVENTBRITE_ORGANIZATION_ID`
- You still keep `EVENTBRITE_PUBLISH_ON_CREATE=false` unless you want publish
- You explicitly call submit with `dry_run=false` **and** `authorize_publication=true`

Until those credentials exist on the machine that will call the API, config is **dry-run / mocked only**.

## After a successful live draft (follow-up)

1. Confirm the draft in Eventbrite UI.
2. Optionally publish via API/UI if desired.
3. Open a follow-up change to set `automation_status` to `READY` and `last_verified_at` — not before live proof.
