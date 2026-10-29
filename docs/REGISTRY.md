# Off-page SEO website registry

Version **0.2.0** of `config/platforms.json` is the Complete Off-Page SEO Website Registry.

## Totals (Definition of Done)

| Metric | Expected |
| --- | --- |
| Registry entries (submit targets) | **35** |
| Distinct platforms | **30** |
| Categories | **7** |
| LinkedIn | **1 platform + 6 workflows** |

Formula: 29 non-LinkedIn platforms + 6 LinkedIn workflows = **35** registry entries; LinkedIn parent + 29 = **30** distinct platforms.

## Categories

1. `event_directory`
2. `ai_tech_calendar`
3. `partner_marketing`
4. `industry_community`
5. `digital_pr`
6. `guest_posting`
7. `linkedin_thought_leadership`

## LinkedIn model

- Distinct platform: `linkedin`
- Workflows (registry entries / submit IDs):  
  `linkedin_speaker_announcement`, `linkedin_customer_success`, `linkedin_industry_research`, `linkedin_agenda_highlights`, `linkedin_executive_poll`, `linkedin_partner_spotlight`
- Do not submit against the parent `linkedin` id — use a workflow entry.

## Research & honesty rules

- Every entry includes `research.sources` and `research.unknown_fields`.
- Unknown homepage/submission/API fields stay **`null`**.
- `automation_status` stays **`NEEDS_VERIFICATION`** until human live proof (never invent `READY` or URLs/APIs).

## Credential metadata

Registry stores **env var names only** (see `.env.example` placeholders). Tools expose presence via `get_credential_status` — never secret values.

## Publishing rules engine

`evaluate_publishing_rules` / orchestrator gates:

1. Required event fields  
2. Platform not `BLOCKED`  
3. Self-promo restricted communities (live blocked)  
4. Dry-run default (no network publish)  
5. Live requires `authorize_publication=true`  
6. `NEEDS_VERIFICATION` live only with explicit human authorization  
7. Credentials present when `required_for_live`  
8. LinkedIn parent is not a submit target  

Evaluations are persisted in SQLite (`publishing_rule_evaluations`).

## MCP tools (extensions)

Existing tools preserved. Added:

- `list_registry_entries`
- `list_workflows`
- `get_registry_stats`
- `get_credential_status`
- `evaluate_publishing_rules`
- `list_platforms` now defaults to **distinct** platforms (30)

Eventbrite adapter and dry-run defaults are unchanged.
