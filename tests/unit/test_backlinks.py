"""Backlink verification against fixtures."""

from __future__ import annotations

from pathlib import Path

from event_seo_mcp.database.repository import Repository
from event_seo_mcp.schemas.event import EventRecord
from event_seo_mcp.tracking.backlinks import BacklinkVerifier

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_backlink_found(repo: Repository, sample_event: EventRecord) -> None:
    repo.upsert_event(sample_event)
    html = (FIXTURES / "listing_with_backlink.html").read_text(encoding="utf-8")
    verifier = BacklinkVerifier(repo)
    result = verifier.verify(
        event_id=sample_event.event_id,
        published_url="https://listings.example/item/1",
        landing_page_url=str(sample_event.landing_page_url),
        html_override=html,
    )
    assert result["link_found"] is True
    assert result["result"] == "verified_link_found"
    assert result["indexing_verified"] is False


def test_backlink_missing(repo: Repository, sample_event: EventRecord) -> None:
    repo.upsert_event(sample_event)
    html = (FIXTURES / "listing_without_backlink.html").read_text(encoding="utf-8")
    verifier = BacklinkVerifier(repo)
    result = verifier.verify(
        event_id=sample_event.event_id,
        published_url="https://listings.example/item/2",
        landing_page_url=str(sample_event.landing_page_url),
        html_override=html,
    )
    assert result["link_found"] is False
    assert result["result"] == "verified_missing_link"
