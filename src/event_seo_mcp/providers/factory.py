"""Provider factory with optional fallback."""

from __future__ import annotations

from typing import Any

from event_seo_mcp.providers.anthropic_provider import AnthropicProvider
from event_seo_mcp.providers.base import AIProvider, ProviderError
from event_seo_mcp.providers.gemini_provider import GeminiProvider
from event_seo_mcp.providers.openai_provider import OpenAIProvider
from event_seo_mcp.providers.template_provider import TemplateProvider
from event_seo_mcp.settings import Settings, get_settings


def _build(name: str, settings: Settings) -> AIProvider:
    if name == "openai":
        return OpenAIProvider(settings)
    if name == "anthropic":
        return AnthropicProvider(settings)
    if name == "gemini":
        return GeminiProvider(settings)
    return TemplateProvider()


def get_provider(settings: Settings | None = None) -> AIProvider:
    settings = settings or get_settings()
    primary = _build(settings.ai_provider, settings)
    if primary.available():
        return primary
    if settings.ai_fallback_provider:
        fallback = _build(settings.ai_fallback_provider, settings)
        if fallback.available():
            return fallback
    # Always usable deterministic provider
    return TemplateProvider()


def list_provider_status(settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    names = ["template", "openai", "anthropic", "gemini"]
    return [_build(name, settings).health() for name in names]


def generate_with_failover(
    settings: Settings,
    *args: Any,
    **kwargs: Any,
):
    provider = get_provider(settings)
    try:
        return provider.generate_content(*args, **kwargs)
    except ProviderError:
        if settings.ai_fallback_provider and settings.ai_fallback_provider != provider.name:
            return _build(settings.ai_fallback_provider, settings).generate_content(*args, **kwargs)
        return TemplateProvider().generate_content(*args, **kwargs)
