"""Canonical HTTP client identity resolution.

This module owns socket-peer normalization and trusted-proxy handling for HTTP
transport identity. Callers such as authentication, auditing, rate limiting, and
other transport context resolvers consume this trust boundary; they must not
parse forwarding identity headers independently.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from collections.abc import Iterable
from typing import Any, Optional

logger = logging.getLogger(__name__)

TRUSTED_PROXY_ENV = "HTTP_TRUSTED_PROXY_HOSTS"
_PROXY_ADDRESS_CACHE_TTL_SECONDS = 30.0
_trusted_proxy_hosts: tuple[str, ...] = ()
_proxy_address_cache: dict[str, tuple[float, frozenset[str]]] = {}


def _csv_values(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def configure_client_identity(
    trusted_proxy_hosts: Optional[Iterable[str]] = None,
) -> None:
    """Configure the canonical trusted-proxy boundary.

    When no explicit hosts are supplied, configuration is read from
    ``HTTP_TRUSTED_PROXY_HOSTS``. Configuration is independent of rate limiting
    so auth/audit identity remains correct even when throttling is disabled.
    """

    global _trusted_proxy_hosts

    if trusted_proxy_hosts is None:
        configured = _csv_values(os.getenv(TRUSTED_PROXY_ENV, ""))
    else:
        configured = [
            str(item).strip() for item in trusted_proxy_hosts if str(item).strip()
        ]

    # Preserve declaration order while removing duplicates.
    _trusted_proxy_hosts = tuple(dict.fromkeys(configured))
    _proxy_address_cache.clear()
    logger.info(
        "HTTP client identity configured with %d trusted proxy host(s)",
        len(_trusted_proxy_hosts),
    )


def _normalize_ip(value: Any) -> Optional[str]:
    """Normalize one IP literal without accepting hostnames or header chains."""

    candidate = str(value or "").strip().strip("[]")
    if not candidate or "," in candidate:
        return None
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return str(address.ipv4_mapped)
    return address.compressed


def _resolve_proxy_host(host: str) -> frozenset[str]:
    """Resolve a configured proxy hostname with a short cache for container churn."""

    literal = _normalize_ip(host)
    if literal:
        return frozenset({literal})

    now = time.monotonic()
    cached = _proxy_address_cache.get(host)
    if cached and now - cached[0] < _PROXY_ADDRESS_CACHE_TTL_SECONDS:
        return cached[1]

    resolved: set[str] = set()
    try:
        for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
            normalized = _normalize_ip(info[4][0])
            if normalized:
                resolved.add(normalized)
    except OSError:
        logger.warning("Unable to resolve configured HTTP proxy host %s", host)

    result = frozenset(resolved)
    _proxy_address_cache[host] = (now, result)
    return result


def _peer_is_trusted_proxy(peer_ip: str) -> bool:
    normalized_peer = _normalize_ip(peer_ip)
    if not normalized_peer:
        return False
    return any(
        normalized_peer in _resolve_proxy_host(host) for host in _trusted_proxy_hosts
    )


def _request_peer_ip(request: Any) -> str:
    raw_peer = request.client.host if getattr(request, "client", None) else ""
    return _normalize_ip(raw_peer) or ""


def is_trusted_proxy_request(request: Any) -> bool:
    """Return whether the request socket peer is inside the configured trust boundary."""

    return _peer_is_trusted_proxy(_request_peer_ip(request))


def resolve_client_ip(request: Any) -> str:
    """Resolve canonical client IP from socket peer plus explicit proxy trust.

    Direct clients cannot override their socket identity with forwarding headers.
    A trusted proxy may supply exactly one valid ``X-Forwarded-For`` address.
    Missing, malformed, or chained forwarded values fail to an unavailable
    identity rather than collapsing traffic onto the shared proxy address.
    """

    peer_ip = _request_peer_ip(request)
    if not _peer_is_trusted_proxy(peer_ip):
        return peer_ip

    headers = getattr(request, "headers", {})
    return _normalize_ip(headers.get("x-forwarded-for")) or ""
