"""CSV/JSON campaign reports and KPI targets."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from event_seo_mcp.database.repository import Repository

STRATEGY_TARGETS = {
    "event_directory_listings": "20-30",
    "industry_calendar_listings": "10-15",
    "guest_posts": "5-10",
    "partner_promotions": "10-20",
    "backlinks": "50-75",
    "linkedin_shares_interactions": "100+",
    "lead_conversion_rate": "3-8%",
    "organic_traffic_increase": "50%",
    "note": "Strategy targets from the Event SEO plan — not guaranteed outcomes.",
}


class CampaignReporter:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def campaign_report(self, event_id: str | None = None) -> dict[str, Any]:
        jobs = self.repo.list_jobs(event_id=event_id)
        platforms = self.repo.list_platforms()
        by_state: dict[str, int] = {}
        for job in jobs:
            by_state[job.state.value] = by_state.get(job.state.value, 0) + 1

        backlinks = []
        if event_id:
            backlinks = self.repo.list_backlink_checks(event_id)
        else:
            # aggregate limited
            rows = self.repo.db.fetchall("SELECT * FROM backlink_checks ORDER BY checked_at DESC LIMIT 500")
            backlinks = [dict(r) for r in rows]

        verified = sum(1 for b in backlinks if b.get("result") == "verified_link_found" or b.get("link_found") == 1)
        missing = sum(1 for b in backlinks if b.get("result") == "verified_missing_link")

        distinct = [p for p in platforms if not p.is_workflow]
        entries = [p for p in platforms if p.is_workflow or p.platform_id != "linkedin"]
        workflows = [p for p in platforms if p.is_workflow]
        by_category: dict[str, int] = {}
        for p in entries:
            by_category[p.category] = by_category.get(p.category, 0) + 1

        return {
            "event_id": event_id,
            "planned_submissions": len(jobs),
            "eligible_platforms": sum(1 for p in entries if p.automation_status != "BLOCKED"),
            "platforms_total": len(platforms),
            "registry": {
                "distinct_platforms": len(distinct),
                "registry_entries": len(entries),
                "linkedin_workflows": len(workflows),
                "categories": by_category,
                "expected": {
                    "distinct_platforms": 30,
                    "registry_entries": 35,
                    "linkedin_workflows": 6,
                    "categories": 7,
                },
            },
            "successfully_submitted": by_state.get("SUBMITTED", 0) + by_state.get("PENDING_REVIEW", 0),
            "published_listings": by_state.get("PUBLISHED", 0),
            "pending_approvals": by_state.get("AWAITING_APPROVAL", 0),
            "failed_attempts": by_state.get("FAILED", 0),
            "blocked": by_state.get("BLOCKED", 0),
            "duplicates": by_state.get("DUPLICATE", 0),
            "jobs_by_state": by_state,
            "verified_backlinks": verified,
            "missing_or_broken_backlinks": missing,
            "referral_traffic": None,
            "registrations_conversions": None,
            "analytics_note": "Traffic/conversion metrics are null unless connected analytics data is provided. Never fabricated.",
            "strategy_targets": STRATEGY_TARGETS,
            "dry_run_default": True,
        }

    def export(self, event_id: str | None = None, fmt: str = "json") -> dict[str, Any]:
        report = self.campaign_report(event_id)
        jobs = [j.model_dump(mode="json") for j in self.repo.list_jobs(event_id=event_id)]
        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.DictWriter(
                buffer,
                fieldnames=[
                    "job_id",
                    "event_id",
                    "platform_id",
                    "state",
                    "dry_run",
                    "published_url",
                    "idempotency_key",
                ],
            )
            writer.writeheader()
            for job in jobs:
                writer.writerow(
                    {
                        "job_id": job["job_id"],
                        "event_id": job["event_id"],
                        "platform_id": job["platform_id"],
                        "state": job["state"],
                        "dry_run": job["dry_run"],
                        "published_url": job.get("published_url"),
                        "idempotency_key": job["idempotency_key"],
                    }
                )
            return {"format": "csv", "report": report, "csv": buffer.getvalue()}
        return {"format": "json", "report": report, "jobs": jobs, "json": json.dumps(report, indent=2)}
