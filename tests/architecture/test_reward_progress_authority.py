from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_reward_projection_is_intelligence_owned() -> None:
    source = (ROOT / "src/ai_karen_engine/core/intelligence/reward.py").read_text(encoding="utf-8")
    assert "class RewardProjector" in source
    assert "authorize" in source
    assert "sqlalchemy" not in source
    assert "fastapi" not in source


def test_runtime_outcome_store_is_composed_not_hidden_in_chat_runtime() -> None:
    composition = (ROOT / "src/ai_karen_engine/core/runtime/composition.py").read_text(encoding="utf-8")
    chat_runtime = (ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py").read_text(encoding="utf-8")
    assert "outcome_store=" in composition
    assert "OutcomeRecorder(store=self._composition.outcome_store)" in chat_runtime
    assert "PostgresOutcomeStore(" not in chat_runtime


def test_progress_route_stays_thin() -> None:
    source = (ROOT / "src/ai_karen_engine/api_routes/users/progress.py").read_text(encoding="utf-8")
    assert "get_current_user" in source
    assert "get_reward_progress_service" in source
    assert "RewardProjector(" not in source
    assert "sqlalchemy" not in source


def test_outcome_migration_is_tenant_scoped_and_rls_enforced() -> None:
    source = (
        ROOT / "supabase/migrations/20261003010000_20_runtime_outcome_evidence.sql"
    ).read_text(encoding="utf-8")
    assert "tenant_id uuid NOT NULL" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "app.current_tenant_id" in source


def test_growth_ui_consumes_backend_truth() -> None:
    source = (
        ROOT
        / "src/ui_launchers/Karen-AI-Theme/src/components/growth/GrowthPage.tsx"
    ).read_text(encoding="utf-8")
    assert "/api/progress/" in source
    assert "progress_index" in source
    assert "Math.random" not in source
    assert "localStorage" not in source


def test_chat_feedback_is_backend_persisted_not_ui_local() -> None:
    source = (
        ROOT
        / "src/ui_launchers/Karen-AI-Theme/src/components/chat/MessageBubble.tsx"
    ).read_text(encoding="utf-8")
    assert "/api/progress/feedback" in source
    assert "Feedback remains UI-local" not in source
    assert "trajectory_id" in source


def test_chat_runtime_uses_async_outcome_persistence() -> None:
    source = (ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py").read_text(encoding="utf-8")
    store = (ROOT / "src/ai_karen_engine/core/runtime/outcome/store.py").read_text(encoding="utf-8")
    assert "await self._outcome_recorder.record_execution_outcome_async(" in source
    assert "async_transaction_scope" in store
    assert "async def save_outcome_async" in store


def test_streamed_transcript_persists_trajectory_identity_for_feedback() -> None:
    source = (ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py").read_text(encoding="utf-8")
    assert "trajectory_id=trajectory.trajectory_id" in source
    assert '**({"trajectory_id": trajectory_id} if trajectory_id else {})' in source



def test_legacy_adaptive_reward_computer_is_retired() -> None:
    retired_module = (
        ROOT
        / "src/ai_karen_engine/core/adaptive/learning/experience/reward.py"
    )
    experience_init = (
        ROOT
        / "src/ai_karen_engine/core/adaptive/learning/experience/__init__.py"
    ).read_text(encoding="utf-8")
    adaptive_contracts = (
        ROOT
        / "src/ai_karen_engine/core/adaptive/learning/experience/contracts.py"
    ).read_text(encoding="utf-8")

    assert not retired_module.exists()
    assert "RewardComputer" not in experience_init
    assert "experience.reward" not in experience_init

    # The adaptive vector remains a neutral data contract for learning signals.
    assert "class LearningRewardVector" in adaptive_contracts
    assert "not a product reward authority" in adaptive_contracts
    assert "def aggregate(" not in adaptive_contracts


def test_reward_projector_is_only_executable_reward_calculator() -> None:
    src_root = ROOT / "src/ai_karen_engine"
    offenders: list[str] = []
    for path in src_root.rglob("*.py"):
        if path == src_root / "core/intelligence/reward.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "class RewardComputer" in source:
            offenders.append(str(path.relative_to(ROOT)))
        if "from ai_karen_engine.core.adaptive.learning.experience.reward" in source:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
