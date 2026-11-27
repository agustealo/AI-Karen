import pytest


class _RuntimeStub:
    def __init__(self):
        self.calls = 0

    async def get_orchestrator(self):
        self.calls += 1
        return object()


@pytest.mark.asyncio
async def test_runtime_route_uses_canonical_runtime_entrypoint(monkeypatch):
    from ai_karen_engine.api_routes.chat import runtime as runtime_route

    stub = _RuntimeStub()
    monkeypatch.setattr(runtime_route, "get_chat_runtime_service", lambda: stub)

    result = await runtime_route.get_chat_orchestrator()
    assert result is not None
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_websocket_diagnostics_do_not_construct_unowned_gateway():
    import json

    from ai_karen_engine.api_routes.chat import websocket as websocket_route

    assert not hasattr(websocket_route, "get_websocket_gateway")
    user = {"user_id": "user-1", "tenant_id": "tenant-1", "roles": ["admin"]}
    response = await websocket_route.get_websocket_stats(user=user)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body)["error_code"] == "COLLABORATION_TRANSPORT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_copilot_route_uses_canonical_runtime_entrypoint(monkeypatch):
    from ai_karen_engine.api_routes.chat import copilot as copilot_route

    stub = _RuntimeStub()
    monkeypatch.setattr(copilot_route, "get_chat_runtime_service", lambda: stub)

    result = await copilot_route._get_chat_orchestrator()
    assert result is not None
    assert stub.calls == 1
