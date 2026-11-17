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
        if urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(newurl).hostname:
            for key in ("Authorization", "Cookie", "Proxy-Authorization"):
                redirected.remove_header(key)
                redirected.unredirected_hdrs.pop(key, None)
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


def _discover(
    model_id: str, revision: str, patterns: list[str], excludes: list[str], token: str | None,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for prefix in sorted({_prefix(pattern) for pattern in patterns}):
        encoded = urllib.parse.quote(prefix, safe="/")
        url = (
            f"{_HF_ORIGIN}/api/models/{model_id}/tree/{revision}"
            + (f"/{encoded}" if encoded else "")
            + "?recursive=true&expand=true"
        )
        with _open(url, token, initial=True) as response:
            raw = response.read(_MAX_TREE_BYTES + 1)
            if len(raw) > _MAX_TREE_BYTES:
                raise DirectHttpsDownloadError("Model tree exceeds bounded manifest limit")
        try:
            tree = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise DirectHttpsDownloadError("Model source returned invalid artifact manifest") from None
        if not isinstance(tree, list) or len(tree) > _MAX_TREE_ITEMS:
            raise DirectHttpsDownloadError("Model manifest is incomplete or invalid")
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
            candidates[path] = {"path": path, "size": size, "sha256": oid}
    found = sorted(candidates.values(), key=lambda item: item["path"])
    if not found or len(found) > _MAX_FILES:
        raise DirectHttpsDownloadError("Model artifact selection empty or exceeds limit")
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
