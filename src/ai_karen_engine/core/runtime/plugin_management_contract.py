"""Verified, non-executable plugin management status presentation contract.

This projection never authorizes, approves, executes or persists a plugin
mutation. It validates a small subset of the canonical PluginService preflight
for AG-UI transport and attested saved-history replay.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_STATES = frozenset({
    "needs_explicit_confirmation", "already_satisfied", "permission_denied",
    "unavailable_installation", "unsupported_state",
    "delegated_to_channel_host", "delegated_to_voice_runtime",
})
_NEXT = {
    "needs_explicit_confirmation": "plugin.open_admin_management",
    "already_satisfied": "plugin.verify_runtime_state",
    "permission_denied": None,
    "unavailable_installation": None,
    "unsupported_state": None,
    "delegated_to_channel_host": "channel.inspect_and_request_operator_authorization",
    "delegated_to_voice_runtime": "voice.inspect_and_request_operator_authorization",
}
_KEYS = frozenset({
    "installation_id", "requested_action", "operation_scope",
    "required_permission", "permission_verified", "approval_granted",
    "mutation_performed", "action_receipt", "next_action", "status",
    "current_state", "confirmation_channel",
})
_PLUGIN_ID = re.compile(r"[a-z][a-z0-9_-]{0,49}\Z")


def validate_plugin_management_preflight(raw: Any) -> dict[str, Any] | None:
    """Return a bounded safe rendering envelope, or reject contradictory data."""
    if (
        not isinstance(raw, Mapping)
        or not set(raw).issubset(_KEYS)
        or not set(_KEYS - {"current_state", "confirmation_channel"}).issubset(raw)
        or not isinstance(raw.get("installation_id"), str)
        or not _PLUGIN_ID.fullmatch(raw["installation_id"])
        or not isinstance(raw.get("requested_action"), str)
        or raw["requested_action"] not in {"enable", "disable"}
        or raw.get("operation_scope") != "application_global"
        or raw.get("required_permission") != "admin.plugins:manage"
        or type(raw.get("permission_verified")) is not bool
        or raw.get("approval_granted") is not False
        or raw.get("mutation_performed") is not False
        or raw.get("action_receipt") is not None
        or not isinstance(raw.get("status"), str)
        or raw["status"] not in _STATES
    ):
        return None

    status = raw["status"]
    permitted = raw["permission_verified"]
    if raw.get("next_action") != _NEXT[status]:
        return None
    if permitted != (status in {
        "needs_explicit_confirmation", "already_satisfied", "unsupported_state",
    }):
        return None
    confirmation = raw.get("confirmation_channel")
    if (
        (status == "needs_explicit_confirmation"
         and confirmation != "authenticated_plugin_management_ui")
        or (status != "needs_explicit_confirmation" and confirmation is not None)
    ):
        return None
    current = raw.get("current_state")
    if current is not None and (
        not isinstance(current, str)
        or not re.fullmatch(r"[a-z][a-z_]{1,31}", current)
    ):
        return None
    if status in {"already_satisfied", "permission_denied", "unsupported_state",
                  "needs_explicit_confirmation"} and current is None:
        return None
    if status in {"unavailable_installation", "delegated_to_channel_host",
                  "delegated_to_voice_runtime"} and current is not None:
        return None
    # Render only validated fields, never pass a caller-owned mapping or
    # miscellaneous plugin settings/secret handles to the event projection.
    result = {
        "installation_id": raw["installation_id"],
        "requested_action": raw["requested_action"],
        "operation_scope": "application_global",
        "required_permission": "admin.plugins:manage",
        "permission_verified": permitted,
        "approval_granted": False,
        "mutation_performed": False,
        "action_receipt": None,
        "status": status,
        "next_action": _NEXT[status],
    }
    if current is not None:
        result["current_state"] = current
    if confirmation is not None:
        result["confirmation_channel"] = confirmation
    if len(json.dumps(result, sort_keys=True)) > 1500:
        return None
    return result
