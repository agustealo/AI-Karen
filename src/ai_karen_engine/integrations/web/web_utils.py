"""
URL canonicalization and content-type policy for web intelligence.

This module owns stable URL normalization and content-type gating so that
crawl/search logic does not embed ad-hoc URL handling.
"""

from __future__ import annotations

import re
from typing import Optional, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


_DEFAULT_PORTS = {
    "http": "80",
    "https": "443",
}


def canonicalize_url(url: str) -> str:
    """
    Produce a canonical URL for deduplication and citation.

    Normalizes:
    - scheme/host casing
    - default ports
    - fragments
    - tracking parameters (common ones)
    - trailing slashes on paths without extension

    Preserves original URL for citations.
    """
    if not url or not isinstance(url, str):
        return url or ""

    parsed = urlparse(url.strip())

    scheme = (parsed.scheme or "https").lower()
    hostname = (parsed.hostname or "").lower()

    port = parsed.port
    if port is None and scheme in _DEFAULT_PORTS:
        netloc = hostname
    elif port is None:
        netloc = parsed.netloc
    else:
        netloc = f"{hostname}:{port}"

    if parsed.username or parsed.password:
        auth = ""
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth += f":{parsed.password}"
            netloc = f"{auth}@{netloc}"

    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"

    if "." not in path.split("/")[-1]:
        path = path.rstrip("/") or "/"

    params = parsed.params

    query_parts = _normalize_query_params(parsed.query)

    fragment = ""

    return urlunparse((scheme, netloc, path, params, query_parts, fragment))


def _normalize_query_params(query: str) -> str:
    if not query:
        return ""

    tracking_params: Set[str] = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "msclkid",
        "_ga",
        "_gid",
        "ref",
        "source",
        "campaign",
    }

    parts = []
    seen: Set[str] = set()
    for key, value in parse_qsl(query, keep_blank_values=True):
        normalized_key = key.lower()
        if normalized_key in tracking_params:
            continue
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        parts.append((key, value))

    return urlencode(parts, doseq=True)


_ALLOWED_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
    "text/css",
    "text/javascript",
    "application/javascript",
    "text/markdown",
}

_BINARY_CONTENT_TYPES = {
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/vnd.rar",
    "application/x-iso9660-image",
    "application/x-msdos-program",
    "application/x-msi",
    "application/x-msdownload",
    "application/x-elf",
    "application/x-sharedlib",
    "application/x-object",
    "video/mp4",
    "video/webm",
    "video/ogg",
    "audio/mpeg",
    "audio/ogg",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "application/font-woff",
    "application/font-woff2",
    "application/vnd.ms-fontobject",
}


def is_content_type_allowed(content_type: Optional[str]) -> bool:
    if not content_type:
        return True
    normalized = content_type.lower().split(";")[0].strip()
    return normalized in _ALLOWED_CONTENT_TYPES


def is_content_type_binary(content_type: Optional[str]) -> bool:
    if not content_type:
        return False
    normalized = content_type.lower().split(";")[0].strip()
    return normalized in _BINARY_CONTENT_TYPES
