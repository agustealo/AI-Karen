"""Direct HTTPS transfer for revision-pinned Hugging Face model assets.

Transport only. The canonical model-download control service owns policy,
license consent, worker leasing, artifact promotion and tenant authorization.
No huggingface_hub Python client is used for file transfer or tree discovery.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_HF_ORIGIN = "https://huggingface.co"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_MODEL = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ALLOWED_CDN_SUFFIXES = (
    ".hf.co",
    ".huggingface.co",
    ".xethub.hf.co",
    ".cloudfront.net",
    ".s3.amazonaws.com",
)
_MAX_TREE_BYTES = 4 * 1024 * 1024
_MAX_TREE_ITEMS = 999
_MAX_TREE_PAGES = 40
_MAX_FILES = 128
_MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024


class DirectHttpsDownloadError(RuntimeError):
    """Safe, redacted direct-transfer failure without token-bearing URLs."""


def _safe_path(value: str) -> str:
    if (
        not value
        or len(value) > 512
        or "\\" in value
        or value.startswith("/")
        or "//" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise DirectHttpsDownloadError("Unsafe remote model artifact path")
    return value


def _approved_url(value: str, *, initial: bool) -> bool:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
        return False
    host = (parsed.hostname or "").lower()
    if initial:
        return host == "huggingface.co"
    return host == "huggingface.co" or any(host.endswith(suffix) for suffix in _ALLOWED_CDN_SUFFIXES)


class _PrivateRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Discard bearer auth on cross-host redirects and forbid other protocols."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str):
        if not _approved_url(newurl, initial=False):
            raise DirectHttpsDownloadError("Unapproved model artifact redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            raise DirectHttpsDownloadError("Model artifact redirect refused")
        cross_host = (
            urllib.parse.urlsplit(req.full_url).hostname
            != urllib.parse.urlsplit(newurl).hostname
        )
        # urllib normalizes proxy headers to "Proxy-authorization", but
        # Request.remove_header() uses exact-case dictionary keys. A bypassed
        # proxy (NO_PROXY) must never expose these credentials to a CDN.
        sensitive = {"proxy-authorization"}
        if cross_host:
            sensitive.update({"authorization", "cookie"})
        for headers_by_name in (redirected.headers, redirected.unredirected_hdrs):
            for name in tuple(headers_by_name):
                if name.casefold() in sensitive:
                    del headers_by_name[name]
        return redirected


def _open(url: str, token: str | None, *, initial: bool):
    if not _approved_url(url, initial=initial):
        raise DirectHttpsDownloadError("Model artifact source is not approved")
    headers = {"User-Agent": "KarenModelDownload/1", "Accept": "application/octet-stream, application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_PrivateRedirectHandler())
    try:
        return opener.open(req, timeout=90)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise DirectHttpsDownloadError("Upstream model access denied; check account and license terms") from None
        if exc.code == 404:
            raise DirectHttpsDownloadError("Pinned model artifact or revision not found") from None
        raise DirectHttpsDownloadError(f"Model transfer HTTP status {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DirectHttpsDownloadError("Model transfer network unavailable") from None


def _prefix(pattern: str) -> str:
    _safe_path(pattern)
    marker = min((pattern.find(symbol) for symbol in "*?[" if symbol in pattern), default=-1)
    before_wildcard = pattern if marker == -1 else pattern[:marker]
    return before_wildcard.rpartition("/")[0]


def _next_tree_url(link_header: str, *, current_url: str) -> str | None:
    """Follow only the exact repository/revision tree with the same filters."""
    if not link_header:
        return None
    matches = re.findall(
        r'<([^<>]+)>\s*;\s*rel\s*=\s*"?next"?',
        link_header, flags=re.IGNORECASE,
    )
    if not matches:
        if re.search(r"\bnext\b", link_header, flags=re.IGNORECASE):
            raise DirectHttpsDownloadError("Invalid model source pagination header")
        return None
    if len(matches) != 1:
        raise DirectHttpsDownloadError("Ambiguous model source pagination header")
    next_url = matches[0]
    if len(next_url) > 4096 or not _approved_url(next_url, initial=True):
        raise DirectHttpsDownloadError("Model source pagination left trusted host")
    current = urllib.parse.urlsplit(current_url)
    following = urllib.parse.urlsplit(next_url)
    if following.path != current.path or following.fragment:
        raise DirectHttpsDownloadError("Model source pagination changed reviewed tree")
    query = urllib.parse.parse_qs(following.query, keep_blank_values=True)
    if (
        set(query) != {"recursive", "expand", "cursor"}
        or query["recursive"] != ["true"]
        or query["expand"] != ["true"]
        or len(query["cursor"]) != 1
        or not query["cursor"][0]
    ):
        raise DirectHttpsDownloadError("Model source pagination parameters invalid")
    return next_url


def _discover(
    model_id: str, revision: str, patterns: list[str], excludes: list[str], token: str | None,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    seen_pages: set[str] = set()
    bytes_seen = 0
    items_seen = 0
    pages_seen = 0
    for prefix in sorted({_prefix(pattern) for pattern in patterns}):
        encoded = urllib.parse.quote(prefix, safe="/")
        url: str | None = (
            f"{_HF_ORIGIN}/api/models/{model_id}/tree/{revision}"
            + (f"/{encoded}" if encoded else "")
            + "?recursive=true&expand=true"
        )
        while url is not None:
            if url in seen_pages or pages_seen >= _MAX_TREE_PAGES:
                raise DirectHttpsDownloadError("Model source pagination loop or limit")
            seen_pages.add(url)
            pages_seen += 1
            with _open(url, token, initial=True) as response:
                remaining = _MAX_TREE_BYTES - bytes_seen
                if remaining <= 0:
                    raise DirectHttpsDownloadError("Model tree exceeds bounded manifest limit")
                raw = response.read(remaining + 1)
                link = str(response.headers.get("Link") or "")
            bytes_seen += len(raw)
            if bytes_seen > _MAX_TREE_BYTES:
                raise DirectHttpsDownloadError("Model tree exceeds bounded manifest limit")
            try:
                tree = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise DirectHttpsDownloadError("Model source returned invalid artifact manifest") from None
            if not isinstance(tree, list):
                raise DirectHttpsDownloadError("Model manifest is incomplete or invalid")
            items_seen += len(tree)
            if items_seen > _MAX_TREE_ITEMS:
                raise DirectHttpsDownloadError("Model manifest is incomplete or exceeds limit")
            for item in tree:
                if not isinstance(item, dict) or item.get("type") != "file":
                    continue
                path = _safe_path(str(item.get("path") or ""))
                if not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
                    continue
                if any(fnmatch.fnmatchcase(path, pattern) for pattern in excludes):
                    continue
                size = item.get("size")
                if type(size) is not int or size <= 0 or size > _MAX_FILE_BYTES:
                    raise DirectHttpsDownloadError("Model artifact size is missing or exceeds limit")
                lfs = item.get("lfs")
                oid = lfs.get("oid") if isinstance(lfs, dict) else None
                if oid is not None and (
                    not isinstance(oid, str) or re.fullmatch(r"[0-9a-f]{64}", oid) is None
                ):
                    raise DirectHttpsDownloadError("Model artifact digest is invalid")
                artifact = {"path": path, "size": size, "sha256": oid}
                if path in candidates and candidates[path] != artifact:
                    raise DirectHttpsDownloadError("Conflicting pinned model file metadata")
                candidates[path] = artifact
                if len(candidates) > _MAX_FILES:
                    raise DirectHttpsDownloadError("Model artifact selection exceeds limit")
            url = _next_tree_url(link, current_url=url)
    found = sorted(candidates.values(), key=lambda item: item["path"])
    if not found:
        raise DirectHttpsDownloadError("Model artifact selection empty")
    for pattern in patterns:
        if not any(fnmatch.fnmatchcase(item["path"], pattern) for item in found):
            raise DirectHttpsDownloadError("Required model artifact pattern was not satisfied")
    if sum(item["size"] for item in found) > _MAX_TOTAL_BYTES:
        raise DirectHttpsDownloadError("Model artifact total size exceeds limit")
    return found


def download_direct_https(
    *, model_id: str, revision: str, directory: Path,
    include_patterns: list[str] | None, exclude_patterns: list[str] | None,
    token: str | None,
) -> None:
    """Transfer verified pinned files into the worker's private staging tree.

    The orchestrator performs its existing symlink, file and registry validation;
    publication can occur only after the worker's lease-fenced transaction.
    """
    if not _MODEL.fullmatch(model_id) or not _SHA.fullmatch(revision):
        raise DirectHttpsDownloadError("Direct HTTPS requires an exact model and immutable SHA")
    if not include_patterns:
        raise DirectHttpsDownloadError("Direct HTTPS requires curated file patterns")
    patterns = [_safe_path(str(pattern)) for pattern in include_patterns]
    excludes = [_safe_path(str(pattern)) for pattern in (exclude_patterns or [])]
    files = _discover(model_id, revision, patterns, excludes, token)
    directory.mkdir(parents=True, exist_ok=True)
    for artifact in files:
        rel = artifact["path"]
        destination = directory / rel
        if destination.is_symlink() or not destination.resolve().is_relative_to(directory.resolve()):
            raise DirectHttpsDownloadError("Artifact destination escapes staging")
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = f"{_HF_ORIGIN}/{model_id}/resolve/{revision}/{urllib.parse.quote(rel, safe='/')}"
        digest = hashlib.sha256()
        written = 0
        temporary = destination.with_name(destination.name + ".partial")
        try:
            with _open(url, token, initial=True) as response, temporary.open("xb") as output:
                if str(response.headers.get("Content-Type", "")).lower().startswith("text/html"):
                    raise DirectHttpsDownloadError("Model source returned HTML instead of a model file")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > artifact["size"]:
                        raise DirectHttpsDownloadError("Model artifact exceeded its published size")
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            if written != artifact["size"]:
                raise DirectHttpsDownloadError("Model artifact size mismatch")
            if artifact["sha256"] and digest.hexdigest() != artifact["sha256"]:
                raise DirectHttpsDownloadError("Model artifact checksum mismatch")
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


__all__ = ["DirectHttpsDownloadError", "download_direct_https"]
