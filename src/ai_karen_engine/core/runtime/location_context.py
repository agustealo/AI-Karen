"""Governed location context selection for direct capabilities.

Request-provided location hints require an explicit recognized provenance.
Tenant-scoped runtime evidence is trusted only after upstream authorization.
This module never geolocates, accesses the network, or persists preferences.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


TRUSTED_REQUEST_SOURCES = frozenset({
    "user_selected",
})


@dataclass(frozen=True)
class ResolvedLocation:
    value: str
    source: str


def _bounded(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 1 <= len(value) <= 120 else None


def resolve_location(
    request_metadata: Mapping[str, Any] | None,
    authorized_context: Mapping[str, Any] | None,
    *,
    kind: str,
) -> ResolvedLocation | None:
    """Select an explicitly sourced request hint, then authorized evidence.

    Explicitly mentioned places in the query remain the caller's responsibility.
    No generic metadata location may override governed runtime evidence.
    """
    metadata = request_metadata or {}
    authorized = authorized_context or {}
    if kind == "weather":
        provenance = metadata.get("location_source")
        if provenance in TRUSTED_REQUEST_SOURCES:
            for key in ("weather_location", "location", "city"):
                value = _bounded(metadata.get(key))
                if value:
                    return ResolvedLocation(value, str(provenance))
        # Authorized memory/profile evidence wins over system defaults.
        # The caller must enforce tenant, identity, consent, and RBAC before
        # populating this context. Raw client metadata cannot assert this tier.
        value = _bounded(authorized.get("weather_location"))
        if value:
            return ResolvedLocation(value, "authorized_runtime")

        if (authorized.get("device_location_permitted") is True
                and metadata.get("location_source") == "device_with_consent"):
            value = _bounded(metadata.get("weather_location") or metadata.get("location"))
            if value:
                return ResolvedLocation(value, "device_with_consent")

        # System location is a *separate*, explicitly permitted context tier.
        # No guessed timezone-to-city conversion or implicit geolocation.
        if authorized.get("system_location_permitted") is True:
            value = _bounded(authorized.get("system_location"))
            if value:
                return ResolvedLocation(value, "system_with_permission")
        return None
    if kind == "time":
        for key in ("timezone", "user_timezone", "local_timezone"):
            value = _bounded(metadata.get(key))
            if value and metadata.get("timezone_source") in TRUSTED_REQUEST_SOURCES:
                return ResolvedLocation(value, str(metadata["timezone_source"]))
        value = _bounded(authorized.get("timezone"))
        if value:
            return ResolvedLocation(value, "authorized_runtime")
        if (authorized.get("device_timezone_permitted") is True
                and metadata.get("timezone_source") == "device_with_consent"):
            value = _bounded(metadata.get("timezone"))
            if value:
                return ResolvedLocation(value, "device_with_consent")
        if authorized.get("system_timezone_permitted") is True:
            value = _bounded(authorized.get("system_timezone"))
            if value:
                return ResolvedLocation(value, "system_with_permission")
        return None
    raise ValueError("Unsupported location context kind")
