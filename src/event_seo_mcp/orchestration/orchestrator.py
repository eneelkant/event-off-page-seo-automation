"""Submission orchestration with dry-run safety and idempotency."""

from __future__ import annotations

from typing import Any

from event_seo_mcp.adapters.registry import get_adapter
from event_seo_mcp.database.repository import Repository
from event_seo_mcp.orchestration.capability_registry import CapabilityRegistry
from event_seo_mcp.orchestration.publishing_rules import PublishingRulesEngine
from event_seo_mcp.providers.factory import generate_with_failover
from event_seo_mcp.schemas.content import ContentType, GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.schemas.submission import JobState
from event_seo_mcp.settings import Settings, get_settings


class Orchestrator:
    def __init__(self, repo: Repository, settings: Settings | None = None) -> None:
        self.repo = repo
        self.settings = settings or get_settings()
        self.capabilities = CapabilityRegistry(self.settings)
        self.publishing_rules = PublishingRulesEngine(self.settings)

    def generate_content(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content_type: ContentType,
        *,
        extra_instructions: str | None = None,
        persist: bool = True,
    ) -> GeneratedContent:
        content = generate_with_failover(
            self.settings,
            event,
            platform,
            content_type,
            extra_instructions=extra_instructions,
        )
        content = self.validate_content(content, platform)
        if persist:
            content = self.repo.save_content(content)
        return content

    def validate_content(
        self, content: GeneratedContent, platform: PlatformRecord | None = None
    ) -> GeneratedContent:
        errors: list[str] = []
        if not content.title.strip():
            errors.append("title empty")
        if not content.body.strip():
            errors.append("body empty")
        content.character_count = len(content.body)
        if content.content_type in {"linkedin_post", "community_post"} and len(content.body) > 3000:
            errors.append("body exceeds soft limit 3000 for social posts")
        if platform and content.content_type not in platform.supported_content_types:
            errors.append(
                f"content_type {content.content_type} not in platform.supported_content_types"
            )
        content.validation_status = "invalid" if errors else "valid"
        return content

    def preview_submission(
        self, event: EventRecord, platform: PlatformRecord, content: GeneratedContent
    ) -> dict[str, Any]:
        selection = self.capabilities.select_adapter(platform)
        adapter = get_adapter(selection["adapter_name"])
        errors = adapter.validate_submission(event, platform, content)
        prepared = adapter.prepare_submission(event, platform, content)
        return {
            "eligible": not errors and platform.automation_status != "BLOCKED",
            "errors": errors,
            "adapter_selection": selection,
            "prepared": prepared,
            "dry_run_default": self.settings.dry_run_default,
            "platform_status": platform.automation_status,
        }

    def check_eligibility(self, event: EventRecord, platform: PlatformRecord) -> dict[str, Any]:
        missing = event.missing_fields_for(platform.required_fields)
        selection = self.capabilities.select_adapter(platform)
        dry = self.publishing_rules.evaluate(event, platform, dry_run=True, authorize_publication=False)
        live = self.publishing_rules.evaluate(
            event, platform, dry_run=False, authorize_publication=True
        )
        blocked_reasons: list[str] = []
        if platform.automation_status == "BLOCKED":
            blocked_reasons.append("platform_blocked")
        if platform.automation_status == "NEEDS_VERIFICATION":
            blocked_reasons.append("platform_needs_verification_for_live")
        if missing:
            blocked_reasons.append("missing_required_fields")
        if live.missing_credentials:
            blocked_reasons.append("missing_credentials")
        return {
            "eligible_for_dry_run": dry.eligible_for_dry_run,
            "eligible_for_live": live.eligible_for_live,
            "missing_fields": missing,
            "blocked_reasons": blocked_reasons,
            "approval_required": platform.approval_required,
            "adapter_selection": selection,
            "automation_status": platform.automation_status,
            "publishing_rules_dry_run": dry.as_dict(),
            "publishing_rules_live_authorized": live.as_dict(),
            "credentials": {
                "required_env_vars": platform.credentials.env_vars,
                "missing_for_live": live.missing_credentials,
                "values_redacted": True,
            },
        }

    def submit_event(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content: GeneratedContent,
        *,
        dry_run: bool | None = None,
        authorize_publication: bool = False,
    ) -> dict[str, Any]:
        if dry_run is None:
            dry_run = self.settings.dry_run_default

        decision = self.publishing_rules.evaluate(
            event,
            platform,
            dry_run=dry_run,
            authorize_publication=authorize_publication,
        )
        # Never silently switch from preview/dry-run to live execution.
        if not dry_run and not decision.allowed:
            return {
                "duplicate": False,
                "refused": True,
                "message": "; ".join(decision.reasons),
                "dry_run": False,
                "publishing_rules": decision.as_dict(),
            }

        idem = Repository.make_idempotency_key(
            event.event_id, platform.platform_id, content.content_type
        )
        existing = self.repo.find_job_by_idempotency(idem)
        terminal = {
            JobState.SUBMITTED,
            JobState.PENDING_REVIEW,
            JobState.PUBLISHED,
            JobState.DUPLICATE,
        }
        if existing and existing.state in terminal and existing.dry_run == dry_run and not dry_run:
            dup = self.repo.transition_job(existing.job_id, JobState.DUPLICATE) if existing.state != JobState.DUPLICATE else existing
            return {
                "duplicate": True,
                "job": dup.model_dump(mode="json"),
                "message": "Duplicate submission prevented by idempotency key.",
            }
        if existing and existing.state in terminal and not dry_run and not existing.dry_run:
            return {
                "duplicate": True,
                "job": existing.model_dump(mode="json"),
                "message": "Duplicate submission prevented by idempotency key.",
            }

        # Separate idempotency for dry-run vs live to allow dry-run then later approved live.
        if dry_run:
            idem = f"{idem}::dry_run"
            existing = self.repo.find_job_by_idempotency(idem)

        job = existing or self.repo.create_job(
            event_id=event.event_id,
            platform_id=platform.platform_id,
            idempotency_key=idem,
            state=JobState.READY,
            dry_run=dry_run,
            content_id=content.content_id,
        )

        if job.state in {JobState.SUBMITTED, JobState.PUBLISHED, JobState.DUPLICATE} and dry_run:
            return {
                "duplicate": True,
                "job": job.model_dump(mode="json"),
                "message": "Dry-run already recorded for this event/platform/content_type.",
            }

        selection = self.capabilities.select_adapter(platform)
        adapter = get_adapter(selection["adapter_name"])

        if job.state == JobState.READY:
            job = self.repo.transition_job(job.job_id, JobState.CONTENT_PREPARED)

        if platform.approval_required and not dry_run and not authorize_publication:
            job = self.repo.transition_job(job.job_id, JobState.AWAITING_APPROVAL)
            return {
                "duplicate": False,
                "job": job.model_dump(mode="json"),
                "message": "Awaiting explicit approval before publication.",
                "adapter_selection": selection,
            }

        if job.state in {JobState.CONTENT_PREPARED, JobState.AWAITING_APPROVAL, JobState.FAILED}:
            job = self.repo.transition_job(job.job_id, JobState.SUBMITTING)
        elif job.state != JobState.SUBMITTING:
            job = self.repo.transition_job(job.job_id, JobState.SUBMITTING)

        result = adapter.submit(
            event,
            platform,
            content,
            dry_run=dry_run,
            authorize_publication=authorize_publication and not dry_run,
        )
        result = adapter.verify_submission(result)
        evidence = adapter.capture_evidence(result)
        attempt_no = self.repo.next_attempt_number(job.job_id)
        self.repo.add_attempt(
            job.job_id,
            attempt_number=attempt_no,
            status=result.state,
            dry_run=result.dry_run,
            adapter_name=adapter.name,
            message=result.message,
            response_summary=result.response_summary,
            error_code=result.error_code,
            evidence_paths=evidence,
        )

        final_state = result.state
        if dry_run and final_state in {JobState.CONTENT_PREPARED, JobState.AWAITING_APPROVAL}:
            # Dry-run completed successfully without publishing.
            final_state = JobState.SUBMITTED

        job = self.repo.transition_job(
            job.job_id,
            final_state,
            error_details=result.message
            if final_state in {JobState.FAILED, JobState.BLOCKED, JobState.NEEDS_VERIFICATION}
            else None,
            published_url=result.published_url,
        )

        if result.published_url and final_state == JobState.PUBLISHED:
            self.repo.save_published_listing(
                event_id=event.event_id,
                platform_id=platform.platform_id,
                job_id=job.job_id,
                published_url=result.published_url,
            )

        return {
            "duplicate": False,
            "job": job.model_dump(mode="json"),
            "attempt": {
                "number": attempt_no,
                "state": result.state.value,
                "message": result.message,
                "dry_run": result.dry_run,
                "error_code": result.error_code,
                "evidence_paths": evidence,
            },
            "adapter_selection": selection,
        }
