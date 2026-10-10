import datetime
import zoneinfo
from typing import Any, Dict, List
 
from .base import AlarmState, TimeHandlerBase, TimeStateStore


SUPPORTED_ALARM_ACTIONS = {
    "create",
    "list",
    "update",
    "delete",
    "enable",
    "disable",
    "status",
}


def _alarm_response(
    alarm: AlarmState,
    *,
    action: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": "success",
        "mode": "alarm",
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
            "timezone_source": "zoneinfo",
            "storage": "in_memory",
            "durable": False,
        },
        "scheduler_status": {
            "integrated": False,
            "ready": False,
            "note": "Alarm definitions are stored, but external scheduling integration is not yet wired here.",
        },
        "alarm": alarm.snapshot(),
        "value": alarm.snapshot(),
        "metadata": {
            "context_hints": TimeHandlerBase.extract_context_hints(context),
        },
    }


def _alarm_list_response(
    alarms: List[AlarmState],
    *,
    action: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    snapshots = [alarm.snapshot() for alarm in alarms]
    return {
        "status": "success",
        "mode": "alarm",
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
            "timezone_source": "zoneinfo",
            "storage": "in_memory",
            "durable": False,
        },
        "scheduler_status": {
            "integrated": False,
            "ready": False,
            "note": "Alarm definitions are stored, but external scheduling integration is not yet wired here.",
        },
        "alarms": snapshots,
        "value": snapshots,
        "metadata": {
            "context_hints": TimeHandlerBase.extract_context_hints(context),
        },
    }


async def handle_alarm(params: Dict[str, Any]) -> Dict[str, Any]:
    mode = "alarm"
    context = TimeHandlerBase.normalize_dict(params.get("context"))
    action = (TimeHandlerBase.normalize_string(params.get("action")) or "list").lower()

    if action not in SUPPORTED_ALARM_ACTIONS:
        return TimeHandlerBase.error_payload(
            mode=mode,
            error=f"Unknown action: {action}",
            context=context,
        )

    with TimeStateStore.lock():
        store = TimeStateStore.alarms()

        if action == "list":
            return _alarm_list_response(list(store.values()), action="list", context=context)

        if action == "create":
            title = TimeHandlerBase.normalize_string(params.get("title")) or "New Alarm"
            alarm_datetime_raw = TimeHandlerBase.normalize_string(params.get("alarm_datetime"))
            timezone_input = TimeHandlerBase.normalize_string(params.get("timezone")) or "UTC"
            recurrence = TimeHandlerBase.normalize_string(params.get("recurrence"))
            enabled = bool(params.get("enabled", True))
            metadata = TimeHandlerBase.normalize_dict(params.get("metadata"))

            if not alarm_datetime_raw:
                return TimeHandlerBase.error_payload(
                    mode=mode,
                    error="alarm_datetime is required for create",
                    context=context,
                )

            resolved_tz = TimeHandlerBase.resolve_timezone(timezone_input)
            if not resolved_tz.get("success"):
                return TimeHandlerBase.error_payload(
                    mode=mode,
                    error=f"Invalid timezone: {resolved_tz.get('error')}",
                    context=context,
                    metadata={"query": timezone_input},
                )

            parsed_dt = TimeHandlerBase.parse_datetime(alarm_datetime_raw)
            if not parsed_dt:
                return TimeHandlerBase.error_payload(
                    mode=mode,
                    error="Invalid alarm_datetime format. Use ISO-8601-compatible datetime.",
                    context=context,
                )

            timezone_name = resolved_tz["timezone"]
            tz = zoneinfo.ZoneInfo(timezone_name)  # type: ignore[name-defined]

            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=tz)
            else:
                parsed_dt = parsed_dt.astimezone(tz)

            now_utc = TimeHandlerBase.get_system_now_utc()
            alarm = AlarmState(
                alarm_id=TimeHandlerBase.generate_alarm_id(),
                title=title,
                alarm_datetime=parsed_dt,
                timezone_name=timezone_name,
                enabled=enabled,
                recurrence=recurrence,
                created_at=now_utc,
                updated_at=now_utc,
                metadata=metadata,
            )
            store[alarm.alarm_id] = alarm
            return _alarm_response(alarm, action="create", context=context)

        alarm_id = TimeHandlerBase.normalize_string(params.get("alarm_id"))
        if not alarm_id:
            return TimeHandlerBase.error_payload(
                mode=mode,
                error="alarm_id required",
                context=context,
            )

        alarm = store.get(alarm_id)
        if alarm is None:
            return TimeHandlerBase.error_payload(
                mode=mode,
                error="alarm not found",
                context=context,
                metadata={"alarm_id": alarm_id},
            )

        if action == "status":
            return _alarm_response(alarm, action="status", context=context)

        if action == "delete":
            deleted = store.pop(alarm_id)
            return {
                "status": "success",
                "mode": mode,
                "action": "delete",
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
                "scheduler_status": {
                    "integrated": False,
                    "ready": False,
                    "note": "Alarm definitions are stored, but external scheduling integration is not yet wired here.",
                },
                "deleted": deleted.snapshot(),
                "value": deleted.snapshot(),
                "metadata": {
                    "context_hints": TimeHandlerBase.extract_context_hints(context),
                },
            }

        if action == "enable":
            alarm.enabled = True
            alarm.updated_at = TimeHandlerBase.get_system_now_utc()
            return _alarm_response(alarm, action="enable", context=context)

        if action == "disable":
            alarm.enabled = False
            alarm.updated_at = TimeHandlerBase.get_system_now_utc()
            return _alarm_response(alarm, action="disable", context=context)

        # update
        title = TimeHandlerBase.normalize_string(params.get("title"))
        alarm_datetime_raw = TimeHandlerBase.normalize_string(params.get("alarm_datetime"))
        timezone_input = TimeHandlerBase.normalize_string(params.get("timezone"))
        recurrence = TimeHandlerBase.normalize_string(params.get("recurrence"))
        metadata = TimeHandlerBase.normalize_dict(params.get("metadata"))

        if title:
            alarm.title = title

        if timezone_input:
            resolved_tz = TimeHandlerBase.resolve_timezone(timezone_input)
            if not resolved_tz.get("success"):
                return TimeHandlerBase.error_payload(
                    mode=mode,
                    error=f"Invalid timezone update: {resolved_tz.get('error')}",
                    context=context,
                    metadata={"query": timezone_input, "alarm_id": alarm_id},
                )
            alarm.timezone_name = resolved_tz["timezone"]

        if alarm_datetime_raw:
            parsed_dt = TimeHandlerBase.parse_datetime(alarm_datetime_raw)
            if not parsed_dt:
                return TimeHandlerBase.error_payload(
                    mode=mode,
                    error="Invalid alarm_datetime format. Use ISO-8601-compatible datetime.",
                    context=context,
                    metadata={"alarm_id": alarm_id},
                )

            tz = zoneinfo.ZoneInfo(alarm.timezone_name)  # type: ignore[name-defined]
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=tz)
            else:
                parsed_dt = parsed_dt.astimezone(tz)

            alarm.alarm_datetime = parsed_dt

        if "enabled" in params:
            alarm.enabled = bool(params.get("enabled"))

        if recurrence is not None:
            alarm.recurrence = recurrence

        if metadata:
            alarm.metadata.update(metadata)

        alarm.updated_at = TimeHandlerBase.get_system_now_utc()
        return _alarm_response(alarm, action="update", context=context)