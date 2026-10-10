from typing import Any, Dict, List

from .base import TimeHandlerBase, TimeStateStore, SavedClockState


SUPPORTED_MULTI_CLOCK_ACTIONS = {
    "resolve",
    "add",
    "remove",
    "list",
    "replace",
}


def _clock_error_item(query: str, error: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "label": query,
        "timezone": query,
        "error": error,
    }


def _build_resolved_clock_item(
    *,
    query: str,
    timezone_name: str,
    resolution_meta: Dict[str, Any],
    clock_id: str | None = None,
    label: str | None = None,
) -> Dict[str, Any]:
    return {
        **TimeHandlerBase.build_clock_entry(
            label=label or resolution_meta.get("label") or TimeHandlerBase.display_label_for_timezone(query, timezone_name),
            timezone_name=timezone_name,
            clock_id=clock_id,
            resolution_meta={
                "query": resolution_meta.get("query", query),
                "resolvedTimezone": timezone_name,
                "label": resolution_meta.get("label"),
                "isAmbiguousDefault": resolution_meta.get("is_ambiguous_default", False),
                "resolutionType": resolution_meta.get("resolution_type", "alias"),
            },
        ),
        "status": "success",
    }


async def handle_multi_clock(params: Dict[str, Any]) -> Dict[str, Any]:
    mode = "multi_clock"
    context = TimeHandlerBase.normalize_dict(params.get("context"))
    output_format = TimeHandlerBase.normalize_string(params.get("format"))
    action = (TimeHandlerBase.normalize_string(params.get("action")) or "resolve").lower()

    if action not in SUPPORTED_MULTI_CLOCK_ACTIONS:
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=f"Unsupported multi_clock action: {action}",
            context=context,
        )

    if action == "resolve":
        clocks = TimeHandlerBase.normalize_string_list(params.get("clocks"))
        if not clocks:
            return TimeHandlerBase.error_payload(
                mode=mode,
                error="clocks list is required for resolve",
                context=context,
            )

        results: List[Dict[str, Any]] = []
        for query in clocks:
            resolved = TimeHandlerBase.resolve_timezone(query)
            if not resolved.get("success"):
                results.append(_clock_error_item(query, resolved.get("error", "Failed resolution")))
                continue

            timezone_name = resolved["timezone"]
            results.append(
                _build_resolved_clock_item(
                    query=query,
                    timezone_name=timezone_name,
                    resolution_meta=resolved,
                )
            )

        return {
            "status": "success",
            "mode": mode,
            "action": "resolve",
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
            "clocks": results,
            "value": results,
            "metadata": {
                "request_format": output_format,
                "context_hints": TimeHandlerBase.extract_context_hints(context),
            },
        }

    with TimeStateStore.lock():
        store = TimeStateStore.saved_clocks()

        if action == "list":
            items: List[Dict[str, Any]] = []
            for clock_id, clock in store.items():
                items.append(
                    _build_resolved_clock_item(
                        query=clock.label,
                        timezone_name=clock.timezone_name,
                        resolution_meta={
                            "query": clock.label,
                            "label": clock.label,
                            "timezone": clock.timezone_name,
                            "is_ambiguous_default": False,
                            "resolution_type": "saved_clock",
                        },
                        clock_id=clock_id,
                        label=clock.label,
                    )
                )

            return {
                "status": "success",
                "mode": mode,
                "action": "list",
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
                    "storage": "in_memory",
                    "durable": False,
                },
                "clocks": items,
                "value": items,
                "metadata": {
                    "request_format": output_format,
                    "context_hints": TimeHandlerBase.extract_context_hints(context),
                },
            }

        if action == "add":
            timezone_input = (
                TimeHandlerBase.normalize_string(params.get("timezone"))
                or TimeHandlerBase.normalize_string(params.get("location"))
                or TimeHandlerBase.normalize_string(params.get("query"))
            )
            label = TimeHandlerBase.normalize_string(params.get("label"))

            if not timezone_input:
                return TimeHandlerBase.error_payload(
                    mode=mode,
                    error="timezone, location, or query is required for add",
                    context=context,
                )

            resolved = TimeHandlerBase.resolve_timezone(timezone_input)
            if not resolved.get("success"):
                return TimeHandlerBase.error_payload(
                    mode=mode,
                    error=resolved.get("error", "Failed resolution"),
                    context=context,
                    metadata={"query": timezone_input},
                )

            clock_id = TimeHandlerBase.generate_alarm_id()
            clock_label = label or resolved.get("label") or TimeHandlerBase.display_label_for_timezone(
                timezone_input,
                resolved["timezone"],
            )

            store[clock_id] = SavedClockState(
                clock_id=clock_id,
                label=clock_label,
                timezone_name=resolved["timezone"],
            )

            # Return full list after mutation
            items: List[Dict[str, Any]] = []
            for saved_clock_id, saved_clock in store.items():
                items.append(
                    _build_resolved_clock_item(
                        query=saved_clock.label,
                        timezone_name=saved_clock.timezone_name,
                        resolution_meta={
                            "query": saved_clock.label,
                            "label": saved_clock.label,
                            "timezone": saved_clock.timezone_name,
                            "is_ambiguous_default": False,
                            "resolution_type": "saved_clock",
                        },
                        clock_id=saved_clock_id,
                        label=saved_clock.label,
                    )
                )

            return {
                "status": "success",
                "mode": mode,
                "action": "add",
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
                    "storage": "in_memory",
                    "durable": False,
                },
                "clocks": items,
                "value": items,
                "metadata": {
                    "request_format": output_format,
                    "context_hints": TimeHandlerBase.extract_context_hints(context),
                },
            }

        if action == "remove":
            clock_id = TimeHandlerBase.normalize_string(params.get("clock_id"))
            if not clock_id:
                return TimeHandlerBase.error_payload(
                    mode=mode,
                    error="clock_id is required for remove",
                    context=context,
                )

            removed = store.pop(clock_id, None)

            items: List[Dict[str, Any]] = []
            for saved_clock_id, saved_clock in store.items():
                items.append(
                    _build_resolved_clock_item(
                        query=saved_clock.label,
                        timezone_name=saved_clock.timezone_name,
                        resolution_meta={
                            "query": saved_clock.label,
                            "label": saved_clock.label,
                            "timezone": saved_clock.timezone_name,
                            "is_ambiguous_default": False,
                            "resolution_type": "saved_clock",
                        },
                        clock_id=saved_clock_id,
                        label=saved_clock.label,
                    )
                )

            return {
                "status": "success",
                "mode": mode,
                "action": "remove",
                "removed": removed is not None,
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
                    "storage": "in_memory",
                    "durable": False,
                },
                "clocks": items,
                "value": items,
                "metadata": {
                    "request_format": output_format,
                    "context_hints": TimeHandlerBase.extract_context_hints(context),
                },
            }

        # replace
        clocks_payload = TimeHandlerBase.normalize_list_of_dicts(params.get("clocks_payload"))
        if not clocks_payload:
            return TimeHandlerBase.error_payload(
                mode=mode,
                error="clocks_payload is required for replace",
                context=context,
            )

        store.clear()

        for clock in clocks_payload:
            timezone_input = (
                TimeHandlerBase.normalize_string(clock.get("timezone"))
                or TimeHandlerBase.normalize_string(clock.get("location"))
                or TimeHandlerBase.normalize_string(clock.get("query"))
            )
            label = TimeHandlerBase.normalize_string(clock.get("label"))

            if not timezone_input:
                continue

            resolved = TimeHandlerBase.resolve_timezone(timezone_input)
            if not resolved.get("success"):
                continue

            clock_id = TimeHandlerBase.generate_alarm_id()
            clock_label = label or resolved.get("label") or TimeHandlerBase.display_label_for_timezone(
                timezone_input,
                resolved["timezone"],
            )

            store[clock_id] = SavedClockState(
                clock_id=clock_id,
                label=clock_label,
                timezone_name=resolved["timezone"],
            )

        items: List[Dict[str, Any]] = []
        for saved_clock_id, saved_clock in store.items():
            items.append(
                _build_resolved_clock_item(
                    query=saved_clock.label,
                    timezone_name=saved_clock.timezone_name,
                    resolution_meta={
                        "query": saved_clock.label,
                        "label": saved_clock.label,
                        "timezone": saved_clock.timezone_name,
                        "is_ambiguous_default": False,
                        "resolution_type": "saved_clock",
                    },
                    clock_id=saved_clock_id,
                    label=saved_clock.label,
                )
            )

        return {
            "status": "success",
            "mode": mode,
            "action": "replace",
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
                "storage": "in_memory",
                "durable": False,
            },
            "clocks": items,
            "value": items,
            "metadata": {
                "request_format": output_format,
                "context_hints": TimeHandlerBase.extract_context_hints(context),
            },
        }