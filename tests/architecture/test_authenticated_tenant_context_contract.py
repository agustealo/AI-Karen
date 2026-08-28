from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
USER_MODELS = ROOT / "src/ai_karen_engine/auth/models.py"
DEPENDENCIES = ROOT / "src/ai_karen_engine/core/services/dependencies.py"
CHAT_ROUTE = ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"
CONVERSATION_ROUTE = ROOT / "src/ai_karen_engine/api_routes/chat/conversation.py"
AUTH_ROUTE = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"


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

    # Synthetic tenant identifiers may exist only as explicit deny-list values
    # and in the configured development bypass path. Production-authenticated
    # requests must reject them rather than silently treating them as durable scope.
    assert '_SYNTHETIC_TENANT_IDS = frozenset({"default", "dev-tenant"})' in source
    assert "if not allow_synthetic_tenant and tenant_id.lower() in _SYNTHETIC_TENANT_IDS:" in source
    assert 'detail="Authenticated tenant context is not authoritative"' in source
    assert "allow_synthetic_tenant=True" in source
    assert "if auth_config.should_bypass_auth():" in source


def test_auth_route_requires_durable_tenant_instead_of_inventing_default() -> None:
    source = AUTH_ROUTE.read_text(encoding="utf-8")

    assert 'payload.get("tenant_id") or payload.get("org_id") or ""' in source
    assert 'detail="Authenticated user context is missing durable tenant scope"' in source
    assert 'payload.get("tenant_id") or payload.get("org_id") or "default"' not in source
    assert 'tenant_id=actor["tenant_id"]' in source
    assert '@router.put("/test")' not in source


def test_session_validation_reconciles_middleware_and_canonical_tenant() -> None:
    source = AUTH_ROUTE.read_text(encoding="utf-8")

    assert 'if user_payload["tenant_id"] != middleware_payload["tenant_id"]:' in source
    assert 'detail="Authenticated tenant context is stale"' in source
    assert "Authenticated user no longer exists" in source


def test_chat_ingress_identity_is_server_resolved_and_fail_closed() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    assert "Depends(bypass_user_context_func)" in source
    assert "def _require_execution_identity" in source
    assert 'detail="Authenticated user identity is incomplete"' in source
    assert 'detail="Authenticated tenant context is required"' in source
    assert "ChatExecutionContext(" in source
    assert "tenant_id=tenant_id" in source
    assert 'user.get("tenant_id") or "default"' not in source
    assert 'tenant_id="default"' not in source


def test_missing_tenant_cannot_reach_chat_runtime_through_shared_dependency() -> None:
    dependencies = DEPENDENCIES.read_text(encoding="utf-8")
    chat = CHAT_ROUTE.read_text(encoding="utf-8")

    assert "return _require_identity_scope(UserData.from_dict(user_dict))" in dependencies
    assert "Depends(bypass_user_context_func)" in chat
    assert "_require_execution_identity(user)" in chat


def test_chat_route_contains_no_dead_session_or_stream_compatibility_shims() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    assert "def get_stream_processor" not in source
    assert "def get_chat_orchestrator" not in source
    assert '@router.get("/sessions/{session_id}")' not in source
    assert '@router.delete("/sessions/{session_id}")' not in source


def test_conversation_ingress_never_fabricates_backend_truth() -> None:
    source = CONVERSATION_ROUTE.read_text(encoding="utf-8")

    assert 'id="new-session"' not in source
    assert 'user_id=user_ctx.get("user_id", "anonymous")' not in source
    assert 'return {"success": False, "error": str(e)}' not in source
    assert '"User context: %s"' not in source
    assert "_raise_not_found(" in source


def test_session_activity_is_authenticated_and_tenant_scoped_before_mutation() -> None:
    source = CONVERSATION_ROUTE.read_text(encoding="utf-8")
    start = source.index("async def update_session_activity(")
    end = source.index('\n\n@router.get("/{conversation_id}"', start)
    route_source = source[start:end]

    assert "tenant_id: str = Depends(get_current_tenant_id)" in route_source
    assert "user_ctx: Dict[str, Any] = Depends(bypass_user_context_func)" in route_source
    assert "user_id = _require_user_id(user_ctx)" in route_source
    assert "get_web_ui_conversation_by_session(" in route_source
    assert "tenant_id=tenant_id" in route_source
    assert "user_id=user_id" in route_source
    assert "update_session_activity(" in route_source


def test_static_conversation_get_routes_precede_dynamic_conversation_id_route() -> None:
    source = CONVERSATION_ROUTE.read_text(encoding="utf-8")

    dynamic_index = source.index('@router.get("/{conversation_id}"')
    assert source.index('@router.get("/health")') < dynamic_index
    assert source.index('@router.get("/analytics"') < dynamic_index
    assert source.index('@router.get("/stats")') < dynamic_index
    assert source.index('@router.get("/by-session/{session_id}"') < dynamic_index
