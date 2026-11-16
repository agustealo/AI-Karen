"""KCM admission feature switches must come only from canonical learning settings."""

from __future__ import annotations

import pytest

from ai_karen_engine.config.learning import LearningSettings


def test_admission_settings_default_disabled() -> None:
    cfg = LearningSettings()
    assert cfg.kcm_training_admission_enabled is False
    assert 0.0 < cfg.kcm_training_min_quality <= 1.0


def test_admission_settings_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("KCM_TRAINING_ADMISSION_ENABLED", "true")
    monkeypatch.setenv("KCM_TRAINING_MIN_QUALITY", "0.91")
    monkeypatch.setenv("KCM_TRAINING_MIN_CORRECTNESS", "0.95")
    monkeypatch.setenv("KCM_TRAINING_MIN_PROVENANCE", "0.90")
    cfg = LearningSettings()
    cfg.apply_env_overrides()
    assert cfg.kcm_training_admission_enabled is True
    assert cfg.kcm_training_min_quality == pytest.approx(0.91)
    assert cfg.kcm_training_min_correctness == pytest.approx(0.95)
    assert cfg.kcm_training_min_provenance == pytest.approx(0.9)


@pytest.mark.parametrize("key,value", [
    ("KCM_TRAINING_ADMISSION_ENABLED", "maybe"),
    ("KCM_TRAINING_MIN_QUALITY", "nan"),
    ("KCM_TRAINING_MIN_QUALITY", "-1"),
    ("KCM_TRAINING_MIN_CORRECTNESS", "2"),
])
def test_invalid_admission_settings_fail_closed(monkeypatch, key: str, value: str) -> None:
    monkeypatch.setenv(key, value)
    cfg = LearningSettings()
    with pytest.raises(ValueError):
        cfg.apply_env_overrides()
