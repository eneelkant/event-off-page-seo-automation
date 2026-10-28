"""Common AI provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from event_seo_mcp.schemas.content import ContentType, GeneratedContent
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.schemas.platform import PlatformRecord


class ProviderError(RuntimeError):
    """Provider failure (timeout, rate limit, auth, etc.)."""


class AIProvider(ABC):
    name: str

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def generate_content(
        self,
        event: EventRecord,
        platform: PlatformRecord,
        content_type: ContentType,
        *,
        extra_instructions: str | None = None,
    ) -> GeneratedContent:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "available": self.available()}
