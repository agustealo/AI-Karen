from __future__ import annotations

from pathlib import Path


GROWTH = (
    Path(__file__).resolve().parents[2]
    / "src/ui_launchers/Karen-AI-Theme/src/components/growth/GrowthPage.tsx"
)


def test_growth_preserves_authoritative_backend_and_no_fake_scores() -> None:
    source = GROWTH.read_text(encoding="utf-8")
    assert 'apiClient.get<RewardProgressResponse>("/api/progress/")' in source
    assert "No fallback score has been invented." in source
    assert "setProgress(response)" in source
    assert "progress.recent_evidence.map" in source
    assert "progress.milestones.map" in source
    assert "progress.dimensions[key]" in source


def test_growth_uses_existing_canonical_visual_primitives() -> None:
    source = GROWTH.read_text(encoding="utf-8")
    assert "karen-page-title" in source
    assert "karen-page-description" in source
    assert "karen-surface" in source
    assert "karen-metric" in source
    assert "karen-growth-hero" in source
    assert "aria-labelledby" in source
    assert "sm:grid-cols-2 xl:grid-cols-3" in source
    assert "memory consent" in source


def test_growth_does_not_invent_policy_verification_receipt() -> None:
    source = GROWTH.read_text(encoding="utf-8")
    assert "Evidence-based projection" in source
    assert "Policy verified projection" not in source
