import pytest

import ai_karen_engine.core.memory.projections.memory_graph_worker as worker_module


class _GraphService:
    def __init__(self):
        self.calls = []

    async def project_memory_event(self, **kwargs):
        self.calls.append(kwargs)
        return True


@pytest.mark.asyncio
async def test_memory_graph_worker_delegates_without_owning_storage(monkeypatch):
    service = _GraphService()
    monkeypatch.setattr(worker_module, "get_leangraph_service", lambda: service)

    worker = worker_module.MemoryGraphWorker()
    event = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "00000000-0000-0000-0000-000000000003",
        "payload": {},
    }

    assert await worker.project(event, None) is True
    assert service.calls == [{"event_data": event, "assertion_data": None}]
