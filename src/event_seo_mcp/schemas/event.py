"""Event input schema and validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class FAQItem(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class EventRecord(BaseModel):
    """Validated event record. Explicit user fields remain source of truth."""

    event_id: str = Field(min_length=1, max_length=128)
    event_title: str = Field(min_length=1, max_length=500)
    event_description: str = Field(min_length=1, max_length=20000)
    landing_page_url: HttpUrl
    start_datetime: datetime
    timezone: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=128)
    target_audience: str = Field(min_length=1, max_length=1000)
    primary_keywords: list[str] = Field(min_length=1)
    registration_url: HttpUrl
    organizer_name: str = Field(min_length=1, max_length=256)

    end_datetime: datetime | None = None
    venue_name: str | None = None
    street_address: str | None = None
    city: str | None = None
    state_or_region: str | None = None
    country: str | None = None
    virtual_event: bool | None = None
    agenda: list[str] | None = None
    speakers: list[str] | None = None
    speaker_bios: list[str] | None = None
    partner_names: list[str] | None = None
    partner_urls: list[HttpUrl] | None = None
    featured_services: list[str] | None = None
    hero_image_url: HttpUrl | None = None
    logo_url: HttpUrl | None = None
    registration_deadline: datetime | None = None
    faqs: list[FAQItem] | None = None
    approved_claims: list[str] | None = None
    excluded_claims: list[str] | None = None
    brand_voice: str | None = None
    campaign_utm_parameters: dict[str, str] | None = None

    @field_validator("primary_keywords")
    @classmethod
    def _keywords_nonempty(cls, value: list[str]) -> list[str]:
        cleaned = [k.strip() for k in value if k and k.strip()]
        if not cleaned:
            raise ValueError("primary_keywords must contain at least one non-empty keyword")
        return cleaned

    @model_validator(mode="after")
    def _check_datetimes(self) -> EventRecord:
        if self.end_datetime and self.end_datetime < self.start_datetime:
            raise ValueError("end_datetime must be >= start_datetime")
        if self.registration_deadline and self.registration_deadline > self.start_datetime:
            # Allow equal; warn-level constraint only if after start
            pass
        return self

    def missing_fields_for(self, required: list[str]) -> list[str]:
        data = self.model_dump()
        missing: list[str] = []
        for field in required:
            value = data.get(field)
            if value is None or value == "" or value == []:
                missing.append(field)
        return missing


def parse_event(payload: dict[str, Any]) -> EventRecord:
    return EventRecord.model_validate(payload)
