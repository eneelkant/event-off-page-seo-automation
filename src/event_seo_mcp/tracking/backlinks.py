"""Backlink verification service."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from event_seo_mcp.database.repository import Repository
from event_seo_mcp.settings import Settings, get_settings


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str | None]] = []
        self._current_href: str | None = None
        self._current_rel: str | None = None
        self._current_text: list[str] = []
        self._in_a = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {k.lower(): v for k, v in attrs}
        self._in_a = True
        self._current_href = attr_map.get("href")
        self._current_rel = attr_map.get("rel")
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._in_a:
            self.links.append(
                {
                    "href": self._current_href,
                    "rel": self._current_rel,
                    "anchor_text": "".join(self._current_text).strip(),
                }
            )
            self._in_a = False


class BacklinkVerifier:
    def __init__(self, repo: Repository, settings: Settings | None = None) -> None:
        self.repo = repo
        self.settings = settings or get_settings()

    def verify(
        self,
        *,
        event_id: str,
        published_url: str,
        landing_page_url: str,
        listing_id: str | None = None,
        html_override: str | None = None,
    ) -> dict[str, Any]:
        redirect_chain: list[str] = []
        http_status: int | None = None
        html = html_override
        final_url = published_url
        error = None

        if html is None:
            try:
                with httpx.Client(
                    timeout=self.settings.backlink_timeout_seconds,
                    follow_redirects=True,
                    max_redirects=self.settings.backlink_max_redirects,
                    headers={"User-Agent": self.settings.backlink_user_agent},
                ) as client:
                    response = client.get(published_url)
                http_status = response.status_code
                final_url = str(response.url)
                redirect_chain = [str(r.url) for r in response.history] + [final_url]
                if response.status_code >= 400:
                    result = self._store(
                        event_id=event_id,
                        listing_id=listing_id,
                        published_url=published_url,
                        landing_page_url=landing_page_url,
                        http_status=http_status,
                        redirect_chain=redirect_chain,
                        link_found=False,
                        result="inaccessible_or_missing_page",
                        details=f"HTTP {http_status}",
                    )
                    return result
                html = response.text
            except httpx.HTTPError as exc:
                error = str(exc)
                result = self._store(
                    event_id=event_id,
                    listing_id=listing_id,
                    published_url=published_url,
                    landing_page_url=landing_page_url,
                    http_status=None,
                    redirect_chain=redirect_chain,
                    link_found=False,
                    result="blocked_or_fetch_error",
                    details=error,
                )
                return result

        parser = _LinkParser()
        parser.feed(html or "")
        target = self._normalize(landing_page_url)
        match = None
        for link in parser.links:
            href = link.get("href")
            if not href:
                continue
            absolute = urljoin(final_url, href)
            if self._normalize(absolute) == target or target in self._normalize(absolute):
                match = link
                break

        # Also detect plain URL mentions
        if not match and target in (html or ""):
            match = {"href": landing_page_url, "rel": None, "anchor_text": None}

        if not match:
            return self._store(
                event_id=event_id,
                listing_id=listing_id,
                published_url=published_url,
                landing_page_url=landing_page_url,
                http_status=http_status or 200,
                redirect_chain=redirect_chain,
                link_found=False,
                result="verified_missing_link",
                details="Page reachable but landing page link not found.",
            )

        rel = (match.get("rel") or "") if match else ""
        rel_l = rel.lower() if isinstance(rel, str) else ""
        return self._store(
            event_id=event_id,
            listing_id=listing_id,
            published_url=published_url,
            landing_page_url=landing_page_url,
            http_status=http_status or 200,
            redirect_chain=redirect_chain,
            link_found=True,
            anchor_text=match.get("anchor_text") if match else None,
            rel_attributes=rel or None,
            result="verified_link_found",
            details=f"rel={rel_l or 'none'}; indexing_not_claimed=true",
        )

    def verify_event(self, event_id: str, landing_page_url: str) -> list[dict[str, Any]]:
        rows = self.repo.db.fetchall(
            "SELECT * FROM published_listings WHERE event_id = ?",
            (event_id,),
        )
        results = []
        for row in rows:
            results.append(
                self.verify(
                    event_id=event_id,
                    published_url=row["published_url"],
                    landing_page_url=landing_page_url,
                    listing_id=row["listing_id"],
                )
            )
        return results

    def _store(self, **payload: Any) -> dict[str, Any]:
        check_id = self.repo.save_backlink_check(payload)
        payload["check_id"] = check_id
        # Never claim search-engine indexing.
        payload["indexing_verified"] = False
        return payload

    @staticmethod
    def _normalize(url: str) -> str:
        parsed = urlparse(url.strip())
        path = re.sub(r"/+$", "", parsed.path or "")
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"
