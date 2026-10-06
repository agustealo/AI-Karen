from __future__ import annotations

import pytest

from ai_karen_engine.config.proactive import (
    get_proactive_continuity_settings,
    reset_proactive_continuity_settings,
)


@pytest.fixture(autouse=True)
def _reset_settings() -> None:
    reset_proactive_continuity_settings()
    yield
    reset_proactive_continuity_settings()


def test_proactive_continuity_defaults_are_valid() -> None:
    settings = get_proactive_continuity_settings()

    assert settings.enabled is True
    assert settings.max_candidates == 5
    assert settings.behavior_min_observations >= 2
    assert 0.0 <= settings.min_candidate_utility <= 1.0


def test_proactive_continuity_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARI_PROACTIVE_CONTINUITY_ENABLED", "false")

    assert get_proactive_continuity_settings().enabled is False


def test_invalid_boolean_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARI_PROACTIVE_CONTINUITY_ENABLED", "sometimes")

    with pytest.raises(RuntimeError, match="must be a boolean"):
        get_proactive_continuity_settings()


def test_invalid_candidate_limit_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARI_PROACTIVE_CONTINUITY_MAX_CANDIDATES", "50")

    with pytest.raises(RuntimeError, match="between 1 and 20"):
        get_proactive_continuity_settings()


def test_invalid_weight_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARI_PROACTIVE_CONTINUITY_OPEN_LOOP_WEIGHT", "1.5")

    with pytest.raises(RuntimeError, match="between 0 and 1"):
        get_proactive_continuity_settings()


def test_non_monotonic_time_windows_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KARI_PROACTIVE_CONTINUITY_DUE_SOON_HOURS", "48")
    monkeypatch.setenv("KARI_PROACTIVE_CONTINUITY_DUE_DAY_HOURS", "24")

    with pytest.raises(RuntimeError, match="must be monotonic"):
        get_proactive_continuity_settings()
