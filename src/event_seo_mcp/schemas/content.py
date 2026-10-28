"""Generated content schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


ContentType = Literal[
    "event_directory_description",
    "event_calendar_listing",
    "partner_promotion_email",
    "community_post",
    "digital_pr_release",
    "guest_post_pitch",
    "guest_article",
    "linkedin_post",
    "speaker_announcement",
    "customer_success_story",
    "research_summary",
    "agenda_highlights",
    "executive_poll",
    "partner_spotlight",
]

ValidationStatus = Literal["valid", "invalid", "needs_review"]
ApprovalStatus = Literal["draft", "pending_approval", "approved", "rejected"]


class GeneratedContent(BaseModel):
    platform_id: str
    event_id: str
    content_type: ContentType
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    destination_url: HttpUrl | str
    cta: str
    suggested_keywords: list[str] = Field(default_factory=list)
    character_count: int = Field(ge=0)
    source_event_fields: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus = "needs_review"
    approval_status: ApprovalStatus = "draft"
    content_id: str | None = None

    @field_validator("character_count", mode="before")
    @classmethod
    def _default_count(cls, value: object) -> object:
        return value

    def recompute_character_count(self) -> GeneratedContent:
        self.character_count = len(self.body)
        return self
