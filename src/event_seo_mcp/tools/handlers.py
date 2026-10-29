"""Business logic backing MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from event_seo_mcp.database.repository import Repository
from event_seo_mcp.discovery.platform_discovery import (
    discover_platform,
    load_platforms_file,
    registry_stats,
    sync_platforms_to_db,
)
from event_seo_mcp.orchestration.capability_registry import CapabilityRegistry
from event_seo_mcp.orchestration.orchestrator import Orchestrator
from event_seo_mcp.orchestration.publishing_rules import PublishingRulesEngine, credential_presence
from event_seo_mcp.reporting.campaign import CampaignReporter
from event_seo_mcp.schemas.content import ContentType, GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.settings import Settings, get_settings
from event_seo_mcp.tracking.backlinks import BacklinkVerifier
from event_seo_mcp.integrations.google_sheets.service import SheetsWorkflow
from event_seo_mcp import __version__


class ToolService:
    def __init__(self, repo: Repository, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.repo = repo
        self.orchestrator = Orchestrator(repo, self.settings)
        self.capabilities = CapabilityRegistry(self.settings)
        self.reporter = CampaignReporter(repo)
        self.backlinks = BacklinkVerifier(repo, self.settings)
        self.sheets = SheetsWorkflow(repo, self.settings, self.orchestrator)
        sync_platforms_to_db(repo, self.settings)

    def health_check(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "transport_default": self.settings.mcp_transport,
            "database": str(self.settings.resolved_database_path),
            "dry_run_default": self.settings.dry_run_default,
            "adapters": self.capabilities.adapter_health(),
            "integrations": self.capabilities.full_health()["integrations"],
            "providers": self.capabilities.full_health()["providers"],
        }

    def list_platforms(
        self, category: str | None = None, *, include_workflows: bool = False
    ) -> dict[str, Any]:
        """List distinct platforms (30). Set include_workflows for DB rows including workflows."""
        if include_workflows:
            platforms = self.repo.list_platforms()
        else:
            platforms = self.repo.list_distinct_platforms()
        if category:
            platforms = [p for p in platforms if p.category == category]
        return {
            "count": len(platforms),
            "include_workflows": include_workflows,
            "platforms": [p.model_dump(mode="json") for p in platforms],
        }

    def list_registry_entries(self, category: str | None = None) -> dict[str, Any]:
        entries = self.repo.list_registry_entries()
        if category:
            entries = [e for e in entries if e.category == category]
        return {
            "count": len(entries),
            "expected": 35,
            "entries": [e.model_dump(mode="json") for e in entries],
        }

    def list_workflows(self, parent_platform_id: str | None = "linkedin") -> dict[str, Any]:
        workflows = self.repo.list_workflows(parent_platform_id=parent_platform_id)
        return {
            "count": len(workflows),
            "parent_platform_id": parent_platform_id,
            "workflows": [w.model_dump(mode="json") for w in workflows],
        }

    def get_registry_stats(self) -> dict[str, Any]:
        stats = registry_stats(self.settings.resolved_platforms_path)
        self.repo.save_registry_snapshot(
            version=str(stats.get("version")),
            totals=stats.get("totals") or {},
            validation=stats.get("validation") or {},
        )
        return stats

    def get_platform_details(self, platform_id: str) -> dict[str, Any]:
        platform = self.repo.get_platform(platform_id)
        if not platform:
            return {"error": "not_found", "platform_id": platform_id}
        selection = self.capabilities.select_adapter(platform)
        return {
            "platform": platform.model_dump(mode="json"),
            "adapter_selection": selection,
            "credentials": credential_presence(platform),
            "research": platform.research.model_dump(mode="json"),
        }

    def get_credential_status(self, platform_id: str | None = None) -> dict[str, Any]:
        if platform_id:
            platform = self.repo.get_platform(platform_id)
            if not platform:
                return {"error": "not_found", "platform_id": platform_id}
            return {"count": 1, "credentials": [credential_presence(platform)]}
        items = [credential_presence(p) for p in self.repo.list_registry_entries()]
        return {
            "count": len(items),
            "configured_count": sum(1 for i in items if i["configured"]),
            "credentials": items,
        }

    def evaluate_publishing_rules(
        self,
        platform_id: str,
        event_id: str | None = None,
        *,
        dry_run: bool | None = None,
        authorize_publication: bool = False,
    ) -> dict[str, Any]:
        platform = self.repo.get_platform(platform_id)
        if not platform:
            return {"error": "not_found", "platform_id": platform_id}
        event = None
        if event_id:
            event = self.repo.get_event(event_id)
            if not event:
                return {"error": "event_not_found", "event_id": event_id}
        if dry_run is None:
            dry_run = self.settings.dry_run_default
        engine = PublishingRulesEngine(self.settings)
        decision = engine.evaluate(
            event, platform, dry_run=dry_run, authorize_publication=authorize_publication
        )
        evaluation_id = self.repo.save_publishing_rule_evaluation(
            platform_id=platform_id,
            event_id=event_id,
            dry_run=decision.dry_run,
            authorize_publication=authorize_publication,
            allowed=decision.allowed,
            eligible_for_live=decision.eligible_for_live,
            result=decision.as_dict(),
        )
        return {"evaluation_id": evaluation_id, **decision.as_dict()}

    async def discover_platform_submission(self, platform_id: str) -> dict[str, Any]:
        platform = self.repo.get_platform(platform_id)
        if not platform:
            return {"error": "not_found", "platform_id": platform_id}
        return await discover_platform(platform, self.settings)

    def validate_event(self, event: dict[str, Any]) -> dict[str, Any]:
        try:
            record = EventRecord.model_validate(event)
            return {"valid": True, "event": record.model_dump(mode="json")}
        except Exception as exc:  # noqa: BLE001
            return {"valid": False, "error": str(exc)}

    def create_event(self, event: dict[str, Any]) -> dict[str, Any]:
        record = EventRecord.model_validate(event)
        self.repo.upsert_event(record)
        return {"created": True, "event": record.model_dump(mode="json")}

    def get_event(self, event_id: str) -> dict[str, Any]:
        event = self.repo.get_event(event_id)
        if not event:
            # try example fixture
            example = self.settings.repo_root / "data/events/example_event.json"
            if event_id == "evt-sample-ai-summit-2026" and example.exists():
                event = EventRecord.model_validate_json(example.read_text(encoding="utf-8"))
                self.repo.upsert_event(event)
            else:
                return {"error": "not_found", "event_id": event_id}
        return {"event": event.model_dump(mode="json")}

    def _require_event(self, event_id: str) -> EventRecord:
        result = self.get_event(event_id)
        if "error" in result:
            raise KeyError(result["error"])
        return EventRecord.model_validate(result["event"])

    def generate_platform_content(
        self,
        event_id: str,
        platform_id: str,
        content_type: str,
        extra_instructions: str | None = None,
    ) -> dict[str, Any]:
        event = self._require_event(event_id)
        platform = self.repo.get_platform(platform_id)
        if not platform:
            return {"error": "platform_not_found", "platform_id": platform_id}
        content = self.orchestrator.generate_content(
            event, platform, content_type, extra_instructions=extra_instructions  # type: ignore[arg-type]
        )
        return {"content": content.model_dump(mode="json")}

    def generate_campaign_content(self, event_id: str, platform_ids: list[str] | None = None) -> dict[str, Any]:
        event = self._require_event(event_id)
        platforms = self.repo.list_registry_entries()
        if platform_ids:
            platforms = [p for p in platforms if p.platform_id in platform_ids]
        items = []
        for platform in platforms:
            ctype = platform.supported_content_types[0] if platform.supported_content_types else "event_directory_description"
            content = self.orchestrator.generate_content(event, platform, ctype)  # type: ignore[arg-type]
            items.append(content.model_dump(mode="json"))
        return {"count": len(items), "content": items}

    def validate_generated_content(self, content: dict[str, Any]) -> dict[str, Any]:
        try:
            parsed = GeneratedContent.model_validate(content)
        except Exception as exc:  # noqa: BLE001
            return {"valid": False, "error": str(exc)}
        platform = self.repo.get_platform(parsed.platform_id)
        validated = self.orchestrator.validate_content(parsed, platform)
        return {
            "valid": validated.validation_status == "valid",
            "content": validated.model_dump(mode="json"),
        }

    def preview_submission(self, event_id: str, platform_id: str, content_id: str | None = None) -> dict[str, Any]:
        event = self._require_event(event_id)
        platform = self.repo.get_platform(platform_id)
        if not platform:
            return {"error": "platform_not_found"}
        if content_id:
            content = self.repo.get_content(content_id)
            if not content:
                return {"error": "content_not_found"}
        else:
            ctype = platform.supported_content_types[0] if platform.supported_content_types else "event_directory_description"
            content = self.orchestrator.generate_content(event, platform, ctype)  # type: ignore[arg-type]
        return self.orchestrator.preview_submission(event, platform, content)

    def check_submission_eligibility(self, event_id: str, platform_id: str) -> dict[str, Any]:
        event = self._require_event(event_id)
        platform = self.repo.get_platform(platform_id)
        if not platform:
            return {"error": "platform_not_found"}
        return self.orchestrator.check_eligibility(event, platform)

    def submit_event(
        self,
        event_id: str,
        platform_id: str,
        *,
        content_id: str | None = None,
        dry_run: bool | None = None,
        authorize_publication: bool = False,
    ) -> dict[str, Any]:
        event = self._require_event(event_id)
        platform = self.repo.get_platform(platform_id)
        if not platform:
            return {"error": "platform_not_found"}
        if content_id:
            content = self.repo.get_content(content_id)
            if not content:
                return {"error": "content_not_found"}
        else:
            ctype = platform.supported_content_types[0] if platform.supported_content_types else "event_directory_description"
            content = self.orchestrator.generate_content(event, platform, ctype)  # type: ignore[arg-type]
        return self.orchestrator.submit_event(
            event,
            platform,
            content,
            dry_run=dry_run,
            authorize_publication=authorize_publication,
        )

    def submit_campaign(
        self,
        event_id: str,
        platform_ids: list[str] | None = None,
        *,
        dry_run: bool | None = None,
        authorize_publication: bool = False,
    ) -> dict[str, Any]:
        if dry_run is None:
            dry_run = True
        if not dry_run and not authorize_publication:
            return {
                "refused": True,
                "message": "Campaign live submit requires authorize_publication=true; defaulting refusal.",
            }
        platforms = self.repo.list_registry_entries()
        if platform_ids:
            platforms = [p for p in platforms if p.platform_id in platform_ids]
        results = []
        for platform in platforms:
            results.append(
                self.submit_event(
                    event_id,
                    platform.platform_id,
                    dry_run=dry_run,
                    authorize_publication=authorize_publication,
                )
            )
        return {"count": len(results), "results": results, "dry_run": dry_run}

    def get_submission_status(self, job_id: str) -> dict[str, Any]:
        job = self.repo.get_job(job_id)
        if not job:
            return {"error": "not_found", "job_id": job_id}
        return {"job": job.model_dump(mode="json")}

    def list_submission_jobs(self, event_id: str | None = None, platform_id: str | None = None) -> dict[str, Any]:
        jobs = self.repo.list_jobs(event_id=event_id, platform_id=platform_id)
        return {"count": len(jobs), "jobs": [j.model_dump(mode="json") for j in jobs]}

    def verify_backlink(
        self,
        event_id: str,
        published_url: str,
        landing_page_url: str | None = None,
        html_fixture: str | None = None,
    ) -> dict[str, Any]:
        event = self._require_event(event_id)
        landing = landing_page_url or str(event.landing_page_url)
        return self.backlinks.verify(
            event_id=event_id,
            published_url=published_url,
            landing_page_url=landing,
            html_override=html_fixture,
        )

    def verify_event_backlinks(self, event_id: str) -> dict[str, Any]:
        event = self._require_event(event_id)
        results = self.backlinks.verify_event(event_id, str(event.landing_page_url))
        return {"event_id": event_id, "count": len(results), "results": results}

    def get_campaign_report(self, event_id: str | None = None) -> dict[str, Any]:
        return self.reporter.campaign_report(event_id)

    def export_submission_report(self, event_id: str | None = None, format: str = "json") -> dict[str, Any]:
        fmt = format.lower().strip()
        if fmt not in {"json", "csv"}:
            return {"error": "format must be json or csv"}
        return self.reporter.export(event_id, fmt=fmt)

    def check_adapter_health(self) -> dict[str, Any]:
        return self.capabilities.full_health()

    def list_submission_targets(self) -> dict[str, Any]:
        return self.sheets.list_targets()

    def submit_event_to_site(
        self,
        *,
        event_name: str,
        event_description: str,
        landing_page_url: str,
        event_datetime: str,
        target_site: str,
        registration_url: str,
        location: str | None = None,
        virtual_event_details: str | None = None,
        dry_run: bool | None = True,
        authorize_publication: bool = False,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        return self.sheets.submit_event_to_site(
            event_name=event_name,
            event_description=event_description,
            landing_page_url=landing_page_url,
            event_datetime=event_datetime,
            target_site=target_site,
            registration_url=registration_url,
            location=location,
            virtual_event_details=virtual_event_details,
            dry_run=dry_run,
            authorize_publication=authorize_publication,
            event_id=event_id,
        )

    def record_publication_update(
        self,
        *,
        event_id: str,
        publication_status: str,
        site_name: str | None = None,
        website: str | None = None,
        published_url: str | None = None,
        published_date: str | None = None,
        external_submission_id: str | None = None,
    ) -> dict[str, Any]:
        return self.sheets.record_publication_update(
            event_id=event_id,
            publication_status=publication_status,
            site_name=site_name,
            website=website,
            published_url=published_url,
            published_date=published_date,
            external_submission_id=external_submission_id,
        )

    def load_example_event_if_needed(self) -> None:
        example = self.settings.repo_root / "data/events/example_event.json"
        if example.exists() and not self.repo.get_event("evt-sample-ai-summit-2026"):
            event = EventRecord.model_validate_json(example.read_text(encoding="utf-8"))
            self.repo.upsert_event(event)
