import uuid

import pytest

from ai_karen_engine.core.memory.retrieval.retrieval_router import HybridRetrievalRouter
from ai_karen_engine.core.memory.types import MemoryQuery
from ai_karen_engine.platform.memory.postgres.entity_resolver import ResolvedEntity


class _Resolver:
    async def resolve_cues(self, **kwargs):
        return [
            ResolvedEntity(
                entity_id=str(uuid.uuid4()),
                canonical_text="Supabase",
                matched_text="Supabase",
                match_type="exact",
                score=1.0,
            )
        ]


class _Graph:
    def __init__(self, event_id):
        self.event_id = event_id
        self.seen = []

    async def get_entity_context(self, **kwargs):
        self.seen.append(kwargs["entity_text"])
        if kwargs["entity_text"] != "Supabase":
            return []
        return [
            {
                "event_id": self.event_id,
                "relationship": "MENTIONS",
                "depth": 1,
                "path": ["entity", self.event_id],
            }
        ]


class _Events:
    def __init__(self, event_id, *, include=True):
        self.event_id = event_id
        self.include = include

    async def fetch_many(self, **kwargs):
        if not self.include:
            return {}
        return {
            self.event_id: {
                "event_id": self.event_id,
                "event_type": "memory_persisted",
                "payload": {"summary": "We chose Supabase as the durable memory platform."},
                "confidence": 0.95,
                "created_at": None,
                "valid_from": None,
                "valid_to": None,
                "source_type": "conversation",
                "source_ref": "message-1",
            }
        }


def _router(event_id, *, include_event=True):
    router = object.__new__(HybridRetrievalRouter)
    router.entity_resolver = _Resolver()
    router.leangraph = _Graph(event_id)
    router.event_source = _Events(event_id, include=include_event)
    return router


@pytest.mark.asyncio
async def test_graph_hit_expands_to_canonical_event_content():
    event_id = str(uuid.uuid4())
    router = _router(event_id)
    query = MemoryQuery(
        text="Why did we choose Supabase?",
        tenant_id="tenant-1",
        user_id="user-1",
        top_k=5,
    )

    entries = await router._query_graph(query)

    assert len(entries) == 1
    assert entries[0].id == event_id
    assert entries[0].content == "We chose Supabase as the durable memory platform."
    provenance = entries[0].metadata.custom["provenance"]
    assert provenance["record_type"] == "memory_event"
    assert provenance["graph_relationship"] == "MENTIONS"
    assert provenance["matched_entity_cue"] == "Supabase"
    assert provenance["entity_resolution"]["match_type"] == "exact"


@pytest.mark.asyncio
async def test_graph_path_without_governed_source_does_not_create_pseudo_memory():
    event_id = str(uuid.uuid4())
    router = _router(event_id, include_event=False)
    query = MemoryQuery(
        text="Why did we choose Supabase?",
        tenant_id="tenant-1",
        user_id="user-1",
        top_k=5,
    )

    assert await router._query_graph(query) == []
