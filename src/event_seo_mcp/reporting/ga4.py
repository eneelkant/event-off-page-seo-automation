"""Read-only Google Analytics 4 Data API reports.

The default install does not import the API client. Tests pass a fake client.
Disabled configuration returns an error and does not invent metrics.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from event_seo_mcp.security.redaction import redact_secrets
from event_seo_mcp.settings import Settings
from event_seo_mcp.tracking.utm import UtmUrlError, normalize_platform

# Session and page fields that the Data API schema allows together with the
# core visit metrics. `conversions` is property-dependent and stays opt-in.
CORE_DIMENSIONS = (
    "sessionSource",
    "sessionMedium",
    "sessionCampaignName",
    "pagePath",
)
CORE_METRICS = (
    "sessions",
    "activeUsers",
    "screenPageViews",
    "eventCount",
)
OPTIONAL_METRICS = frozenset({"conversions"})
_ABSOLUTE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RELATIVE_DATE = re.compile(r"^(\d+)daysAgo$")
_INTEGER = re.compile(r"^-?\d+$")
_DECIMAL = re.compile(r"^-?\d+\.\d+$")
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")


class _ClientMissing(RuntimeError):
    pass


def query_ga4_campaign_performance(
    property_id: str | None,
    campaign_name: str,
    start_date: str,
    end_date: str,
    *,
    source: str | None = None,
    medium: str | None = None,
    page_path: str | None = None,
    enabled: bool = False,
    include_conversions: bool = False,
    page_size: int = 10000,
    max_pages: int = 10,
    timeout_seconds: float = 30.0,
    client: Any | None = None,
) -> dict[str, Any]:
    """Query campaign rows. Empty rows are a successful report, not an error."""
    if not enabled:
        return _failure(
            "ga4_disabled",
            "GA4 reporting is disabled. Set GA4_ENABLED=true only where a property and credentials are configured.",
        )
    try:
        property_token, start, end, filters, dimensions, metrics = _validated_request(
            property_id,
            campaign_name,
            start_date,
            end_date,
            source=source,
            medium=medium,
            page_path=page_path,
            include_conversions=include_conversions,
            page_size=page_size,
            max_pages=max_pages,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as exc:
        return _failure("configuration_error", str(exc))
    try:
        active = client if client is not None else _default_client()
    except _ClientMissing:
        return _failure(
            "ga4_client_missing",
            "The Google Analytics Data API client is not installed. Install the optional ga4 extra.",
        )
    except Exception as exc:
        code, message = classify_ga4_exception(exc)
        return _failure(code, message)
    request = {
        "property": f"properties/{property_token}",
        "dimensions": [{"name": name} for name in dimensions],
        "metrics": [{"name": name} for name in metrics],
        "date_ranges": [{"start_date": start, "end_date": end}],
        "dimension_filter": _dimension_filter(filters),
        "limit": page_size,
        "offset": 0,
        "keep_empty_rows": False,
    }
    rows: list[dict[str, Any]] = []
    total: int | None = None
    for page in range(max_pages):
        request["offset"] = page * page_size
        try:
            response = _run_report(active, request, timeout_seconds)
            parsed_rows, reported_total = _parse_page(response, dimensions, metrics)
        except Exception as exc:
            code, message = classify_ga4_exception(exc)
            return _failure(code, message)
        if reported_total is None:
            return _failure("api_error", "The Google Analytics Data API returned a report that could not be read.")
        total = reported_total
        rows.extend(parsed_rows)
        if len(parsed_rows) < page_size or len(rows) >= reported_total:
            return _success(
                property_id=property_token,
                campaign_name=campaign_name.strip(),
                start_date=start,
                end_date=end,
                dimensions=dimensions,
                metrics=metrics,
                filters=filters,
                rows=rows,
                row_count=reported_total,
                complete=True,
                truncated=False,
            )
    return _success(
        property_id=property_token,
        campaign_name=campaign_name.strip(),
        start_date=start,
        end_date=end,
        dimensions=dimensions,
        metrics=metrics,
        filters=filters,
        rows=rows,
        row_count=total if total is not None else len(rows),
        complete=False,
        truncated=True,
    )


def query_ga4_from_settings(
    settings: Settings,
    campaign_name: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str | None = None,
    medium: str | None = None,
    page_path: str | None = None,
    include_conversions: bool | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run the report with environment configuration. Credentials are not returned."""
    return query_ga4_campaign_performance(
        settings.ga4_property_id,
        campaign_name,
        start_date or settings.ga4_start_date,
        end_date or settings.ga4_end_date,
        source=source,
        medium=medium,
        page_path=page_path,
        enabled=settings.ga4_enabled,
        include_conversions=(
            settings.ga4_include_conversions if include_conversions is None else include_conversions
        ),
        page_size=settings.ga4_page_size,
        max_pages=settings.ga4_max_pages,
        timeout_seconds=settings.ga4_timeout_seconds,
        client=client,
    )


