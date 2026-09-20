"""Canonical public HTTP origin resolution for proxy-aware security decisions.

The application server normally receives internal HTTP from the trusted web
proxy, so ASGI ``request.url.scheme`` is not necessarily the browser-visible
scheme. This module is the only backend authority allowed to consume
``X-Forwarded-Proto``. It accepts that value only from the canonical trusted
proxy boundary owned by ``client_identity``.
"""

from __future__ import annotations

from typing import Any, Optional

from ai_karen_engine.server.client_identity import is_trusted_proxy_request

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _normalize_scheme(value: Any) -> Optional[str]:
    candidate = str(value or "").strip().lower()
    if candidate not in _ALLOWED_SCHEMES:
        return None
    return candidate


def resolve_public_scheme(request: Any) -> str:
    """Resolve the browser-visible HTTP scheme without trusting direct headers.

    Direct requests use their ASGI URL scheme. Requests from a configured trusted
    proxy may use exactly one normalized ``X-Forwarded-Proto`` value. Missing or
    malformed forwarded scheme from a trusted proxy resolves to an empty value so
    security callers can fail closed rather than silently treating it as HTTP.
    """

    url = getattr(request, "url", None)
    direct_scheme = _normalize_scheme(getattr(url, "scheme", "")) or ""
    if not is_trusted_proxy_request(request):
        return direct_scheme

    headers = getattr(request, "headers", {})
    return _normalize_scheme(headers.get("x-forwarded-proto")) or ""


def should_use_secure_cookie(request: Any) -> bool:
    """Fail closed for cookies unless the canonical public scheme is plain HTTP."""

    return resolve_public_scheme(request) != "http"
