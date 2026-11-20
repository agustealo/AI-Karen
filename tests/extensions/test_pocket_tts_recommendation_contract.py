"""Keep the governed Pocket TTS model pin aligned with the curated downloader.

These are packaging invariants, not proof that the model was fetched, licensed,
installed, tenant-eligible, or actually loadable on an operator's CPU.
"""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "src/ai_karen_engine/extensions/plugins/pocket-tts"
CURATED = ROOT / "config_assets/model_download_recommendations.json"


def test_pocket_recommendation_is_pinned_to_the_plugin_runtime_spec() -> None:
    spec = json.loads((PLUGIN / "model_spec.json").read_text(encoding="utf-8"))
    recommendations = json.loads(CURATED.read_text(encoding="utf-8"))[
        "recommendations"
    ]
    matches = [
        row for row in recommendations
        if spec["plugin_id"] in row.get("app_consumers", [])
    ]
    assert len(matches) == 1, "Every Pocket model must have one curated authority"
    curated = matches[0]

    assert curated["model_id"] == spec["model_id"]
    assert curated["channel_id"] == spec["channel_id"]
    assert curated["revision"] == spec["revision"]
    assert curated["expected_runtime"] == spec["runtime_package"]
    assert curated["license"] == spec["model_license"]
    assert curated["license_url"] == (
        f"https://huggingface.co/{spec['model_id']}"
    )
    assert curated["revision"] and len(curated["revision"]) == 40
    assert all(char in "0123456789abcdef" for char in curated["revision"])
    assert curated.get("recommended") is False
    assert curated["tier"] == "optional"
    # The official non-cloning Pocket repository is public, but the runtime
    # must still verify the immutable source and license metadata.
    assert curated["model_id"] == "kyutai/pocket-tts-without-voice-cloning"
    assert curated["revision"] == "a7056f505a4a8ca72d8b5fb1440071d6f1a35739"
    assert curated.get("gated") is False
    default_ids = {
        row["id"] for row in recommendations if row.get("recommended") is True
    }
    assert len(default_ids) == 3
    assert curated["id"] not in default_ids

    base = spec["model_subdirectory"]
    included = curated["include_patterns"]
    # The curated model choices belong to acquisition; the native spec owns
    # the loader. Assert their precise contract without creating another
    # manifest, download registry, or alternate plugin executor.
    assert included == [
        f"{base}/{spec['weights']}",
        f"{base}/{spec['tokenizer']}",
        f"{base}/{spec['voice_dir']}/*.safetensors",
    ]
    assert all(
        not pattern.startswith("/") and
        all(part not in {"", ".", ".."} for part in pattern.split("/"))
        for pattern in included
    )
    required = (
        f"{base}/{spec['weights']}",
        f"{base}/{spec['tokenizer']}",
        f"{base}/{spec['voice_dir']}/alba.safetensors",
    )
    unrelated = (
        f"{base}/{spec['voice_dir']}/README.txt",
        "languages/english_7m_refl_2026-10/model.safetensors",
        "languages/english_2m_refl_2026-10/tokenizer.model",
    )
    assert all(any(fnmatchcase(path, pattern) for pattern in included) for path in required)
    assert all(
        not any(fnmatchcase(path, pattern) for pattern in included)
        for path in unrelated
    )


def test_pocket_model_download_remains_in_canonical_admin_governed_service() -> None:
    route = (
        ROOT / "src/ai_karen_engine/api_routes/models/model_orchestrator.py"
    ).read_text(encoding="utf-8")
    service = (
        ROOT / "src/ai_karen_engine/core/model_runtime/model_download_control_service.py"
    ).read_text(encoding="utf-8")
    plugin = (PLUGIN / "handler.py").read_text(encoding="utf-8")
    ui = (
        ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/plugins/"
        "PluginRecommendedModels.tsx"
    ).read_text(encoding="utf-8")

    assert 'admin-scopes this router' in route
    assert '@router.post("/download/validate"' in route
    assert '@router.post("/download", response_model=Dict[str, str])' in route
    assert "async def start_download(" in service
    assert "async def list_completed_model_installations(" in service
    assert "list_completed_model_installations(" in plugin
    assert 'job.get("license_accepted") is not True' in plugin
    assert 'job.get("trust_remote_code") is True' in plugin
    assert 'job.get("tenant_id") or ""' in plugin
    assert "apiClient.post<DownloadValidation>" in ui
    assert "apiClient.post<DownloadReceipt>" in ui
    assert "validated_revision: revision" in ui
    assert "trust_remote_code: false" in ui
    assert "accept_license: true" in ui
    assert "pin: true" in ui
    assert "isAdmin()" in ui
    assert "metadata_verified" in ui
    assert "No installation was started." in ui


def test_pocket_optional_cpu_image_uses_pinned_native_runtime() -> None:
    """Build-time dependency must match the loader, without baking in weights."""
    spec = json.loads((PLUGIN / "model_spec.json").read_text(encoding="utf-8"))
    requirements = (
        ROOT / "requirements/pocket-tts.txt"
    ).read_text(encoding="utf-8").splitlines()
    packages = [line.strip() for line in requirements if line.strip() and not line.startswith("#")]
    assert packages == [f"{spec['runtime_package']}=={spec['runtime_version']}"]

    image = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM runtime AS runtime-pocket-tts" in image
    assert "COPY requirements/pocket-tts.txt /app/requirements/pocket-tts.txt" in image
    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in image
    assert "-r /app/requirements/pocket-tts.txt" in image
    assert "python -m pip check" in image
    assert "from pocket_tts import TTSModel" in image
    assert "FROM ${PROFILE} AS app" in image
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "PROFILE: ${API_BUILD_TARGET:-runtime}" in compose

    # A host package may be installed at image build, but licensed model
    # weights must still be fetched only through Karen's governed model worker.
    assert "snapshot_download" not in image
    assert "huggingface-cli download" not in image
    assert "HF_TOKEN" not in image
