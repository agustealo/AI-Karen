from __future__ import annotations

import json
import re
import struct
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRESENTATION_MANIFEST = REPO_ROOT / "docs" / "presentation-manifest.json"
SCREENSHOT_DIR = REPO_ROOT / "docs" / "assets" / "screenshots"
CAPTURE_MANIFEST = SCREENSHOT_DIR / "capture-manifest.json"


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path} is not a valid PNG file")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _assert_capture_sha_is_ancestor(capture_sha: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", capture_sha, "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"presentation capture SHA {capture_sha} is not an ancestor of current HEAD; "
        "recapture the product from the branch being presented"
    )


def test_presentation_manifest_points_to_real_assets() -> None:
    payload = json.loads(PRESENTATION_MANIFEST.read_text(encoding="utf-8"))

    assert payload["product"] == "KAREN"
    assert payload["product_photography"]["source"] == "real-running-application"

    for asset_key in ("mark", "banner", "ui_mark", "ui_banner", "brand_contract"):
        asset_path = REPO_ROOT / payload["brand"][asset_key]
        assert asset_path.is_file(), f"missing canonical presentation asset: {asset_path}"

    capture_spec = REPO_ROOT / payload["product_photography"]["capture_spec"]
    assert capture_spec.is_file(), f"missing product capture spec: {capture_spec}"


def test_real_product_screenshot_set_is_complete_and_provenanced() -> None:
    payload = json.loads(PRESENTATION_MANIFEST.read_text(encoding="utf-8"))
    required_files = payload["product_photography"]["required_files"]

    assert CAPTURE_MANIFEST.is_file(), (
        "real KAREN screenshots have not been captured yet; run npm run "
        "capture:presentation against a healthy installation and commit the results"
    )

    capture = json.loads(CAPTURE_MANIFEST.read_text(encoding="utf-8"))
    assert capture["source"] == "real-running-application"
    assert capture["authenticated"] is True
    assert capture["policy"] == {
        "mocked_responses": False,
        "generated_ui": False,
        "fixture_only_state": False,
    }

    capture_sha = capture["git_sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", capture_sha), capture_sha
    _assert_capture_sha_is_ancestor(capture_sha)

    assert capture["files"] == required_files

    for file_name in required_files:
        path = SCREENSHOT_DIR / file_name
        assert path.is_file(), f"missing required real product screenshot: {file_name}"
        width, height = _png_dimensions(path)
        assert width >= 1200, f"{file_name} is too narrow for premium product presentation: {width}px"
        assert height >= 700, f"{file_name} is too short for premium product presentation: {height}px"
        assert path.stat().st_size >= 20_000, (
            f"{file_name} is suspiciously small ({path.stat().st_size} bytes); "
            "verify that it contains a real rendered KAREN view"
        )
