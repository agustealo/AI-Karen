"""Architecture contract for the split chat intelligence surface."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHAT_RUNTIME = ROOT / "src" / "ai_karen_engine" / "core" / "runtime" / "chat_runtime.py"
CHAT_UI = (
    ROOT
    / "src"
    / "ui_launchers"
    / "Karen-AI-Theme"
    / "src"
    / "components"
    / "chat"
)
CHAT_INTERFACE = CHAT_UI / "ChatInterface.tsx"
SIDECAR = CHAT_UI / "ChatIntelligenceSidecar.tsx"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chat_runtime_projects_existing_learning_lineage_to_public_metadata() -> None:
    source = _source(CHAT_RUNTIME)

    assert 'result.metadata.extra["trajectory_id"]' in source
    assert 'result.metadata.extra["policy_decision_id"]' in source
    assert 'result.metadata.extra["decision_observation_id"]' in source
    assert 'result.metadata.extra["feature_snapshot_count"]' in source

    assert 'terminal_metadata["trajectory_id"]' in source
    assert 'terminal_metadata["policy_decision_id"]' in source
    assert 'terminal_metadata["decision_observation_id"]' in source
    assert 'terminal_metadata["feature_snapshot_count"]' in source


def test_chat_interface_uses_one_split_intelligence_surface() -> None:
    chat = _source(CHAT_INTERFACE)
    sidecar = _source(SIDECAR)

    assert "import ChatIntelligenceSidecar from './ChatIntelligenceSidecar';" in chat
    assert 'xl:grid-cols-[minmax(0,1fr)_360px]' in chat
    assert "<ChatIntelligenceSidecar" in chat

    assert "RuntimeMetadataPanel" not in chat
    assert "RuntimeReceipt" not in chat
    assert "AgentActivityPanel" not in chat

    assert "AgentActivityPanel" in sidecar
    assert "Memory & Continuity" in sidecar
    assert "Learning & Outcome" in sidecar
    assert "Agents & Tools" in sidecar


def test_intelligence_sidecar_is_observability_only() -> None:
    sidecar = _source(SIDECAR)

    forbidden = (
        "applyModelSelection",
        "apiClient.post(",
        "apiClient.put(",
        "apiClient.delete(",
        "memory.write",
        "promote",
        "activate_model",
    )
    for token in forbidden:
        assert token not in sidecar


def test_sidecar_falls_back_to_not_reported_instead_of_fake_metrics() -> None:
    sidecar = _source(SIDECAR)

    assert "not reported" in sidecar
    assert "has not reported memory recall or formation evidence" in sidecar
    assert "Learning lineage or outcome evidence has not been reported" in sidecar
