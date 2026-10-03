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
