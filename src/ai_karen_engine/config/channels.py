"""Validated, disabled-by-default settings for the canonical channel host.

Transport installations and secret names are operator-supplied configuration,
not inferred from native provider events, prompt text or plugin input. Channel
activation remains an explicit per-tenant RuntimePolicy decision.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Mapping


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SECRET_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}$")


@dataclass(frozen=True)
class ChannelHostSettings:
    enabled: bool = False
    installations: Mapping[str, frozenset[str]] = field(default_factory=dict)
    service_principal_id: str = ""
    max_native_body_bytes: int = 65_536
    http_timeout_seconds: float = 10.0

    def validate(self) -> "ChannelHostSettings":
        if not 1 <= self.max_native_body_bytes <= 10_485_760:
            raise ValueError("Channel native request budget must be 1..10485760")
        if not 0.5 <= self.http_timeout_seconds <= 60:
            raise ValueError("Channel network timeout must be 0.5..60 seconds")
        if not self.enabled:
            # Never parse or activate configured installations on a disabled host.
            return self
        if (
            not self.installations
            or len(self.installations) > 32
            or not self.service_principal_id.strip()
            or len(self.service_principal_id) > 128
        ):
            raise ValueError("Enabled channel host needs installed transports and audit actor")
        for installation, secrets in self.installations.items():
            if (
                not isinstance(installation, str)
                or _IDENTIFIER.fullmatch(installation) is None
                or not isinstance(secrets, frozenset)
                or not 1 <= len(secrets) <= 8
                or any(
                    not isinstance(kind, str)
                    or _SECRET_TYPE.fullmatch(kind) is None
                    for kind in secrets
                )
            ):
                raise ValueError("Invalid channel installation credential contract")
        return self


def _env_boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate channel installation declaration")
        result[key] = value
    return result


def load_channel_host_settings() -> ChannelHostSettings:
    """Resolve operator config at process startup; invalid opt-in fails closed."""
    enabled = _env_boolean("KAREN_CHANNEL_HOST_ENABLED")
    if not enabled:
        return ChannelHostSettings().validate()
    try:
        raw = json.loads(
            os.getenv("KAREN_CHANNEL_HOST_INSTALLATIONS_JSON", "{}"),
            object_pairs_hook=_unique_json_object,
        )
        if not isinstance(raw, dict):
            raise ValueError("Expected installation-to-secret-type mapping")
        declared: dict[str, frozenset[str]] = {}
        for name, values in raw.items():
            if (
                not isinstance(values, list)
                or len(values) != len(set(values))
            ):
                raise ValueError("Channel secret types must be distinct lists")
            declared[name] = frozenset(values)
        timeout = float(os.getenv("KAREN_CHANNEL_HTTP_TIMEOUT_SECONDS", "10"))
        body_budget = int(os.getenv("KAREN_CHANNEL_MAX_BODY_BYTES", "65536"))
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid enabled channel host configuration") from exc

    return ChannelHostSettings(
        enabled=True,
        installations=declared,
        service_principal_id=os.getenv("KAREN_CHANNEL_SERVICE_PRINCIPAL_ID", ""),
        max_native_body_bytes=body_budget,
        http_timeout_seconds=timeout,
    ).validate()


__all__ = ["ChannelHostSettings", "load_channel_host_settings"]
