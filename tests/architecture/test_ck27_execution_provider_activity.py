"""CK-27I: a requested provider alone is not an execution trace."""
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/chat/ConversationContextRail.tsx"


def test_execution_activity_excludes_requested_provider_fallback() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    usage = source.split("const normalizeExecutionUsage =", 1)[1].split("const normalizeRuntimeInsight =", 1)[0]
    assert "asString(metadata.actual_provider)" in usage
    assert "asString(metadata.provider)" in usage
    assert "asString(metadata.requested_provider)" not in usage
    assert "asString(responseMetadata.actual_provider)" in usage
