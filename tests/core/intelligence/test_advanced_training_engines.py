from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ai_karen_engine.core.intelligence.ml.training.advanced_preflight import (
    preflight_advanced_engine,
)


def _check(root, engine="timeseries", **overrides):
    cfg = dict(
        dataset_root=root, engine=engine, task="outcome_forecast",
        dataset_version="series_v1", test_split=0.2, max_samples=100,
        base_model_path=None, license_id=None, license_accepted=False,
        license_model_path=None, epochs=1, sequence_length=256, lora_rank=8,
        allow_cpu_training=True, lags=5, horizon=1,
    )
    cfg.update(overrides)
    return preflight_advanced_engine(**cfg)


def test_temporal_preflight_accepts_ordered_numeric_series(tmp_path):
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    path = tmp_path / "series_v1.jsonl"
    path.write_text("\n".join(json.dumps({
        "timestamp": (first + timedelta(days=i)).isoformat(), "value": i * 1.2,
    }) for i in range(40)) + "\n")
    result = _check(tmp_path)
    assert result["ready"] or {item["code"] for item in result["checks"]} == {"missing_dependency"}
    assert result["evidence"]["examples_scanned"] == 40


def test_temporal_preflight_rejects_future_then_past(tmp_path):
    path = tmp_path / "series_v1.jsonl"
    path.write_text(
        '{"timestamp":"2026-01-02T00:00:00+00:00","value":2}\n'
        '{"timestamp":"2026-01-01T00:00:00+00:00","value":1}\n'
    )
    result = _check(tmp_path)
    assert not result["ready"]
    assert "invalid_dataset_record" in {item["code"] for item in result["checks"]}


def test_lora_preflight_requires_selected_license_and_local_model(tmp_path):
    path = tmp_path / "series_v1.jsonl"
    path.write_text('{"text":"Training example"}\n' * 20)
    result = _check(tmp_path, engine="transformers")
    assert not result["ready"]
    codes = {item["code"] for item in result["checks"]}
    assert "base_model_missing" in codes


def test_lora_preflight_rejects_duplicate_holdout_candidates(tmp_path):
    path = tmp_path / "series_v1.jsonl"
    path.write_text(('{"text":"same training example"}\n') * 20)
    result = _check(tmp_path, engine="transformers")
    assert result["ready"] is False
    assert "invalid_dataset_record" in {item["code"] for item in result["checks"]}


def test_temporal_preflight_rejects_invalid_lag_type_without_crashing(tmp_path):
    result = _check(tmp_path, lags="five")
    assert result["ready"] is False
    assert "invalid_lags" in {item["code"] for item in result["checks"]}
