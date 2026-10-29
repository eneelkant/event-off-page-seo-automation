"""Platform registry schemas — platforms, workflows, credentials, research."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


AutomationStatus = Literal[
    "DISCOVERED",
    "NEEDS_VERIFICATION",
    "READY",
    "BLOCKED",
]

CATEGORY_IDS = (
    "event_directory",
    "ai_tech_calendar",
    "partner_marketing",
    "industry_community",
    "digital_pr",
    "guest_posting",
    "linkedin_thought_leadership",
)


class ResearchSource(BaseModel):
    type: str
    url: HttpUrl | str | None = None
    verified: bool = False
    note: str | None = None


class ResearchRecord(BaseModel):
    researched_at: str | None = None
    sources: list[ResearchSource] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    notes: str | None = None


class CredentialMetadata(BaseModel):
    """Names of env vars only — never store secret values in the registry."""

    env_vars: list[str] = Field(default_factory=list)
    optional_env_vars: list[str] = Field(default_factory=list)
    auth_type: str = "unknown"
    required_for_live: bool = True
    docs_url: HttpUrl | str | None = None
    notes: str | None = None


class PolicyRecord(BaseModel):
    approval_required: bool = True
    dry_run_default: bool = True
    allow_live_without_ready: bool = False
    self_promo_restricted: bool = False
    paid_submission_possible: bool | None = None


class PlatformRecord(BaseModel):
    platform_id: str
    platform_name: str
    category: str
    official_homepage: HttpUrl | str | None = None
    verified_submission_url: HttpUrl | str | None = None
    submission_method: str
    adapter_name: str
    authentication_method: str
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    supported_content_types: list[str] = Field(default_factory=list)
    automation_status: AutomationStatus = "NEEDS_VERIFICATION"
    approval_required: bool = True
    paid_submission_possible: bool | None = None
    last_verified_at: datetime | None = None
    documentation_url: HttpUrl | str | None = None
    operational_notes: str | None = None

    # Registry v0.2 extensions
    credentials: CredentialMetadata = Field(default_factory=CredentialMetadata)
    research: ResearchRecord = Field(default_factory=ResearchRecord)
    policy: PolicyRecord = Field(default_factory=PolicyRecord)
    distinct_platform_id: str | None = None
    is_workflow: bool = False
    workflow_id: str | None = None
    parent_platform_id: str | None = None
    has_workflows: bool = False

    @model_validator(mode="after")
    def _defaults(self) -> PlatformRecord:
        if not self.distinct_platform_id:
            self.distinct_platform_id = self.parent_platform_id or self.platform_id
        if self.approval_required and not self.policy.approval_required:
            self.policy.approval_required = True
        # Unknown research fields must keep NEEDS_VERIFICATION (never invent READY).
        if self.research.unknown_fields and self.automation_status == "READY":
            self.automation_status = "NEEDS_VERIFICATION"
        return self


class PlatformsFile(BaseModel):
    version: str
    last_updated: str | None = None
    notes: str | None = None
    categories: list[str] = Field(default_factory=lambda: list(CATEGORY_IDS))
    totals: dict[str, Any] = Field(default_factory=dict)
    platforms: list[PlatformRecord] = Field(default_factory=list)
    workflows: list[PlatformRecord] = Field(default_factory=list)

    def by_id(self, platform_id: str) -> PlatformRecord | None:
        for platform in self.platforms:
            if platform.platform_id == platform_id:
                return platform
        for workflow in self.workflows:
            if workflow.platform_id == platform_id or workflow.workflow_id == platform_id:
                return workflow
        return None

    def distinct_platforms(self) -> list[PlatformRecord]:
        return list(self.platforms)

    def registry_entries(self) -> list[PlatformRecord]:
        """35 submit/registry entries: non-LinkedIn platforms + LinkedIn workflows.

        The LinkedIn parent platform is a distinct platform but not a standalone
        registry submit entry (use workflows instead).
        """
        entries = [p for p in self.platforms if p.platform_id != "linkedin"]
        entries.extend(self.workflows)
        return entries

    def validate_totals(self) -> dict[str, Any]:
        cats = sorted({p.category for p in self.platforms} | {w.category for w in self.workflows})
        distinct = {p.distinct_platform_id or p.platform_id for p in self.platforms}
        entries = self.registry_entries()
        li_workflows = [w for w in self.workflows if (w.parent_platform_id or "") == "linkedin"]
        checks = {
            "categories_count": len(cats),
            "categories_expected": 7,
            "categories_ok": len(cats) == 7 and set(cats) == set(CATEGORY_IDS),
            "distinct_platforms_count": len(self.platforms),
            "distinct_platforms_expected": 30,
            "distinct_platforms_ok": len(self.platforms) == 30 and len(distinct) == 30,
            "linkedin_workflows_count": len(li_workflows),
            "linkedin_workflows_expected": 6,
            "linkedin_workflows_ok": len(li_workflows) == 6,
            "registry_entries_count": len(entries),
            "registry_entries_expected": 35,
            "registry_entries_ok": len(entries) == 35,
            "linkedin_parent_present": any(p.platform_id == "linkedin" for p in self.platforms),
        }
        checks["all_ok"] = all(
            checks[k]
            for k in (
                "categories_ok",
                "distinct_platforms_ok",
                "linkedin_workflows_ok",
                "registry_entries_ok",
                "linkedin_parent_present",
            )
        )
        return checks

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
