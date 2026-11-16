"""A failed backend dependency must not be reported as trained model output."""

from __future__ import annotations

import pytest

from ai_karen_engine.echocore.production_fine_tuner import ProductionFineTuner


@pytest.mark.asyncio
async def test_real_training_failure_cannot_be_replaced_with_mock(tmp_path, monkeypatch) -> None:
    tuner = ProductionFineTuner(
        logs_path=tmp_path / "missing.jsonl",
        output_dir=tmp_path / "training",
        enable_experiment_tracking=False,
    )

    async def unavailable(*args, **kwargs):
        raise ImportError("training dependencies unavailable")

    monkeypatch.setattr(tuner, "_train_with_transformers", unavailable)
    with pytest.raises(ImportError):
        await tuner.fine_tune(
            "unavailable-model",
            train_texts=["Verified supervised training example"],
            val_texts=[],
        )
    assert tuner.current_run is not None
    assert tuner.current_run.status == "failed"
    assert tuner.current_run.final_metrics is None
