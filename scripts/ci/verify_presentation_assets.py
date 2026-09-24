#!/usr/bin/env python3
"""Verify KAREN presentation assets and real screenshot provenance.

This gate owns presentation integrity only. It does not infer runtime capability or
replace the canonical architecture/developer manifests.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "src" / "ui_launchers" / "Karen-AI-Theme"
BRAND_ROOT = UI_ROOT / "public" / "brand"
SCREENSHOT_ROOT = REPO_ROOT / "docs" / "assets" / "screenshots"
CAPTURE_MANIFEST = SCREENSHOT_ROOT / "capture-manifest.json"

BRAND_ASSETS = (
    BRAND_ROOT / "karen-mark.svg",
    BRAND_ROOT / "karen-wordmark.svg",
    BRAND_ROOT / "karen-banner.svg",
)

GALLERY_FILES = (
    "01-chat-runtime.png",
    "02-agents-overview.png",
    "03-plugin-ecosystem.png",
    "04-comms-center.png",
    "05-settings-and-models.png",
)

REQUIRED_PRESENTATION_FILES = (
    REPO_ROOT / "docs" / "presentation" / "BRAND_SYSTEM.md",
    REPO_ROOT / "docs" / "presentation" / "PRODUCT_PRESENTATION_MANIFEST.md",
    SCREENSHOT_ROOT / "README.md",
    UI_ROOT / "e2e" / "playwright.showcase.config.ts",
    UI_ROOT / "e2e" / "showcase" / "capture-product.showcase.ts",
    UI_ROOT / "src" / "app" / "dashboard" / "page.tsx",
    UI_ROOT / "src" / "app" / "manifest.ts",
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PresentationContractError(RuntimeError):
    """Raised when presentation truth is incomplete or unsafe."""


def require_file(path: Path) -> None:
    if not path.is_file():
        raise PresentationContractError(
            f"missing required presentation file: {path.relative_to(REPO_ROOT)}"
        )


def read_text(path: Path) -> str:
    require_file(path)
    return path.read_text(encoding="utf-8")


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != PNG_SIGNATURE:
        raise PresentationContractError(
            f"not a valid PNG: {path.relative_to(REPO_ROOT)}"
        )
    return struct.unpack(">II", data[16:24])


def assert_known_revision_is_ancestor(label: str, revision: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PresentationContractError(
            f"{label} {revision} is not an ancestor of current HEAD; the gallery cannot be attributed to this repository line"
        )


def verify_brand_contract() -> None:
    for path in BRAND_ASSETS + REQUIRED_PRESENTATION_FILES:
        require_file(path)

    readme = read_text(REPO_ROOT / "README.md")
    if "src/ui_launchers/Karen-AI-Theme/public/brand/karen-banner.svg" not in readme:
        raise PresentationContractError("README must use the canonical KAREN banner")
    if "docs/presentation/BRAND_SYSTEM.md" not in readme:
        raise PresentationContractError("README must link the canonical brand system")
    if "docs/presentation/PRODUCT_PRESENTATION_MANIFEST.md" not in readme:
        raise PresentationContractError("README must link the presentation manifest")

    layout = read_text(UI_ROOT / "src" / "app" / "layout.tsx")
    manifest = read_text(UI_ROOT / "src" / "app" / "manifest.ts")
    dashboard = read_text(UI_ROOT / "src" / "app" / "dashboard" / "page.tsx")

    if "/brand/karen-mark.svg" not in layout or "/brand/karen-banner.svg" not in layout:
        raise PresentationContractError(
            "web metadata must use canonical KAREN mark and banner"
        )
    if "/brand/karen-mark.svg" not in manifest:
        raise PresentationContractError("install manifest must use canonical KAREN mark")
    if dashboard.count('/brand/karen-mark.svg') < 2:
        raise PresentationContractError(
            "authenticated shell must use the canonical KAREN mark in header and footer"
        )
    if "Karen AI" in dashboard:
        raise PresentationContractError(
            "authenticated shell still contains the retired split-brand 'Karen AI' label"
        )
    if '"Initializing KAREN"' not in dashboard:
        raise PresentationContractError(
            "authenticated startup state must use canonical KAREN naming"
        )

    capture_spec = read_text(
        UI_ROOT / "e2e" / "showcase" / "capture-product.showcase.ts"
    )
    forbidden_capture_primitives = (
        "page.route(",
        "context.route(",
        "route.fulfill(",
        "page.setContent(",
    )
    for primitive in forbidden_capture_primitives:
        if primitive in capture_spec:
            raise PresentationContractError(
                f"showcase capture may not synthesize product state via {primitive}"
            )

    required_capture_guards = (
        'KAREN_SHOWCASE_ALLOW_CAPTURE !== "true"',
        'KAREN_SHOWCASE_ACCOUNT_KIND !== "sanitized-demo"',
        "KAREN_SHOWCASE_TARGET_REVISION",
        'page.getByRole("heading", { name: "KAREN", exact: true })',
        'header img[src*="karen-mark.svg"]',
        'source: "real-running-application"',
        'capture_harness_git_sha: currentGitSha()',
        'target_revision: targetRevision',
        'target_revision_attestation: "operator-supplied"',
        'mocked_responses: false',
        'generated_ui: false',
        'fixture_only_state: false',
    )
    for guard in required_capture_guards:
        if guard not in capture_spec:
            raise PresentationContractError(
                f"showcase capture is missing guard/provenance marker: {guard}"
            )


def verify_gallery(require_assets: bool) -> bool:
    gallery_paths = [SCREENSHOT_ROOT / filename for filename in GALLERY_FILES]
    present = [path for path in gallery_paths if path.is_file()]
    manifest_present = CAPTURE_MANIFEST.is_file()

    if not present and not manifest_present:
        if require_assets:
            raise PresentationContractError(
                "curated real-product gallery is missing; capture it from an approved sanitized running KAREN installation"
            )
        return False

    if len(present) != len(gallery_paths):
        missing = [path.name for path in gallery_paths if not path.is_file()]
        raise PresentationContractError(
            "partial screenshot galleries are prohibited; missing: " + ", ".join(missing)
        )

    require_file(CAPTURE_MANIFEST)
    payload = json.loads(CAPTURE_MANIFEST.read_text(encoding="utf-8"))

    if payload.get("source") != "real-running-application":
        raise PresentationContractError(
            "capture provenance must identify a real running application"
        )
    if payload.get("authenticated") is not True:
        raise PresentationContractError(
            "curated screenshots must come from an authenticated product session"
        )
    if payload.get("account_kind") != "sanitized-demo":
        raise PresentationContractError(
            "curated screenshots must use an approved sanitized demo account"
        )

    policy = payload.get("policy")
    expected_policy = {
        "mocked_responses": False,
        "generated_ui": False,
        "fixture_only_state": False,
        "production_or_personal_data": False,
    }
    if policy != expected_policy:
        raise PresentationContractError(f"invalid capture policy provenance: {policy!r}")

    harness_sha = str(payload.get("capture_harness_git_sha", "")).lower()
    if not SHA_RE.fullmatch(harness_sha):
        raise PresentationContractError(
            f"invalid capture_harness_git_sha: {harness_sha!r}"
        )
    assert_known_revision_is_ancestor("capture harness revision", harness_sha)

    target_revision = str(payload.get("target_revision", "")).lower()
    if not SHA_RE.fullmatch(target_revision):
        raise PresentationContractError(
            f"invalid target_revision: {target_revision!r}"
        )
    if payload.get("target_revision_attestation") != "operator-supplied":
        raise PresentationContractError(
            "target revision must be explicitly recorded as operator-supplied until KAREN exposes a canonical deployment revision attestation"
        )
    assert_known_revision_is_ancestor("target application revision", target_revision)

    files = payload.get("files")
    if files != list(GALLERY_FILES):
        raise PresentationContractError(
            f"capture manifest file set does not match canonical gallery: {files!r}"
        )

    viewport = payload.get("viewport")
    if viewport != {"width": 1600, "height": 1000}:
        raise PresentationContractError(f"unexpected capture viewport: {viewport!r}")

    for path in gallery_paths:
        width, height = png_dimensions(path)
        if width < 1400 or height < 800:
            raise PresentationContractError(
                f"{path.name} is below premium capture resolution: {width}x{height}"
            )
        if path.stat().st_size < 10_000:
            raise PresentationContractError(
                f"{path.name} is suspiciously small ({path.stat().st_size} bytes); verify it is a real rendered product view"
            )

    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-assets",
        action="store_true",
        help="fail when the curated real-product screenshot set has not been captured yet",
    )
    args = parser.parse_args()

    try:
        verify_brand_contract()
        gallery_ready = verify_gallery(require_assets=args.require_assets)
    except (PresentationContractError, json.JSONDecodeError) as exc:
        print(f"presentation contract failed: {exc}", file=sys.stderr)
        return 1

    if gallery_ready:
        print("presentation contract green: canonical brand + provenanced real-product gallery")
    else:
        print(
            "presentation contract green: brand/capture rail valid; curated real-product gallery still pending"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
