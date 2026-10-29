# Architecture

## Overview

The Event Off-Page SEO Automation MCP accepts event records, validates them, looks up a platform registry, generates platform-specific content, routes work through adapters, records submission jobs, and verifies backlinks.

```
Event Input → Validation → Platform Discovery/Eligibility
    → AI Content Generation → Orchestrator → Capability Router
        → API / Playwright / optional frameworks
    → Submission Verification → SQLite tracking → Reports
```

## Core packages (`src/event_seo_mcp`)

| Area | Role |
| --- | --- |
| `server.py` | MCP entrypoint (`stdio` or Streamable HTTP) |
| `tools/` | Strict MCP tool handlers |
| `schemas/` | Pydantic models for events, platforms, content, jobs |
| `database/` | SQLite schema + repository |
| `providers/` | OpenAI / Anthropic / Gemini / template |
| `adapters/` | Per-category submission adapters |
| `orchestration/` | Capability registry + dry-run-safe orchestrator |
| `integrations/` | Soft-fail Agno, Crawl4AI, browser-use, Skyvern |
| `browser/` | Playwright helper with human-verification stops |
| `tracking/` | Backlink verifier |
| `reporting/` | JSON/CSV campaign reports |
| `security/` | Secret redaction + bind/auth guards |
| `integrations/google_sheets/` | Sheets API targets, submission tracking, Gemini HTTP bridge |

## Design rules

1. Prefer official APIs over browser automation.
2. Optional frameworks must soft-fail; the MCP must start without them.
3. Do not invent submission URLs/APIs; mark platforms `NEEDS_VERIFICATION`.
4. Never silently switch from dry-run/preview to live publication.
5. Never claim `PUBLISHED` without a verified public listing URL or equivalent receipt.
6. Never bypass CAPTCHA, MFA, paywalls, or bot detection.
