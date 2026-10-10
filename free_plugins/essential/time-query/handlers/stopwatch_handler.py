import datetime
from typing import Any, Dict

from .base import TimeHandlerBase, TimeStateStore, StopwatchState


SUPPORTED_STOPWATCH_ACTIONS = {
    "create",
    "delete",
    "list",
    "start",
    "pause",
    "resume",
    "stop",
    "reset",
    "status",
}

DEFAULT_STOPWATCH_ID = "default"


def _now_utc() -> datetime.datetime:
    return TimeHandlerBase.get_system_now_utc()


def _compute_elapsed_ms(stopwatch: StopwatchState, now_utc: datetime.datetime) -> int:
    elapsed_ms = stopwatch.elapsed_ms
    if stopwatch.running and stopwatch.started_at is not None:
        elapsed_ms += max(int((now_utc - stopwatch.started_at).total_seconds() * 1000), 0)
    return elapsed_ms


def _stopwatch_response(
    stopwatch: StopwatchState,
    *,
    action: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    now_utc = _now_utc()
    elapsed_ms = _compute_elapsed_ms(stopwatch, now_utc)

    return {
        "status": "success",
        "mode": "stopwatch",
        "action": action,
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
            "timezone_source": "system",
            "storage": "in_memory",
            "durable": False,
        },
        "stopwatch": {
            **stopwatch.snapshot(),
            "elapsed_ms": elapsed_ms,
        },
        "value": elapsed_ms,
        "metadata": {
            "context_hints": TimeHandlerBase.extract_context_hints(context),
        },
    }


async def handle_stopwatch(params: Dict[str, Any]) -> Dict[str, Any]:
    mode = "stopwatch"
    context = TimeHandlerBase.normalize_dict(params.get("context"))
    action = (TimeHandlerBase.normalize_string(params.get("action")) or "status").lower()
    stopwatch_id = TimeHandlerBase.normalize_string(params.get("stopwatch_id")) or DEFAULT_STOPWATCH_ID
    label = TimeHandlerBase.normalize_string(params.get("label"))

    if action not in SUPPORTED_STOPWATCH_ACTIONS:
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=f"Unsupported stopwatch action: {action}",
            context=context,
            metadata={"stopwatch_id": stopwatch_id},
        )

    with TimeStateStore.lock():
        store = TimeStateStore.stopwatches()
        stopwatch = store.get(stopwatch_id)
        now_utc = _now_utc()

        if action == "list":
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
                    "timezone_source": "system",
                    "storage": "in_memory",
                    "durable": False,
                },
                "stopwatches": [
                    {
                        **sw.snapshot(),
                        "elapsed_ms": _compute_elapsed_ms(sw, now_utc),
                    }
                    for sw in store.values()
                ],
                "metadata": {
                    "context_hints": TimeHandlerBase.extract_context_hints(context),
                },
            }

        if action == "delete":
            removed = store.pop(stopwatch_id, None)
            return {
                "status": "success",
                "mode": mode,
                "action": "delete",
                "stopwatch_id": stopwatch_id,
                "deleted": removed is not None,
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
                    "timezone_source": "system",
                    "storage": "in_memory",
                    "durable": False,
                },
                "metadata": {
                    "context_hints": TimeHandlerBase.extract_context_hints(context),
                },
            }

        if action == "create":
            if stopwatch is None:
                stopwatch = StopwatchState(
                    stopwatch_id=stopwatch_id,
                    created_at=now_utc,
                    label=label,
                )
                store[stopwatch_id] = stopwatch
            elif label:
                stopwatch.label = label
                stopwatch.last_updated_at = now_utc

            return _stopwatch_response(stopwatch, action="create", context=context)

        if stopwatch is None:
            stopwatch = StopwatchState(
                stopwatch_id=stopwatch_id,
                created_at=now_utc,
                label=label,
            )
            store[stopwatch_id] = stopwatch
        elif label:
            stopwatch.label = label

        if action == "start":
            if not stopwatch.running:
                stopwatch.running = True
                stopwatch.paused = False
                stopwatch.started_at = now_utc
                stopwatch.last_updated_at = now_utc
            return _stopwatch_response(stopwatch, action="start", context=context)

        if action == "pause":
            if stopwatch.running and not stopwatch.paused and stopwatch.started_at is not None:
                stopwatch.elapsed_ms += max(
                    int((now_utc - stopwatch.started_at).total_seconds() * 1000),
                    0,
                )
                stopwatch.running = False
                stopwatch.paused = True
                stopwatch.started_at = None
                stopwatch.last_updated_at = now_utc
            return _stopwatch_response(stopwatch, action="pause", context=context)

        if action == "resume":
            if stopwatch.paused:
                stopwatch.running = True
                stopwatch.paused = False
                stopwatch.started_at = now_utc
                stopwatch.last_updated_at = now_utc
            return _stopwatch_response(stopwatch, action="resume", context=context)

        if action == "stop":
            if stopwatch.running and stopwatch.started_at is not None:
                stopwatch.elapsed_ms += max(
                    int((now_utc - stopwatch.started_at).total_seconds() * 1000),
                    0,
                )
            stopwatch.running = False
            stopwatch.paused = False
            stopwatch.started_at = None
            stopwatch.last_updated_at = now_utc
            return _stopwatch_response(stopwatch, action="stop", context=context)

        if action == "reset":
            stopwatch.running = False
            stopwatch.paused = False
            stopwatch.elapsed_ms = 0
            stopwatch.started_at = None
            stopwatch.last_updated_at = now_utc
            return _stopwatch_response(stopwatch, action="reset", context=context)

        return _stopwatch_response(stopwatch, action="status", context=context)