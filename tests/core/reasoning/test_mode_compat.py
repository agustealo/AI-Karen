from __future__ import annotations

from ai_karen_engine.core.reasoning.mode_compat import normalize_reasoning_modes


def test_deep_legacy_mode_expands_to_canonical_non_soft_pipeline() -> None:
    modes = normalize_reasoning_modes(["deep"])

    assert modes == [
        "evidence_synthesis",
        "verification",
        "refinement",
        "metacognition",
    ]
    assert "soft_exploration" not in modes


def test_generic_reasoning_capability_never_implies_soft_exploration() -> None:
    modes = normalize_reasoning_modes(["reasoning"])

    assert "soft_exploration" not in modes
    assert "evidence_synthesis" in modes


def test_soft_exploration_survives_only_when_explicitly_requested() -> None:
    modes = normalize_reasoning_modes(["soft_exploration"])

    assert modes == ["soft_exploration"]


def test_unknown_mode_is_preserved_for_fail_closed_authorization() -> None:
    modes = normalize_reasoning_modes(["unknown_future_mode"])

    assert modes == ["unknown_future_mode"]


def test_duplicate_alias_expansion_is_stable_and_deduplicated() -> None:
    modes = normalize_reasoning_modes(["deep", "verification", "synthesis"])

    assert modes == [
        "evidence_synthesis",
        "verification",
        "refinement",
        "metacognition",
    ]
