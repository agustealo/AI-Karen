#!/usr/bin/env python3
"""Validate provenanced real-product KAREN screenshot galleries.

This module owns gallery provenance only. Brand/system presentation checks remain
with the higher-level presentation contract.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(
    os.environ.get(
        "KAREN_PRESENTATION_REPO_ROOT",
        str(Path(__file__).resolve().parents[2]),
    )
).resolve()
SCREENSHOT_ROOT = REPO_ROOT / "docs" / "assets" / "screenshots"
CAPTURE_MANIFEST = SCREENSHOT_ROOT / "capture-manifest.json"
GALLERY_FILES = (
    "01-chat-runtime.png",
    "02-agents-overview.png",
    "03-plugin-ecosystem.png",
    "04-comms-center.png",
    "05-settings-and-models.png",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_POLICY = {
    "mocked_responses": False,
    "generated_ui": False,
    "fixture_only_state": False,
    "production_or_personal_data": False,
    "presentation_ready_state_required": True,
    "retired_visible_brand_forbidden": True,
}


class GalleryContractError(RuntimeError):
    """Raised when screenshot provenance is incomplete or unsafe."""


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _require_known_commit(label: str, revision: str) -> None:
    if _git("cat-file", "-e", f"{revision}^{{commit}}").returncode != 0:
        raise GalleryContractError(f"{label} {revision} is not a known repository commit")


def _require_ancestor(label: str, ancestor: str, descendant: str) -> None:
    if _git("merge-base", "--is-ancestor", ancestor, descendant).returncode != 0:
        raise GalleryContractError(
            f"{label}: {ancestor} is not an ancestor of {descendant}"
        )


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != PNG_SIGNATURE:
        raise GalleryContractError(f"not a valid PNG: {path.relative_to(REPO_ROOT)}")
    return struct.unpack(">II", data[16:24])


def _read_manifest() -> dict[str, Any]:
    try:
        payload = json.loads(CAPTURE_MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GalleryContractError("capture-manifest.json is missing") from exc
    except json.JSONDecodeError as exc:
        raise GalleryContractError("capture-manifest.json is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise GalleryContractError("capture-manifest.json must contain a JSON object")
    return payload


def verify_gallery(
    *,
    require_assets: bool,
    expected_harness_sha: str | None = None,
    require_target_descendant_of_harness: bool = False,
) -> bool:
    gallery_paths = [SCREENSHOT_ROOT / filename for filename in GALLERY_FILES]
    present = [path for path in gallery_paths if path.is_file()]
    manifest_present = CAPTURE_MANIFEST.is_file()

    if not present and not manifest_present:
        if require_assets:
            raise GalleryContractError(
                "curated real-product gallery is missing; capture it from an approved sanitized running KAREN installation"
            )
        return False

    if len(present) != len(gallery_paths):
        missing = [path.name for path in gallery_paths if not path.is_file()]
        raise GalleryContractError(
            "partial screenshot galleries are prohibited; missing: " + ", ".join(missing)
        )

    payload = _read_manifest()
    if payload.get("schema_version") != 1:
        raise GalleryContractError(
            f"unsupported capture schema_version: {payload.get('schema_version')!r}"
        )
    if payload.get("source") != "real-running-application":
        raise GalleryContractError("capture source must be a real running application")
    if payload.get("authenticated") is not True:
        raise GalleryContractError("curated screenshots must come from an authenticated session")
    if payload.get("account_kind") != "sanitized-demo":
        raise GalleryContractError("curated screenshots must use a sanitized demo account")
    if payload.get("policy") != EXPECTED_POLICY:
        raise GalleryContractError(f"invalid capture policy provenance: {payload.get('policy')!r}")
    if payload.get("files") != list(GALLERY_FILES):
        raise GalleryContractError(
            f"capture manifest file set does not match canonical gallery: {payload.get('files')!r}"
        )
    if payload.get("viewport") != {"width": 1600, "height": 1000}:
        raise GalleryContractError(f"unexpected capture viewport: {payload.get('viewport')!r}")
    browser = payload.get("browser")
    if not isinstance(browser, str) or not browser.strip():
        raise GalleryContractError("capture browser provenance is missing")
    captured_at = payload.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise GalleryContractError("capture timestamp provenance is missing")

    harness_sha = str(payload.get("capture_harness_git_sha", "")).lower()
    if not SHA_RE.fullmatch(harness_sha):
        raise GalleryContractError(f"invalid capture_harness_git_sha: {harness_sha!r}")
    _require_known_commit("capture harness revision", harness_sha)
    if expected_harness_sha:
        expected = expected_harness_sha.lower()
        if not SHA_RE.fullmatch(expected):
            raise GalleryContractError(f"invalid expected harness SHA: {expected!r}")
        if harness_sha != expected:
            raise GalleryContractError(
                f"capture harness SHA mismatch: manifest={harness_sha} expected={expected}"
            )

    target_revision = str(payload.get("target_revision", "")).lower()
    if not SHA_RE.fullmatch(target_revision):
        raise GalleryContractError(f"invalid target_revision: {target_revision!r}")
    if payload.get("target_revision_attestation") != "operator-supplied":
        raise GalleryContractError(
            "target revision must be explicitly recorded as operator-supplied"
        )
    _require_known_commit("target application revision", target_revision)
    if require_target_descendant_of_harness:
        _require_ancestor(
            "target application must include the trusted capture baseline",
            harness_sha,
            target_revision,
        )

    for path in gallery_paths:
        width, height = _png_dimensions(path)
        if width < 1400 or height < 800:
            raise GalleryContractError(
                f"{path.name} is below premium capture resolution: {width}x{height}"
            )
        if path.stat().st_size < 10_000:
            raise GalleryContractError(
                f"{path.name} is suspiciously small ({path.stat().st_size} bytes)"
            )

    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-assets", action="store_true")
    parser.add_argument("--expected-harness-sha")
    parser.add_argument("--require-target-descendant-of-harness", action="store_true")
    args = parser.parse_args()

    try:
        ready = verify_gallery(
            require_assets=args.require_assets,
            expected_harness_sha=args.expected_harness_sha,
            require_target_descendant_of_harness=args.require_target_descendant_of_harness,
        )
    except GalleryContractError as exc:
        print(f"presentation gallery contract failed: {exc}", file=sys.stderr)
        return 1

    if ready:
        print("presentation gallery contract green: provenanced real-product gallery")
    else:
        print("presentation gallery contract green: gallery not yet required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
