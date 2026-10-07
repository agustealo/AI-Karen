from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEAD_DUPLICATE = ROOT / "src/ai_karen_engine/services/conversation_service.py"
DEPENDENCIES = ROOT / "src/ai_karen_engine/core/services/dependencies.py"
GATEWAY = ROOT / "src/ai_karen_engine/core/runtime/conversation_runtime_gateway.py"


def test_duplicate_legacy_conversation_crud_service_is_retired() -> None:
    assert not DEAD_DUPLICATE.exists()


def test_active_conversation_authority_remains_gateway_repository_path() -> None:
    dependencies = DEPENDENCIES.read_text(encoding="utf-8")
    gateway = GATEWAY.read_text(encoding="utf-8")

    assert "ConversationRuntimeGateway" in gateway
    assert "ConversationRepository" in gateway
    assert "from ai_karen_engine.services.conversation_service" not in dependencies
