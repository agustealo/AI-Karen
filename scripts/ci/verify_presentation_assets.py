#!/usr/bin/env python3
"""Verify KAREN presentation activation and real-gallery provenance.

The presentation layer has two valid repository states:

* dormant: no premium presentation identity is active and no curated gallery exists;
* active: the complete brand/presentation contract is present and the real gallery
  satisfies the canonical provenance contract.

This prevents an incomplete presentation layer from becoming production truth while
allowing KAREN's underlying runtime to remain green until real presentation evidence
is ready. Gallery provenance itself remains owned by presentation_gallery_contract.py.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from presentation_gallery_contract import (
    CAPTURE_MANIFEST,
    GalleryContractError,
    verify_gallery as verify_gallery_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = REPO_ROOT / "src" / "ui_launchers" / "Karen-AI-Theme"
BRAND_ROOT = UI_ROOT / "public" / "brand"
SCREENSHOT_ROOT = REPO_ROOT / "docs" / "assets" / "screenshots"

BRAND_ASSETS = (
    BRAND_ROOT / "karen-mark.svg",
    BRAND_ROOT / "karen-wordmark.svg",
    BRAND_ROOT / "karen-banner.svg",
)

PRESENTATION_DOCS = (
    REPO_ROOT / "docs" / "presentation" / "BRAND_SYSTEM.md",
    REPO_ROOT / "docs" / "presentation" / "PRODUCT_PRESENTATION_MANIFEST.md",
)

PRESENTATION_SURFACES = (
    UI_ROOT / "src" / "app" / "dashboard" / "page.tsx",
    UI_ROOT / "src" / "components" / "automation" / "AgentsOverviewPage.tsx",
    UI_ROOT / "src" / "components" / "plugins" / "PluginOverviewPage.tsx",
    UI_ROOT / "src" / "components" / "comms" / "CommsCenterPage.tsx",
)

REQUIRED_PRESENTATION_FILES = (
    *PRESENTATION_DOCS,
    SCREENSHOT_ROOT / "README.md",
    REPO_ROOT / "scripts" / "ci" / "presentation_gallery_contract.py",
    UI_ROOT / "e2e" / "playwright.showcase.config.ts",
    UI_ROOT / "e2e" / "showcase" / "capture-product.showcase.ts",
    UI_ROOT / "src" / "app" / "dashboard" / "page.tsx",
    UI_ROOT / "src" / "app" / "manifest.ts",
)

README_BANNER = "src/ui_launchers/Karen-AI-Theme/public/brand/karen-banner.svg"


class PresentationContractError(RuntimeError):
    """Raised when presentation integration is incomplete or unsafe."""


def require_file(path: Path) -> None:
    if not path.is_file():
        raise PresentationContractError(
            f"missing required presentation file: {path.relative_to(REPO_ROOT)}"
        )


def read_text(path: Path) -> str:
    require_file(path)
    return path.read_text(encoding="utf-8")


def presentation_is_active() -> bool:
    """Return true only when repository presentation identity has been activated.

    Capture infrastructure on main is deliberately not an activation signal. It may
    exist while the premium presentation layer is dormant and awaiting real evidence.
    """
    if any(path.exists() for path in BRAND_ASSETS + PRESENTATION_DOCS):
        return True
    readme = REPO_ROOT / "README.md"
    return readme.is_file() and README_BANNER in readme.read_text(encoding="utf-8")


def assert_revision_is_ancestor_of_head(label: str, revision: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PresentationContractError(
            f"{label} {revision} is not an ancestor of current HEAD; "
            "the gallery cannot be attributed to this presentation line"
        )


def verify_dormant_contract() -> None:
    gallery_ready = verify_gallery_contract(
        require_assets=False,
        require_target_descendant_of_harness=True,
    )
    if gallery_ready:
        raise PresentationContractError(
            "curated gallery exists while the premium presentation layer is dormant"
        )


def verify_brand_contract() -> None:
    for path in BRAND_ASSETS + REQUIRED_PRESENTATION_FILES + PRESENTATION_SURFACES:
        require_file(path)

    readme = read_text(REPO_ROOT / "README.md")
    if README_BANNER not in readme:
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
    if '"Initializing KAREN"' not in dashboard:
        raise PresentationContractError(
            "authenticated startup state must use canonical KAREN naming"
        )

    for surface in PRESENTATION_SURFACES:
        surface_text = read_text(surface)
        if "Karen AI" in surface_text:
            raise PresentationContractError(
                "curated presentation surface still contains the retired split-brand "
                f"'Karen AI' label: {surface.relative_to(REPO_ROOT)}"
            )

    capture_spec = read_text(
        UI_ROOT / "e2e" / "showcase" / "capture-product.showcase.ts"
    )
    for primitive in (
        "page.route(",
        "context.route(",
        "route.fulfill(",
        "page.setContent(",
    ):
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
        'production_or_personal_data: false',
        'presentation_ready_state_required: true',
        'retired_visible_brand_forbidden: true',
        'data-showcase-state="ready"',
        "assertChatReady(page)",
        "assertAgentsReady(page)",
        "assertPluginOverviewReady(page)",
        "assertCommsReady(page)",
        "RETIRED_VISIBLE_BRAND",
    )
    for guard in required_capture_guards:
        if guard not in capture_spec:
            raise PresentationContractError(
                f"showcase capture is missing guard/provenance marker: {guard}"
            )


def verify_presentation_gallery(require_assets: bool) -> bool:
    gallery_ready = verify_gallery_contract(
        require_assets=require_assets,
        require_target_descendant_of_harness=True,
    )
    if not gallery_ready:
        return False

    payload = json.loads(CAPTURE_MANIFEST.read_text(encoding="utf-8"))
    assert_revision_is_ancestor_of_head(
        "capture harness revision",
        str(payload["capture_harness_git_sha"]).lower(),
    )
    assert_revision_is_ancestor_of_head(
        "target application revision",
        str(payload["target_revision"]).lower(),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-assets",
        action="store_true",
        help="require real gallery evidence whenever presentation identity is active",
    )
    args = parser.parse_args()

    try:
        if not presentation_is_active():
            verify_dormant_contract()
            print(
                "presentation contract green: premium presentation dormant; "
                "no curated gallery published"
            )
            return 0

        verify_brand_contract()
        gallery_ready = verify_presentation_gallery(require_assets=args.require_assets)
    except (PresentationContractError, GalleryContractError, json.JSONDecodeError) as exc:
        print(f"presentation contract failed: {exc}", file=sys.stderr)
        return 1

    if gallery_ready:
        print("presentation contract green: canonical brand + provenanced real-product gallery")
    else:
        print(
            "presentation contract green: brand/capture rail valid; "
            "curated real-product gallery still pending"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
