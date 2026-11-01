"""UTM URL generation stays deterministic and does not fetch or store URLs."""

from __future__ import annotations

import pytest

from event_seo_mcp.tracking.utm import UtmUrlError, build_event_utm_url, normalize_platform, preview_event_utm_url

BASE = "https://events.example.com/summit?ref=newsletter&utm_source=legacy&utm_medium=email&utm_term=spring#register"


def test_replace_policy_keeps_plain_query_and_fragment() -> None:
    tracked = build_event_utm_url(
        BASE,
        "Dev Events",
        "Spring Launch",
        medium="event_directory",
        content="event_submission_link",
        conflict_policy="replace",
    )
    assert tracked == (
        "https://events.example.com/summit?ref=newsletter"
        "&utm_source=dev_events&utm_medium=event_directory"
        "&utm_campaign=Spring%20Launch&utm_content=event_submission_link"
        "&utm_term=spring#register"
    )


def test_preserve_policy_keeps_existing_utm_values() -> None:
    tracked = build_event_utm_url(BASE, "eventbrite", "Spring Launch", conflict_policy="preserve")
    assert "utm_source=legacy" in tracked
    assert "utm_medium=email" in tracked
    assert "utm_campaign=Spring%20Launch" in tracked
    assert "utm_source=eventbrite" not in tracked
    assert tracked.endswith("#register")
    assert build_event_utm_url(tracked, "eventbrite", "Spring Launch", conflict_policy="preserve") == tracked


def test_duplicate_utm_parameters_collapse() -> None:
    tracked = build_event_utm_url(
        "https://events.example.com/summit?utm_source=one&utm_source=two&ref=a",
        "10times",
        "Launch",
        conflict_policy="replace",
    )
    assert tracked.count("utm_source=") == 1
    assert "utm_source=10times" in tracked
    assert tracked.startswith("https://events.example.com/summit?ref=a&")


def test_platform_normalization_does_not_rewrite_campaign_text() -> None:
    assert normalize_platform("Eventbrite") == "eventbrite"
    assert normalize_platform("10Times") == "10times"
    assert normalize_platform("dev.events") == "dev_events"
    assert normalize_platform("Dev Events") == "dev_events"
    tracked = build_event_utm_url("https://events.example.com/a", "Eventbrite", "Keep This Case")
    assert "utm_campaign=Keep%20This%20Case" in tracked
    assert "utm_source=eventbrite" in tracked


def test_encoding_and_repeated_execution_are_stable() -> None:
    first = build_event_utm_url(
        "https://events.example.com/a?q=caf%C3%A9&utm_source=old",
        "eventbrite",
        "A & B",
        conflict_policy="replace",
    )
    assert "utm_campaign=A%20%26%20B" in first
    assert "q=caf%C3%A9" in first
    for _ in range(5):
        assert build_event_utm_url(first, "eventbrite", "A & B", conflict_policy="replace") == first


@pytest.mark.parametrize(
    "value",
    ["", "   ", None, "javascript:alert(1)", "ftp://events.example.com/a", "https://user:pass@events.example.com/a", "/relative", "not a url"],
)
def test_invalid_urls_are_rejected(value: object) -> None:
    with pytest.raises(UtmUrlError) as caught:
        build_event_utm_url(value, "eventbrite", "Launch")  # type: ignore[arg-type]
    assert caught.value.code == "invalid_url"


def test_empty_campaign_and_unknown_policy_are_rejected() -> None:
    with pytest.raises(UtmUrlError) as campaign:
        build_event_utm_url("https://events.example.com/a", "eventbrite", "  ")
    assert campaign.value.code == "invalid_input"
    with pytest.raises(UtmUrlError) as policy:
        build_event_utm_url("https://events.example.com/a", "eventbrite", "Launch", conflict_policy="merge")
    assert policy.value.code == "invalid_policy"


def test_preview_is_a_dry_run_and_reports_errors() -> None:
    preview = preview_event_utm_url("https://events.example.com/a", "eventbrite", "Launch")
    assert preview["dry_run"] is True
    assert preview["would_publish"] is False
    assert preview["stored_landing_page_modified"] is False
    assert preview["utm_parameter_preservation"] == "unknown"
    assert preview["original_url"] == "https://events.example.com/a"
    assert preview["tracked_url"] != preview["original_url"]
    assert preview["error"] is None
    failed = preview_event_utm_url("", "eventbrite", "Launch")
    assert failed["tracked_url"] is None
    assert failed["error"] == "invalid_url"
    assert failed["would_publish"] is False
