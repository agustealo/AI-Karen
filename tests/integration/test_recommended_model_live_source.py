"""Opt-in, real-network verification for Karen's configured first-run models.

Run with:
    KAREN_LIVE_MODEL_SOURCE_PROOF=1 PYTHONPATH=src pytest tests/integration/test_recommended_model_live_source.py -q

This test never downloads model weights or claims runtime inference readiness.
It uses the canonical source metadata resolver, not fabricated HF fixtures.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path

import pytest

from ai_karen_engine.config.config_asset_loaders import load_model_download_recommendations
from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    ModelOrchestratorService,
)

pytestmark = pytest.mark.skipif(
    os.getenv("KAREN_LIVE_MODEL_SOURCE_PROOF") != "1",
    reason="Opt in to live model-source verification explicitly",
)

IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)


@pytest.mark.asyncio
async def test_curated_model_metadata_live_source_and_revision(tmp_path) -> None:
    """Prove real source resolution, terms, and immutable revision per model."""
    entries = load_model_download_recommendations()["recommendations"]
    assert {entry["id"] for entry in entries} == {
        "spacy-english-core",
        "distilbert-semantic-encoder",
        "qwen3-lightweight-chat",
    }
    orchestrator = ModelOrchestratorService({
        "models_root": str(tmp_path / "models"),
        "registry_path": str(tmp_path / "registry.json"),
    })
    for entry in entries:
        info = await orchestrator.get_model_info(
            entry["model_id"], refresh_remote=True
        )
        assert info.model_id == entry["model_id"]
        assert info.revision and IMMUTABLE_REVISION.fullmatch(info.revision), (
            f"{entry['id']}: missing immutable source revision"
        )
        assert info.license and info.license.strip(), (
            f"{entry['id']}: source did not report reviewable license terms"
        )
        assert info.gated is False, (
            f"{entry['id']}: source unexpectedly requires gated access"
        )

        if entry["id"] == "spacy-english-core":
            # The canonical publisher validates a spaCy directory containing
            # config.cfg and meta.json; merely downloading a Python wheel is
            # insufficient to satisfy this contract.
            files = {str(file["path"]) for file in info.files}
            config_dirs = {
                name.removesuffix("/config.cfg") if name != "config.cfg" else ""
                for name in files
                if name == "config.cfg" or name.endswith("/config.cfg")
            }
            meta_dirs = {
                name.removesuffix("/meta.json") if name != "meta.json" else ""
                for name in files
                if name == "meta.json" or name.endswith("/meta.json")
            }
            assert config_dirs & meta_dirs, (
                "spaCy model source contains no publishable directory with "
                "config.cfg and meta.json; wheel-only snapshots require a "
                "governed extraction path before Install Essentials can work"
            )


@pytest.mark.asyncio
async def test_spacy_live_download_registry_and_linguistic_inference(tmp_path) -> None:
    """Opt-in artifact proof: canonical download, persisted registry and spaCy inference.

    Must run inside the actual backend Python environment with spaCy installed.
    Do not make normal CI depend on model downloads.
    """
    if os.getenv("KAREN_LIVE_SPACY_ARTIFACT_PROOF") != "1":
        pytest.skip("Requires explicit live spaCy artifact proof opt-in")
    import spacy

    catalog = load_model_download_recommendations()["recommendations"]
    item = next(entry for entry in catalog if entry["id"] == "spacy-english-core")
    # Source verification precedes downloading and must resolve immutable SHA.
    models_root = tmp_path / "models"
    registry_path = tmp_path / "registry.json"
    orchestrator = ModelOrchestratorService({
        "models_root": str(models_root),
        "registry_path": str(registry_path),
    })
    remote = await orchestrator.get_model_info(item["model_id"], refresh_remote=True)
    assert remote.license and remote.license.strip(), "Source license unavailable"
    assert not remote.gated, "Unexpected gated model source"
    assert remote.revision and IMMUTABLE_REVISION.fullmatch(remote.revision)

    from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
        DownloadRequest,
    )

    result = await orchestrator.download_model(DownloadRequest(
        model_id=item["model_id"],
        revision=remote.revision,
        storage_key="spacy",
    ))
    from pathlib import Path
    root = Path(result.install_path)
    assert root.is_dir() and not root.is_symlink()
    assert (root / "config.cfg").is_file()
    assert (root / "meta.json").is_file()
    registry = await orchestrator.snapshot_registry_entry(item["model_id"])
    assert registry is not None
    assert Path(registry["install_path"]) == root
    # Exercise exactly the path the canonical download publishes.
    nlp = spacy.load(root)
    doc = nlp("Karen runs local language analysis in Detroit.")
    assert nlp.pipe_names
    assert len(doc) > 0
    assert any(token.pos_ for token in doc), "Expected linguistic analysis"


@pytest.mark.asyncio
async def test_distilbert_live_pinned_download_and_nonfallback_encoding(tmp_path) -> None:
    """Opt-in real artifact and inference proof, not part of ordinary CI."""
    if os.getenv("KAREN_LIVE_DISTILBERT_ARTIFACT_PROOF") != "1":
        pytest.skip("Requires explicit live DistilBERT artifact proof opt-in")

    from pathlib import Path
    from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
        DownloadRequest,
    )
    from ai_karen_engine.core.intelligence.ml.encoders.distilbert import (
        DistilBertSemanticEncoder,
    )
    from ai_karen_engine.core.memory.signals.nlp_config import DistilBertConfig

    item = next(
        entry for entry in load_model_download_recommendations()["recommendations"]
        if entry["id"] == "distilbert-semantic-encoder"
    )
    orchestrator = ModelOrchestratorService({
        "models_root": str(tmp_path / "models"),
        "registry_path": str(tmp_path / "registry.json"),
    })
    remote = await orchestrator.get_model_info(item["model_id"], refresh_remote=True)
    assert remote.license and remote.license.strip(), "Source license unavailable"
    assert not remote.gated, "Unexpected gated source"
    assert remote.revision and IMMUTABLE_REVISION.fullmatch(remote.revision)

    result = await orchestrator.download_model(DownloadRequest(
        model_id=item["model_id"],
        revision=remote.revision,
        storage_key="transformers",
        include_patterns=item.get("include_patterns"),
    ))
    root = Path(result.install_path)
    assert root.is_dir() and not root.is_symlink()
    assert (root / "config.json").is_file()
    assert (root / "model.safetensors").is_file()
    assert (root / "tokenizer_config.json").is_file()
    registry = await orchestrator.snapshot_registry_entry(item["model_id"])
    assert registry and Path(registry["install_path"]) == root

    encoder = DistilBertSemanticEncoder(config=DistilBertConfig(
        model_name=item["model_id"],
        local_model_root=str(tmp_path / "models" / "transformers"),
        enable_gpu=False,
        enable_fallback=False,
    ))
    assert not encoder.fallback_mode and encoder.model is not None
    output = await encoder.encode("Karen runs local semantic encoding.")
    assert not output.fallback_used
    assert output.dimensions == 768
    assert len(output.vector) == 768
    assert any(abs(float(value)) > 0 for value in output.vector)


@pytest.mark.asyncio
async def test_qwen_live_registered_provider_inference() -> None:
    """Opt-in inference against a real, already-running registered local provider.

    This proves provider execution only, not download, deployment or model loading.
    The operator must configure KAREN_LIVE_QWEN_PROVIDER_ID for a registered
    endpoint exposing the recommended Qwen model.
    """
    if os.getenv("KAREN_LIVE_QWEN_PROVIDER_PROOF") != "1":
        pytest.skip("Requires explicit live Qwen provider proof opt-in")

    provider_id = os.getenv("KAREN_LIVE_QWEN_PROVIDER_ID", "").strip()
    assert provider_id, "Set KAREN_LIVE_QWEN_PROVIDER_ID to a registered local provider"

    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        ProviderRegistryService,
    )
    from ai_karen_engine.core.model_runtime.provider_execution import (
        execute_provider_endpoint,
    )
    from ai_karen_engine.core.model_runtime.runtime_engine import (
        EndpointProtocol,
        Locality,
    )

    item = next(
        entry for entry in load_model_download_recommendations()["recommendations"]
        if entry["id"] == "qwen3-lightweight-chat"
    )
    registry = ProviderRegistryService()
    endpoint = registry.get_provider_endpoint(provider_id)
    assert endpoint is not None, "Provider is not registered"
    assert endpoint.enabled and endpoint.locality == Locality.LOCAL
    assert endpoint.protocol == EndpointProtocol.OPENAI_COMPATIBLE
    assert "chat_completion" in endpoint.capabilities

    result = await execute_provider_endpoint(
        endpoint,
        messages=[{
            "role": "user",
            "content": "Respond in one short sentence describing a local language model.",
        }],
        model=item["model_id"],
        max_tokens=80,
        temperature=0.0,
    )
    assert result.provider_id == endpoint.provider_id
    assert result.text.strip(), "Provider returned no real generated text"
    assert result.model == item["model_id"], (
        "Provider executed a different model than the recommended Qwen3"
    )


def test_pocket_tts_live_pinned_manifest_matches_both_transports() -> None:
    """Compare independent live HF SDK and direct HTTPS file manifests.

    Explicit opt-in with approved gated source account; metadata only. No
    model weights, Karen model jobs, plugin activation, or audio inference.
    """
    if os.getenv("KAREN_LIVE_POCKET_MANIFEST_PROOF") != "1":
        pytest.skip("Requires explicit gated Pocket manifest parity opt-in")
    token = next(
        (
            os.environ[name].strip()
            for name in ("HF_TOKEN", "HUGGINGFACE_API_KEY", "HUGGING_FACE_HUB_TOKEN")
            if os.environ.get(name, "").strip()
        ),
        "",
    )
    if not token:
        pytest.fail(
            "Licensed Pocket manifest proof requires an approved private HF token",
            pytrace=False,
        )

    from huggingface_hub import HfApi, RepoFile
    from ai_karen_engine.core.model_runtime.management import (
        direct_https_model_transport as direct,
    )

    spec_path = (
        Path(__file__).resolve().parents[2]
        / "src/ai_karen_engine/extensions/plugins/pocket-tts/model_spec.json"
    )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    recommended = next(
        entry
        for entry in load_model_download_recommendations()["recommendations"]
        if entry["id"] == "pocket-tts-english-18m-refl"
    )
    model_id = str(spec["model_id"])
    revision = str(spec["revision"])
    patterns = list(recommended["include_patterns"])
    assert recommended["model_id"] == model_id
    assert recommended["revision"] == revision
    assert recommended["channel_id"] == spec["channel_id"] == "plugin_audio"
    assert re.fullmatch(r"[a-f0-9]{40}", revision)
    assert patterns == [
        f'{spec["model_subdirectory"]}/{spec["weights"]}',
        f'{spec["model_subdirectory"]}/{spec["tokenizer"]}',
        f'{spec["model_subdirectory"]}/{spec["voice_dir"]}/*.safetensors',
    ]

    api = HfApi()
    try:
        remote = api.model_info(model_id, revision=revision, token=token)
    except Exception:
        pytest.fail(
            "Pinned gated Pocket metadata inaccessible to approved HF account",
            pytrace=False,
        )
    assert remote.sha == revision, "HF SDK resolved a different Pocket revision"
    assert bool(remote.gated), "Reviewed gated model access contract changed"

    # Hub SDK transparently paginates; direct HTTPS independently validates
    # and follows the cursor chain at the same reviewed repository revision.
    hub_files: dict[str, dict[str, object]] = {}
    # SDK discovery uses the full reviewed language directory independently
    # of the direct transport's per-pattern prefix and cursor selection.
    try:
        entries = list(
            api.list_repo_tree(
                model_id,
                path_in_repo=str(spec["model_subdirectory"]),
                recursive=True,
                expand=True,
                revision=revision,
                token=token,
            )
        )
    except Exception:
        pytest.fail(
            "Gated Pocket file tree inaccessible through Hugging Face SDK",
            pytrace=False,
        )
    for entry in entries:
        if not isinstance(entry, RepoFile):
            continue
        path = direct._safe_path(entry.path)
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
            continue
        assert isinstance(entry.size, int) and 0 < entry.size <= direct._MAX_FILE_BYTES
        lfs = getattr(entry, "lfs", None)
        digest = getattr(lfs, "sha256", None) if lfs is not None else None
        if digest is not None:
            assert re.fullmatch(r"[0-9a-f]{64}", digest)
        candidate = {"size": entry.size, "sha256": digest}
        assert path not in hub_files or hub_files[path] == candidate, (
            "HF SDK reported inconsistent pinned file metadata"
        )
        hub_files[path] = candidate

    assert hub_files, "HF SDK returned no approved Pocket artifacts"
    assert len(hub_files) <= direct._MAX_FILES
    assert sum(int(item["size"]) for item in hub_files.values()) <= direct._MAX_TOTAL_BYTES

    try:
        direct_files = direct._discover(model_id, revision, patterns, [], token)
    except direct.DirectHttpsDownloadError:
        pytest.fail(
            "Direct HTTPS cannot enumerate the complete gated pinned Pocket tree",
            pytrace=False,
        )
    direct_by_path = {
        item["path"]: {"size": item["size"], "sha256": item["sha256"]}
        for item in direct_files
    }
    assert direct_by_path == hub_files, (
        "Pinned direct HTTPS and Hub SDK inventories differ; "
        "neither transport is source-certified by this test"
    )

    mandatory = {
        f'{spec["model_subdirectory"]}/{spec["weights"]}',
        f'{spec["model_subdirectory"]}/{spec["tokenizer"]}',
    }
    assert mandatory.issubset(direct_by_path), "Required Pocket model files absent"
    voice_prefix = f'{spec["model_subdirectory"]}/{spec["voice_dir"]}/'
    assert any(
        path.startswith(voice_prefix) and path.endswith(".safetensors")
        for path in direct_by_path
    ), "No approved precomputed voice states in reviewed revision"
