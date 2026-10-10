from typing import Any, Dict
import zoneinfo
 
from .base import TimeHandlerBase, TimeProviderError


SUPPORTED_CURRENT_TIME_MODES = {
    "datetime",
    "date",
    "time",
    "timestamp",
    "timezone",
    "iso",
    "utc",
    "external_time",
    "sync_status",
    "validate_time_source",
}


def _build_value_for_mode(mode: str, payload: Dict[str, Any]) -> Any:
    if mode == "date":
        return payload["date"]
    if mode == "time":
        return payload["time"]
    if mode == "timestamp":
        return payload["timestamp_unix"]
    if mode == "timezone":
        return {
            "timezone": payload["timezone"],
            "utc_offset": payload["utc_offset"],
        }
    if mode == "iso":
        return payload["iso"]
    if mode == "utc":
        return payload["timestamp_utc"]
    return payload["formatted"]


async def handle_current_time(mode: str, params: Dict[str, Any]) -> Dict[str, Any]:
    context = TimeHandlerBase.normalize_dict(params.get("context"))
    output_format = TimeHandlerBase.normalize_string(params.get("format"))
    resolved_mode = (TimeHandlerBase.normalize_string(mode) or "datetime").lower()

    if resolved_mode not in SUPPORTED_CURRENT_TIME_MODES:
        return TimeHandlerBase.error_payload(
            mode=resolved_mode,
            error=f"Unsupported current time mode: {resolved_mode}",
            context=context,
        )

    # Keep external provider-only modes explicitly separate.
    if resolved_mode in {"external_time", "sync_status", "validate_time_source"}:
        provider_name = TimeHandlerBase.resolve_provider_name(params.get("provider"))
        provider_chain = TimeHandlerBase.provider_chain_for_request(provider_name)
        timezone_input = TimeHandlerBase.normalize_string(params.get("timezone"))
        resolved_timezone = None

        if timezone_input:
            tz_resolution = TimeHandlerBase.resolve_timezone(timezone_input)
            if not tz_resolution.get("success"):
                return TimeHandlerBase.error_payload(
                    mode=resolved_mode,
                    error=tz_resolution.get("error", "Could not resolve timezone"),
                    context=context,
                    metadata={"query": timezone_input},
                )
            resolved_timezone = tz_resolution["timezone"]

        system_now_utc = TimeHandlerBase.get_system_now_utc()
        errors = []

        if resolved_mode == "external_time":
            for provider_candidate in provider_chain:
                try:
                    provider = TimeHandlerBase.provider_for_name(provider_candidate)
                    provider_payload = provider.fetch_current_time(timezone_name=resolved_timezone)
                    return {
                        "status": "success",
                        "mode": resolved_mode,
                        "source": "system_clock",
                        "provider": provider_candidate,
                        "provider_status": "ok",
                        "external_sync": {
                            "checked": True,
                            "available": True,
                            "provider": provider_candidate,
                            "offset_ms": None,
                        },
                        "source_detail": {
                            "clock": "local_os_clock",
                            "timezone_source": "system" if not resolved_timezone else "zoneinfo",
                            "external_sync_checked": True,
                            "storage": "stateless",
                        },
                        "provider_payload": provider_payload,
                        "value": provider_payload.get("timestamp") or provider_payload.get("timestamp_utc"),
                        "metadata": {
                            "request_format": output_format,
                            "context_hints": TimeHandlerBase.extract_context_hints(context),
                            "requested_provider": provider_name,
                            "resolved_timezone": resolved_timezone,
                            "provider_chain": provider_chain,
                        },
                    }
                except (TimeProviderError, ValueError, zoneinfo.ZoneInfoNotFoundError) as exc:  # type: ignore[name-defined]
                    errors.append(f"{provider_candidate}: {exc}")

            return TimeHandlerBase.error_payload(
                mode=resolved_mode,
                error="All external providers failed",
                context=context,
                metadata={
                    "requested_provider": provider_name,
                    "resolved_timezone": resolved_timezone,
                    "provider_chain": provider_chain,
                    "provider_errors": errors,
                },
            )

        for provider_candidate in provider_chain:
            if provider_candidate == "system_clock":
                continue
            try:
                provider = TimeHandlerBase.provider_for_name(provider_candidate)
                validation = provider.validate_against_system_clock(
                    system_now_utc=system_now_utc,
                    timezone_name=resolved_timezone,
                )
                return {
                    "status": "success",
                    "mode": resolved_mode,
                    "source": "system_clock",
                    "provider": provider_candidate,
                    "provider_status": "ok",
                    "external_sync": validation,
                    "source_detail": {
                        "clock": "local_os_clock",
                        "timezone_source": "system" if not resolved_timezone else "zoneinfo",
                        "external_sync_checked": True,
                        "storage": "stateless",
                    },
                    "system_timestamp_utc": system_now_utc.isoformat(),
                    "value": validation,
                    "metadata": {
                        "request_format": output_format,
                        "context_hints": TimeHandlerBase.extract_context_hints(context),
                        "requested_provider": provider_name,
                        "resolved_timezone": resolved_timezone,
                        "provider_chain": provider_chain,
                    },
                }
            except (TimeProviderError, ValueError, zoneinfo.ZoneInfoNotFoundError) as exc:  # type: ignore[name-defined]
                errors.append(f"{provider_candidate}: {exc}")

        return {
            "status": "success",
            "mode": resolved_mode,
            "source": "system_clock",
            "provider": provider_name,
            "provider_status": "unavailable",
            "external_sync": {
                "checked": True,
                "available": False,
                "provider": provider_name,
                "offset_ms": None,
                "errors": errors,
            },
            "source_detail": {
                "clock": "local_os_clock",
                "timezone_source": "system" if not resolved_timezone else "zoneinfo",
                "external_sync_checked": True,
                "storage": "stateless",
            },
            "system_timestamp_utc": system_now_utc.isoformat(),
            "value": {
                "checked": True,
                "available": False,
                "provider": provider_name,
                "offset_ms": None,
                "errors": errors,
            },
            "metadata": {
                "request_format": output_format,
                "context_hints": TimeHandlerBase.extract_context_hints(context),
                "requested_provider": provider_name,
                "resolved_timezone": resolved_timezone,
                "provider_chain": provider_chain,
            },
        }

    timezone_input = TimeHandlerBase.normalize_string(params.get("timezone"))
    resolution_meta = None
    timezone_name = None

    if timezone_input:
        tz_resolution = TimeHandlerBase.resolve_timezone(timezone_input)
        if not tz_resolution.get("success"):
            return TimeHandlerBase.error_payload(
                mode=resolved_mode,
                error=tz_resolution.get("error", "Could not resolve timezone"),
                context=context,
                metadata={"query": timezone_input},
            )
        timezone_name = tz_resolution["timezone"]
        resolution_meta = {
            "query": tz_resolution.get("query", timezone_input),
            "resolvedTimezone": timezone_name,
            "label": tz_resolution.get("label"),
            "isAmbiguousDefault": tz_resolution.get("is_ambiguous_default", False),
            "resolutionType": tz_resolution.get("resolution_type", "alias"),
        }

    local_now = TimeHandlerBase.get_system_now(timezone_name)
    utc_now = TimeHandlerBase.get_system_now_utc()

    payload = TimeHandlerBase.build_base_time_payload(
        mode=resolved_mode,
        now_local=local_now,
        now_utc=utc_now,
        output_format=output_format,
        context=context,
        provider="system_clock",
        provider_status="ok",
        external_sync={
            "checked": False,
            "available": False,
            "provider": None,
            "offset_ms": None,
        },
        source_detail={
            "clock": "local_os_clock",
            "timezone_source": "system" if not timezone_name else "zoneinfo",
            "external_sync_checked": False,
            "storage": "stateless",
        },
        resolution_meta=resolution_meta,
    )

    payload["value"] = _build_value_for_mode(resolved_mode, payload)

    return payload