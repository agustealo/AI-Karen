from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "src/ai_karen_engine/core/runtime/prompt/prompt_registry.py"
TRAJECTORY_STORE = ROOT / "src/ai_karen_engine/core/runtime/trajectory/store.py"


def test_token_estimate_supports_incremental_breakdown_construction() -> None:
    source = REGISTRY.read_text(encoding="utf-8")

    assert "total_tokens: int = 0" in source
    assert "breakdown = TokenEstimate()" in source


def test_canonical_chat_prompt_is_builtin_registry_contract() -> None:
    source = REGISTRY.read_text(encoding="utf-8")

    assert 'prompt_id = "karen.chat.default"' in source
    assert 'version="v1.0.0"' in source
    assert 'status=PromptLifecycleStatus.ACTIVE' in source
    assert 'is_default=True' in source
    assert '"owner": "prompt_runtime"' in source


def test_learning_store_binds_real_datetimes_not_iso_strings() -> None:
    source = TRAJECTORY_STORE.read_text(encoding="utf-8")

    assert "def _normalize_datetime(value: Any) -> datetime | None:" in source
    assert "trajectory.started_at.isoformat()" not in source
    assert "trajectory.completed_at.isoformat()" not in source
    assert "snapshot.created_at.isoformat()" not in source
    assert "observation.created_at.isoformat()" not in source
    assert "PostgresTrajectoryStore._normalize_datetime(" in source
