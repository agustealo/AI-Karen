from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
USER_MODELS = ROOT / "src/ai_karen_engine/auth/models.py"
DEPENDENCIES = ROOT / "src/ai_karen_engine/core/services/dependencies.py"
CHAT_ROUTE = ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"


def test_user_data_does_not_synthesize_default_tenant() -> None:
    source = USER_MODELS.read_text(encoding="utf-8")

    assert 'tenant_id: str = ""' in source
    assert 'payload.get("tenant_id") or payload.get("org_id") or ""' in source
    assert 'tenant_id: str = "default"' not in source


def test_authenticated_dependency_requires_user_and_tenant_scope() -> None:
    source = DEPENDENCIES.read_text(encoding="utf-8")

    assert "def _require_identity_scope" in source
    assert 'detail="Authenticated user identity is incomplete"' in source
    assert 'detail="Authenticated tenant context is required"' in source
    assert '"anonymous"' not in source
    assert '"dev-tenant"' not in source


def test_chat_ingress_identity_is_server_resolved_before_runtime() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    assert "Depends(bypass_user_context_func)" in source
    assert "ChatExecutionContext(" in source
    assert "tenant_id" in source
    assert "user_id" in source


def test_missing_tenant_cannot_reach_chat_runtime_through_shared_dependency() -> None:
    dependencies = DEPENDENCIES.read_text(encoding="utf-8")
    chat = CHAT_ROUTE.read_text(encoding="utf-8")

    # The route's transitional fallback is unreachable because the shared auth
    # dependency now rejects an empty tenant before route execution. Keep this
    # guard until the large route file is physically simplified.
    assert "return _require_identity_scope(UserData.from_dict(user_dict))" in dependencies
    assert "Depends(bypass_user_context_func)" in chat
