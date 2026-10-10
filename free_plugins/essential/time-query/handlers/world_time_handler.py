import datetime
import zoneinfo
from typing import Any, Dict, Optional

from .base import TimeHandlerBase, TimeProviderError


async def handle_world_time(params: Dict[str, Any]) -> Dict[str, Any]:
    mode = "world_time"
    context = TimeHandlerBase.normalize_dict(params.get("context"))
    output_format = TimeHandlerBase.normalize_string(params.get("format"))

    query = (
        TimeHandlerBase.normalize_string(params.get("query"))
        or TimeHandlerBase.normalize_string(params.get("location"))
        or TimeHandlerBase.normalize_string(params.get("country"))
        or TimeHandlerBase.normalize_string(params.get("city"))
        or TimeHandlerBase.normalize_string(params.get("timezone"))
    )

    if not query:
        return TimeHandlerBase.error_payload(
            mode=mode,
            error="Missing timezone or location query",
            context=context,
        )

    resolved = TimeHandlerBase.resolve_timezone(query)

    if not resolved.get("success"):
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=resolved.get("error", "Could not resolve timezone"),
            context=context,
            metadata={
                "query": query,
            },
        )

    tz_name = resolved["timezone"]

    try:
        local_now = TimeHandlerBase.get_system_now(tz_name)
        utc_now = TimeHandlerBase.get_system_now_utc()
    except zoneinfo.ZoneInfoNotFoundError:
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=f"Unknown timezone '{tz_name}' after resolution",
            context=context,
            metadata={
                "query": query,
                "resolved_timezone": tz_name,
            },
        )

    provider_name = TimeHandlerBase.resolve_provider_name(params.get("provider"))
    external_sync = {
        "checked": False,
        "available": False,
        "provider": None,
        "offset_ms": None,
    }
    provider_status = "ok"

    if provider_name != "system_clock":
        provider_chain = TimeHandlerBase.provider_chain_for_request(provider_name)
        sync_errors = []

        for provider_candidate in provider_chain:
            if provider_candidate == "system_clock":
                continue

            try:
                provider = TimeHandlerBase.provider_for_name(provider_candidate)
                validation = provider.validate_against_system_clock(
                    system_now_utc=utc_now,
                    timezone_name=tz_name,
                )
                external_sync = validation
                provider_status = "ok"
                provider_name = provider_candidate
                break
            except (TimeProviderError, zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
                sync_errors.append(f"{provider_candidate}: {exc}")

        if not external_sync.get("available"):
            provider_status = "unavailable"
            external_sync = {
                "checked": True,
                "available": False,
                "provider": provider_name,
                "offset_ms": None,
                "errors": sync_errors,
            }

    payload = TimeHandlerBase.build_base_time_payload(
        mode=mode,
        now_local=local_now,
        now_utc=utc_now,
        output_format=output_format,
        context=context,
        provider=provider_name,
        provider_status=provider_status,
        external_sync=external_sync,
        source_detail={
            "clock": "local_os_clock",
            "timezone_source": "zoneinfo",
            "external_sync_checked": external_sync.get("checked", False),
            "storage": "stateless",
        },
        resolution_meta={
            "query": resolved.get("query", query),
            "resolvedTimezone": tz_name,
            "label": resolved.get("label"),
            "isAmbiguousDefault": resolved.get("is_ambiguous_default", False),
            "resolutionType": resolved.get("resolution_type", "alias"),
        },
    )

    payload.update(
        {
            "label": resolved.get("label") or TimeHandlerBase.display_label_for_timezone(query, tz_name),
            "resolved_timezone": tz_name,
            "query_location": resolved.get("query", query),
            "value": payload["formatted"],
        }
    )

    return payload