def validate_report_fields(
    dimensions: list[str],
    metrics: list[str],
    *,
    allow_conversions: bool,
) -> None:
    """Reject fields outside the compatible campaign report schema."""
    if not dimensions or any(name not in CORE_DIMENSIONS for name in dimensions):
        raise ValueError("dimensions must be chosen from the supported campaign report schema")
    allowed = set(CORE_METRICS)
    if allow_conversions:
        allowed |= OPTIONAL_METRICS
    if not metrics or any(name not in allowed for name in metrics):
        raise ValueError("metrics must be chosen from the supported campaign report schema")
    if "conversions" in metrics and not allow_conversions:
        raise ValueError("conversions is omitted unless the property configuration requests it")


def classify_ga4_exception(exc: BaseException) -> tuple[str, str]:
    """Map an API failure to a stable code. The message never includes secrets."""
    name = type(exc).__name__
    redacted = _PEM.sub("***REDACTED***", redact_secrets(str(exc)))
    if "PRIVATE KEY" in redacted or "-----BEGIN" in redacted:
        redacted = "credential material was removed"
    if name in {"Unauthenticated", "PermissionDenied", "DefaultCredentialsError", "RefreshError"}:
        return "authentication_error", "Google Analytics credentials were rejected or are missing."
    if name in {"ResourceExhausted", "TooManyRequests"}:
        return "quota_exceeded", "Google Analytics Data API quota was exceeded."
    if name in {"DeadlineExceeded", "TimeoutError"} or isinstance(exc, TimeoutError):
        return "timeout", "The Google Analytics Data API request timed out."
    if name == "InvalidArgument":
        lowered = redacted.lower()
        if "incompatible" in lowered or "not a valid metric" in lowered or "not a valid dimension" in lowered:
            return (
                "metric_not_supported",
                "A requested dimension or metric is not compatible with this report.",
            )
        return "api_error", "The Google Analytics Data API rejected the report request."
    return "api_error", "The Google Analytics Data API request failed."


def _validated_request(
    property_id: str | None,
    campaign_name: str,
    start_date: str,
    end_date: str,
    *,
    source: str | None,
    medium: str | None,
    page_path: str | None,
    include_conversions: bool,
    page_size: int,
    max_pages: int,
    timeout_seconds: float,
) -> tuple[str, str, str, dict[str, str], tuple[str, ...], tuple[str, ...]]:
    token = _property_id(property_id)
    start = _date(start_date, field="start_date")
    end = _date(end_date, field="end_date")
    if _ABSOLUTE_DATE.fullmatch(start) and _ABSOLUTE_DATE.fullmatch(end) and start > end:
        raise ValueError("start_date must not be after end_date")
    if not isinstance(campaign_name, str) or not campaign_name.strip():
        raise ValueError("campaign_name is required")
    if len(campaign_name.strip()) > 100:
        raise ValueError("campaign_name is longer than 100 characters")
    if not isinstance(page_size, int) or not 1 <= page_size <= 10000:
        raise ValueError("page_size must be from 1 to 10000")
    if not isinstance(max_pages, int) or not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be from 1 to 20")
    if not isinstance(timeout_seconds, (int, float)) or not 1 <= float(timeout_seconds) <= 120:
        raise ValueError("timeout_seconds must be from 1 to 120")
    filters = {"sessionCampaignName": campaign_name.strip()}
    if source not in (None, ""):
        try:
            filters["sessionSource"] = normalize_platform(str(source))
        except UtmUrlError as exc:
            raise ValueError(exc.message) from exc
    if medium not in (None, ""):
        if not isinstance(medium, str) or not medium.strip():
            raise ValueError("medium must be a string")
        filters["sessionMedium"] = medium.strip()
    if page_path not in (None, ""):
        filters["pagePath"] = _page_path(str(page_path))
    dimensions = CORE_DIMENSIONS
    metrics = CORE_METRICS + (("conversions",) if include_conversions else ())
    validate_report_fields(list(dimensions), list(metrics), allow_conversions=include_conversions)
    return token, start, end, filters, dimensions, metrics


