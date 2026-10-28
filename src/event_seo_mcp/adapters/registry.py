"""Adapter registry and selection."""

from __future__ import annotations

from event_seo_mcp.adapters.base import PlatformAdapter
from event_seo_mcp.adapters.community import CommunityAdapter
from event_seo_mcp.adapters.digital_pr import DigitalPRAdapter
from event_seo_mcp.adapters.directory_browser import DirectoryBrowserAdapter
from event_seo_mcp.adapters.eventbrite import EventbriteAdapter
from event_seo_mcp.adapters.guest_post import GuestPostAdapter
from event_seo_mcp.adapters.linkedin import LinkedInAdapter
from event_seo_mcp.adapters.meetup import MeetupAdapter
from event_seo_mcp.adapters.partner import PartnerAdapter

_ADAPTERS: dict[str, PlatformAdapter] = {
    "eventbrite": EventbriteAdapter(),
    "meetup": MeetupAdapter(),
    "directory_browser": DirectoryBrowserAdapter(),
    "partner": PartnerAdapter(),
    "community": CommunityAdapter(),
    "digital_pr": DigitalPRAdapter(),
    "guest_post": GuestPostAdapter(),
    "linkedin": LinkedInAdapter(),
}


def get_adapter(name: str) -> PlatformAdapter:
    if name not in _ADAPTERS:
        raise KeyError(f"Unknown adapter: {name}")
    return _ADAPTERS[name]


def list_adapters() -> list[PlatformAdapter]:
    return list(_ADAPTERS.values())
