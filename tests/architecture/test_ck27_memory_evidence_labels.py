"""CK-27G: Consumer rail must distinguish retrieval from memory formation."""
from pathlib import Path

RAIL = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ConversationContextRail.tsx"


def test_retrieved_memory_is_not_claimed_as_used_in_answer() -> None:
    source = RAIL.read_text(encoding="utf-8")
    assert "Retrieved memory preview (" in source
    assert "Retrieved context is not evidence that an excerpt was used in the answer." in source


def test_memory_formation_counts_are_labeled_as_runtime_reports() -> None:
    source = RAIL.read_text(encoding="utf-8")
    assert "Memory formation reported by runtime" in source
    assert "{turnIntelligence.memoryPersistedCount} reported persisted" in source
    assert "Learning this turn" not in source
