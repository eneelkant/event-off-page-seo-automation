"""Compare expected UTM configuration with a GA4 report.

Observed rows are facts. Possible causes are inferences. A session does not
prove a backlink, and a lack of sessions does not prove tracking is broken.
"""

from __future__ import annotations

from typing import Any

LIMITATIONS = (
    "GA4 reports aggregated traffic. It does not independently verify that a backlink exists or that a directory listing is live.",
    "A UTM-tagged session is reported traffic only. It is not proof of a specific external listing.",
    "No recorded sessions does not prove that tracking is broken. Reporting delay, consent, traffic volume, attribution rules, and the date range can all hide visits.",
    "Directory sites may remove query parameters. UTM preservation is not verified by this audit.",
    "This audit does not change listings, submission records, or GA4 settings.",
)


def audit_campaign_attribution(expected: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Return facts and inferences for one campaign. Never marks a backlink verified."""
    base = {
        "ok": bool(report.get("ok")),
        "error": report.get("error"),
        "backlink_verified": False,
        "listing_verified": False,
        "tracking_verified": False,
        "tracking_broken": False,
        "modifies_listings": False,
        "modifies_ga4": False,
        "observed_sessions": None,
        "facts": [],
        "inferences": [],
        "observations": [],
        "potential_issues": [],
        "limitations": list(LIMITATIONS),
    }
    if not report.get("ok"):
        code = report.get("error") or "unavailable"
        base["facts"].append(f"GA4 did not return a report ({code}).")
        base["inferences"].append(
            "No comparison was made. An API, configuration, or authentication failure is not a count of zero sessions."
        )
        return base
    rows = report.get("rows")
    if not isinstance(rows, list):
        base["ok"] = False
        base["error"] = "unreadable_report"
        base["facts"].append("The GA4 payload did not contain a row list.")
        return base
    sessions = _session_sum(rows) if report.get("complete") else None
    base["observed_sessions"] = sessions
    campaign = str(expected.get("campaign_name") or "").strip()
    source = expected.get("source")
    medium = expected.get("medium")
    page_path = expected.get("page_path")
    if report.get("truncated"):
        base["facts"].append("The report hit the configured page limit before every matching row was returned.")
        base["observations"].append("report_truncated")
    if not rows:
        base["facts"].append("GA4 returned no rows for this filter and date range.")
        base["observations"].append("no_recorded_sessions")
        base["inferences"].append(
            "Possible causes include reporting delay, consent mode, low traffic, attribution rules, "
            "a date range that misses the visit, or a directory stripping UTM parameters. "
            "This is not proof that tracking is broken and it is not proof that a listing is absent."
        )
        return base
    base["facts"].append(f"GA4 returned {len(rows)} row(s) for this filter and date range.")
    if sessions is not None:
        base["facts"].append(f"Returned rows report {sessions} session(s).")
    else:
        base["facts"].append("Session totals were not summed because the report is incomplete or a metric was missing.")
    observed_campaigns = sorted({str(row.get("sessionCampaignName") or "") for row in rows})
    observed_sources = sorted({str(row.get("sessionSource") or "") for row in rows})
    observed_mediums = sorted({str(row.get("sessionMedium") or "") for row in rows})
    observed_paths = sorted({str(row.get("pagePath") or "") for row in rows})
    base["facts"].append(f"Observed campaign values: {observed_campaigns}.")
    base["facts"].append(f"Observed source values: {observed_sources}.")
    base["facts"].append(f"Observed medium values: {observed_mediums}.")
    if campaign and any(value != campaign for value in observed_campaigns):
        _issue(
            base,
            code="inconsistent_campaign",
            fact=f"At least one returned campaign value differs from the expected campaign {campaign!r}.",
            inference="This is a potential attribution discrepancy. It does not by itself show which listing produced the session.",
        )
    if any(value in {"", "(not set)"} for value in observed_campaigns):
        _issue(
            base,
            code="missing_campaign",
            fact="At least one returned row has no campaign name.",
            inference="The visit may have been attributed without the expected utm_campaign parameter.",
        )
    if isinstance(source, str) and source and source not in observed_sources:
        _issue(
            base,
            code="unexpected_source",
            fact=f"Expected source {source!r} was not among the returned session sources.",
            inference="Another channel, a later redirect, or a changed tag can produce a different source. This does not prove the directory listing is missing.",
        )
    if isinstance(medium, str) and medium and medium not in observed_mediums:
        _issue(
            base,
            code="unexpected_medium",
            fact=f"Expected medium {medium!r} was not among the returned session mediums.",
            inference="A different medium is a potential discrepancy, not a verified listing failure.",
        )
    if isinstance(page_path, str) and page_path:
        if page_path not in observed_paths:
            _issue(
                base,
                code="page_without_matching_rows",
                fact=f"No returned row used page path {page_path!r}. Observed paths: {observed_paths}.",
                inference="The page may have no matching sessions in this date range. That is not proof the page or its listings are absent.",
            )
    if not base["potential_issues"]:
        base["facts"].append("Returned rows match the expected campaign, source, medium, and page path that were supplied.")
        base["inferences"].append(
            "Matching reported traffic still does not verify a backlink or prove that a directory listing is live."
        )
    return base


def _session_sum(rows: list[dict[str, Any]]) -> int | None:
    total = 0
    for row in rows:
        value = row.get("sessions")
        if not isinstance(value, int):
            return None
        total += value
    return total


def _issue(result: dict[str, Any], *, code: str, fact: str, inference: str) -> None:
    result["facts"].append(fact)
    result["inferences"].append(inference)
    result["observations"].append(code)
    result["potential_issues"].append(
        {"code": code, "kind": "potential_discrepancy", "fact": fact, "inference": inference}
    )