def ga4_property_id_valid(value: str | None) -> bool:
    """True when the value is a numeric property id. The id itself is not returned."""
    try:
        _property_id(value)
    except ValueError:
        return False
    return True


def _property_id(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("GA4_PROPERTY_ID is required when GA4 reporting is enabled")
    text = value.strip()
    if text.startswith("properties/"):
        text = text.split("/", 1)[1]
    if not text.isdigit() or not 1 <= len(text) <= 20:
        raise ValueError("GA4_PROPERTY_ID must be the numeric property id")
    return text


def _date(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a GA4 date")
    text = value.strip()
    if text in {"today", "yesterday"}:
        return text
    if _ABSOLUTE_DATE.fullmatch(text):
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"{field} must be a real calendar date") from exc
        return text
    match = _RELATIVE_DATE.fullmatch(text)
    if match and 0 <= int(match.group(1)) <= 3650:
        return text
    raise ValueError(f"{field} must be YYYY-MM-DD, today, yesterday, or NdaysAgo")


def _page_path(value: str) -> str:
    text = value.strip()
    if any(ch.isspace() or ord(ch) < 32 for ch in text):
        raise ValueError("page_path contains unsupported characters")
    if text.startswith("/"):
        return text.split("?", 1)[0].split("#", 1)[0] or "/"
    from urllib.parse import urlsplit

    parts = urlsplit(text)
    if parts.scheme in {"http", "https"} and parts.netloc:
        return parts.path or "/"
    raise ValueError("page_path must be a path or an http(s) URL")


def _dimension_filter(filters: dict[str, str]) -> dict[str, Any]:
    expressions = [
        {
            "filter": {
                "field_name": field,
                "string_filter": {"match_type": "EXACT", "value": value, "case_sensitive": True},
            }
        }
        for field, value in filters.items()
    ]
    if len(expressions) == 1:
        return expressions[0]
    return {"and_group": {"expressions": expressions}}


def ga4_client_importable() -> bool:
    """Return whether the optional client package imports. Does not construct a client."""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
    except ImportError:
        return False
    return BetaAnalyticsDataClient is not None


def _default_client() -> Any:
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
    except ImportError as exc:
        raise _ClientMissing() from exc
    return BetaAnalyticsDataClient()


def _run_report(client: Any, request: dict[str, Any], timeout: float) -> Any:
    if type(client).__module__.startswith("google.analytics"):
        return client.run_report(request=_to_proto(request), timeout=timeout)
    return client.run_report(request, timeout=timeout)


def _to_proto(request: dict[str, Any]) -> Any:
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Filter,
        FilterExpression,
        FilterExpressionList,
        Metric,
        RunReportRequest,
    )

    return RunReportRequest(
        property=request["property"],
        dimensions=[Dimension(name=item["name"]) for item in request["dimensions"]],
        metrics=[Metric(name=item["name"]) for item in request["metrics"]],
        date_ranges=[
            DateRange(start_date=item["start_date"], end_date=item["end_date"]) for item in request["date_ranges"]
        ],
        dimension_filter=_filter_expression(request["dimension_filter"], Filter, FilterExpression, FilterExpressionList),
        limit=request["limit"],
        offset=request["offset"],
        keep_empty_rows=False,
    )


