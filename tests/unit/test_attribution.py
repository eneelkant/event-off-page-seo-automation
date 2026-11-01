"""Attribution audit separates observed traffic from listing claims."""

from __future__ import annotations

from event_seo_mcp.reporting.attribution import audit_campaign_attribution


def _report(rows: list[dict], *, complete: bool = True, row_count: int | None = None) -> dict:
    return {
        "ok": True,
        "error": None,
        "rows": rows,
        "row_count": len(rows) if row_count is None else row_count,
        "complete": complete,
        "truncated": not complete,
    }


def _row(**overrides) -> dict:
    row = {
        "sessionSource": "eventbrite",
        "sessionMedium": "event_directory",
        "sessionCampaignName": "Spring Launch",
        "pagePath": "/summit",
        "sessions": 3,
        "activeUsers": 2,
        "screenPageViews": 4,
        "eventCount": 5,
    }
    row.update(overrides)
    return row


def test_api_error_is_not_reported_as_zero_sessions() -> None:
    result = audit_campaign_attribution(
        {"campaign_name": "Spring Launch"},
        {"ok": False, "error": "authentication_error", "rows": None},
    )
    assert result["ok"] is False
    assert result["observed_sessions"] is None
    assert result["tracking_broken"] is False
    assert result["backlink_verified"] is False
    assert "zero sessions" in result["inferences"][0]


def test_empty_report_does_not_declare_tracking_broken() -> None:
    result = audit_campaign_attribution(
        {"campaign_name": "Spring Launch", "source": "eventbrite"},
        _report([]),
    )
    assert result["ok"] is True
    assert result["observed_sessions"] == 0
    assert result["tracking_broken"] is False
    assert result["backlink_verified"] is False
    assert result["listing_verified"] is False
    assert "no_recorded_sessions" in result["observations"]
    assert result["potential_issues"] == []
    assert "not proof that tracking is broken" in result["inferences"][0]


def test_matching_sessions_do_not_verify_a_backlink() -> None:
    result = audit_campaign_attribution(
        {
            "campaign_name": "Spring Launch",
            "source": "eventbrite",
            "medium": "event_directory",
            "page_path": "/summit",
        },
        _report([_row()]),
    )
    assert result["observed_sessions"] == 3
    assert result["backlink_verified"] is False
    assert result["tracking_verified"] is False
    assert result["potential_issues"] == []
    assert "does not verify a backlink" in result["inferences"][0]
    assert result["modifies_listings"] is False
    assert result["modifies_ga4"] is False


def test_unexpected_source_medium_campaign_and_page_are_inferences() -> None:
    result = audit_campaign_attribution(
        {
            "campaign_name": "Spring Launch",
            "source": "eventbrite",
            "medium": "event_directory",
            "page_path": "/summit",
        },
        _report(
            [
                _row(
                    sessionSource="newsletter",
                    sessionMedium="email",
                    sessionCampaignName="(not set)",
                    pagePath="/other",
                    sessions=1,
                )
            ]
        ),
    )
    codes = {item["code"] for item in result["potential_issues"]}
    assert codes == {"inconsistent_campaign", "missing_campaign", "unexpected_source", "unexpected_medium", "page_without_matching_rows"}
    assert result["backlink_verified"] is False
    assert result["tracking_broken"] is False
    assert all(item["kind"] == "potential_discrepancy" for item in result["potential_issues"])
    joined = " ".join(result["limitations"])
    assert "does not independently verify" in joined
