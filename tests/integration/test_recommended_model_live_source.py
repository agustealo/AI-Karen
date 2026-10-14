"""Opt-in, real-network verification for Karen's configured first-run models.

Run with:
    KAREN_LIVE_MODEL_SOURCE_PROOF=1 PYTHONPATH=src pytest tests/integration/test_recommended_model_live_source.py -q

This test never downloads model weights or claims runtime inference readiness.
It uses the canonical source metadata resolver, not fabricated HF fixtures.
"""
from __future__ import annotations

import os
import re

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
