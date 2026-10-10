from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.transformer_executor import TransformerLoRAExecutor


def _job(tmp_path, **overrides):
    config = {
        "base_model_path": str(tmp_path),
        "license_accepted": False,
        "license_id": "",
        "license_model_path": "",
    }
    config.update(overrides)
    return TrainingJob(
        job_id="lora-license-test", task="intent", base_model="transformers",
        dataset_version="training-v1", metadata={
            "tenant_id": "tenant-a", "advanced_config": config,
        },
    )


def test_lora_rejects_unaccepted_model_license_before_loading_weights(tmp_path):
    (tmp_path / "config.json").write_text('{"model_type":"gpt2"}')
    with pytest.raises(PermissionError, match="license"):
        TransformerLoRAExecutor().execute(_job(tmp_path))


def test_lora_rejects_license_for_different_model_path(tmp_path):
    (tmp_path / "config.json").write_text('{"model_type":"gpt2"}')
    with pytest.raises(PermissionError, match="does not match"):
        TransformerLoRAExecutor().execute(_job(
            tmp_path, license_accepted=True, license_id="test-terms",
            license_model_path="/some/other/model",
        ))
