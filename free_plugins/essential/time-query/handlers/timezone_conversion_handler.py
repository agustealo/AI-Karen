import zoneinfo
from typing import Any, Dict

from .base import TimeHandlerBase


async def handle_timezone_conversion(params: Dict[str, Any]) -> Dict[str, Any]:
    mode = "convert_timezone"
    context = TimeHandlerBase.normalize_dict(params.get("context"))
    output_format = TimeHandlerBase.normalize_string(params.get("format"))

    dt_str = TimeHandlerBase.normalize_string(params.get("datetime"))
    from_tz_input = TimeHandlerBase.normalize_string(params.get("from_timezone"))
    to_tz_input = TimeHandlerBase.normalize_string(params.get("to_timezone"))

    if not all([dt_str, from_tz_input, to_tz_input]):
        return TimeHandlerBase.error_payload(
            mode=mode,
            error="Missing required conversion fields: datetime, from_timezone, and to_timezone are required",
            context=context,
        )

    # At this point we know these are not None due to the check above
    assert dt_str is not None
    assert from_tz_input is not None
    assert to_tz_input is not None

    from_resolution = TimeHandlerBase.resolve_timezone(from_tz_input)
    if not from_resolution.get("success"):
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=from_resolution.get("error", "Invalid source timezone"),
            context=context,
            metadata={"query": from_tz_input, "field": "from_timezone"},
        )

    to_resolution = TimeHandlerBase.resolve_timezone(to_tz_input)
    if not to_resolution.get("success"):
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=to_resolution.get("error", "Invalid destination timezone"),
            context=context,
            metadata={"query": to_tz_input, "field": "to_timezone"},
        )

    parsed_dt = TimeHandlerBase.parse_datetime(dt_str)
    if not parsed_dt:
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=f"Invalid datetime format: {dt_str}. Use ISO-8601-compatible datetime.",
            context=context,
        )

    from_timezone_name = from_resolution["timezone"]
    to_timezone_name = to_resolution["timezone"]

    try:
        from_tz = zoneinfo.ZoneInfo(from_timezone_name)
        to_tz = zoneinfo.ZoneInfo(to_timezone_name)
    except zoneinfo.ZoneInfoNotFoundError as exc:
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=f"Invalid timezone after resolution: {exc}",
            context=context,
            metadata={
                "from_timezone": from_timezone_name,
                "to_timezone": to_timezone_name,
            },
        )

    if parsed_dt.tzinfo is None:
        source_dt = parsed_dt.replace(tzinfo=from_tz)
    else:
        source_dt = parsed_dt.astimezone(from_tz)

    converted_dt = source_dt.astimezone(to_tz)

    source_resolution_meta = {
        "query": from_resolution.get("query", from_tz_input),
        "resolvedTimezone": from_timezone_name,
        "label": from_resolution.get("label"),
        "isAmbiguousDefault": from_resolution.get("is_ambiguous_default", False),
        "resolutionType": from_resolution.get("resolution_type", "alias"),
    }

    destination_resolution_meta = {
        "query": to_resolution.get("query", to_tz_input),
        "resolvedTimezone": to_timezone_name,
        "label": to_resolution.get("label"),
        "isAmbiguousDefault": to_resolution.get("is_ambiguous_default", False),
        "resolutionType": to_resolution.get("resolution_type", "alias"),
    }

    return {
        "status": "success",
        "mode": mode,
        "source": "system_clock",
        "provider": "system_clock",
        "provider_status": "ok",
        "external_sync": {
            "checked": False,
            "available": False,
            "provider": None,
            "offset_ms": None,
        },
        "source_detail": {
            "clock": "local_os_clock",
            "timezone_source": "zoneinfo",
            "storage": "stateless",
            "durable": False,
        },
        "source_datetime": {
            "datetime": source_dt.isoformat(),
            "timezone": from_timezone_name,
            "utc_offset": TimeHandlerBase.format_utc_offset(source_dt),
            "date": source_dt.date().isoformat(),
            "time": source_dt.time().replace(microsecond=0).isoformat(),
            "resolution_meta": source_resolution_meta,
        },
        "converted_datetime": {
            "datetime": converted_dt.isoformat(),
            "timezone": to_timezone_name,
            "utc_offset": TimeHandlerBase.format_utc_offset(converted_dt),
            "date": converted_dt.date().isoformat(),
            "time": converted_dt.time().replace(microsecond=0).isoformat(),
            "resolution_meta": destination_resolution_meta,
        },
        "value": converted_dt.isoformat(),
        "metadata": {
            "request_format": output_format,
            "context_hints": TimeHandlerBase.extract_context_hints(context),
        },
    }