def _filter_expression(payload: dict[str, Any], filter_type: Any, expression_type: Any, group_type: Any) -> Any:
    if "and_group" in payload:
        return expression_type(
            and_group=group_type(
                expressions=[
                    _filter_expression(item, filter_type, expression_type, group_type)
                    for item in payload["and_group"]["expressions"]
                ]
            )
        )
    body = payload["filter"]
    match = filter_type.StringFilter.MatchType.EXACT
    return expression_type(
        filter=filter_type(
            field_name=body["field_name"],
            string_filter=filter_type.StringFilter(
                match_type=match,
                value=body["string_filter"]["value"],
                case_sensitive=True,
            ),
        )
    )


def _parse_page(
    response: Any,
    dimensions: tuple[str, ...],
    metrics: tuple[str, ...],
) -> tuple[list[dict[str, Any]], int | None]:
    raw = _as_mapping(response)
    if raw is None:
        return [], None
    try:
        reported = int(raw.get("row_count", 0))
    except (TypeError, ValueError):
        return [], None
    parsed: list[dict[str, Any]] = []
    for item in raw.get("rows") or []:
        row = _parse_row(item, dimensions, metrics)
        if row is None:
            return [], None
        parsed.append(row)
    return parsed, reported


def _as_mapping(response: Any) -> dict[str, Any] | None:
    if isinstance(response, dict):
        return response
    rows = getattr(response, "rows", None)
    row_count = getattr(response, "row_count", None)
    if rows is None or row_count is None:
        return None
    converted = []
    for row in rows:
        converted.append(
            {
                "dimension_values": [{"value": getattr(value, "value", None)} for value in row.dimension_values],
                "metric_values": [{"value": getattr(value, "value", None)} for value in row.metric_values],
            }
        )
    return {"row_count": row_count, "rows": converted}


def _parse_row(item: Any, dimensions: tuple[str, ...], metrics: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    dim_values = item.get("dimension_values")
    metric_values = item.get("metric_values")
    if not isinstance(dim_values, list) or not isinstance(metric_values, list):
        return None
    if len(dim_values) != len(dimensions) or len(metric_values) != len(metrics):
        return None
    row: dict[str, Any] = {}
    for name, value in zip(dimensions, dim_values, strict=True):
        text = value.get("value") if isinstance(value, dict) else None
        if not isinstance(text, str):
            return None
        row[name] = text
    for name, value in zip(metrics, metric_values, strict=True):
        text = value.get("value") if isinstance(value, dict) else None
        row[name] = _metric(text)
    return row


def _returned_sessions(rows: list[dict[str, Any]], *, complete: bool) -> int | None:
    if not complete:
        return None
    total = 0
    for row in rows:
        value = row.get("sessions")
        if not isinstance(value, int):
            return None
        total += value
    return total


def _metric(value: Any) -> int | float | None:
    if not isinstance(value, str) or value == "":
        return None
    if _INTEGER.fullmatch(value):
        return int(value)
    if _DECIMAL.fullmatch(value):
        return float(value)
    return None


def _success(**fields: Any) -> dict[str, Any]:
    rows = fields["rows"]
    session_sum = _returned_sessions(rows, complete=bool(fields["complete"]))
    return {
        "ok": True,
        "error": None,
        "message": None,
        "read_only": True,
        "fabricated": False,
        "property_id": fields["property_id"],
        "campaign_name": fields["campaign_name"],
        "start_date": fields["start_date"],
        "end_date": fields["end_date"],
        "dimensions": list(fields["dimensions"]),
        "metrics": list(fields["metrics"]),
        "filters": fields["filters"],
        "rows": rows,
        "row_count": fields["row_count"],
        "returned_row_count": len(rows),
        "complete": fields["complete"],
        "truncated": fields["truncated"],
        "sessions_in_returned_rows": session_sum if fields["complete"] else None,
        "data_state": "empty" if fields["row_count"] == 0 else "rows",
    }


def _failure(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": code,
        "message": message,
        "read_only": True,
        "fabricated": False,
        "rows": None,
        "row_count": None,
        "returned_row_count": None,
        "complete": False,
        "truncated": False,
        "sessions_in_returned_rows": None,
        "data_state": "unavailable",
    }
