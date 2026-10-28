"""Google Gemini provider (optional dependency)."""

from __future__ import annotations

import json
from typing import Any

from event_seo_mcp.providers.base import AIProvider, ProviderError
from event_seo_mcp.providers.template_provider import TemplateProvider
from event_seo_mcp.schemas.content import ContentType, GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord
from event_seo_mcp.settings import Settings


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = TemplateProvider()

    def available(self) -> bool:
        return bool(self.settings.gemini_api_key)

    def generate_content(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content_type: ContentType,
        *,
        extra_instructions: str | None = None,
    ) -> GeneratedContent:
        if not self.available():
            raise ProviderError("GEMINI_API_KEY is not configured")
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError("google-genai package is not installed") from exc

        client = genai.Client(api_key=self.settings.gemini_api_key)
        prompt = (
            "Return ONLY JSON with keys title, body, cta, suggested_keywords. "
            "Do not invent statistics. "
            f"content_type={content_type}; platform={platform.platform_name}; "
            f"event={event.model_dump_json()}; extra={extra_instructions or 'none'}"
        )
        try:
            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
            )
            raw = getattr(response, "text", None) or "{}"
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Gemini generation failed: {exc}") from exc
        return self._to_content(event, platform, content_type, data)

    def _to_content(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content_type: ContentType,
        data: dict[str, Any],
    ) -> GeneratedContent:
        body = str(data.get("body") or "").strip()
        if not body:
            return self._fallback.generate_content(event, platform, content_type)
        return GeneratedContent(
            platform_id=platform.platform_id,
            event_id=event.event_id,
            content_type=content_type,  # type: ignore[arg-type]
            title=str(data.get("title") or event.event_title)[:500],
            body=body,
            destination_url=str(event.landing_page_url),
            cta=str(data.get("cta") or "Learn more"),
            suggested_keywords=list(data.get("suggested_keywords") or event.primary_keywords),
            character_count=len(body),
            source_event_fields=["event_title", "event_description", "landing_page_url"],
            validation_status="needs_review",
            approval_status="draft",
        )
