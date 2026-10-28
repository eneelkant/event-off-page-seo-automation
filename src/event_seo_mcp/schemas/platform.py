"""Platform registry schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


AutomationStatus = Literal[
    "DISCOVERED",
    "NEEDS_VERIFICATION",
    "READY",
    "BLOCKED",
]


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


class PlatformsFile(BaseModel):
    version: str
    last_updated: str | None = None
    notes: str | None = None
    platforms: list[PlatformRecord]

    def by_id(self, platform_id: str) -> PlatformRecord | None:
        for platform in self.platforms:
            if platform.platform_id == platform_id:
                return platform
        return None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
