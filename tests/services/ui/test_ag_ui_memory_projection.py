from __future__ import annotations

import pytest

from ai_karen_engine.services.ui import ag_ui_memory_manager as module


@pytest.mark.asyncio
async def test_search_preserves_canonical_recall_order_and_metadata(monkeypatch):
    async def fake_recall_context(**kwargs):
        assert kwargs["tenant_id"] == "tenant-1"
        assert kwargs["user_id"] == "user-1"
        assert kwargs["query"] == "alpha"
        return {
            "results": [
                {
                    "id": "memory-a",
                    "content": "first backend result",
                    "memory_type": "episodic",
                    "similarity_score": 0.42,
                    "timestamp": 100.0,
                    "metadata": {
                        "semantic_cluster": "backend-cluster",
                        "relationships": ["memory-b"],
                    },
                },
                {
                    "id": "memory-b",
                    "content": "second backend result",
                    "timestamp": 200.0,
                    "metadata": {},
                },
            ],
            "source": "neuro_recall",
        }

    monkeypatch.setattr(module, "recall_context", fake_recall_context)
    manager = module.AGUIMemoryManager()

    result = await manager.search_memories(
        {"user_id": "user-1", "tenant_id": "tenant-1"},
        "alpha",
        limit=10,
    )

    assert [item["id"] for item in result] == ["memory-a", "memory-b"]
    assert result[0]["type"] == "episodic"
    assert result[0]["semantic_cluster"] == "backend-cluster"
    assert result[0]["relationships"] == ["memory-b"]
    assert result[0]["confidence"] is None
    assert result[1]["type"] == "unknown"
    assert result[1]["semantic_cluster"] is None
    assert result[1]["relationships"] == []
    assert result[1]["confidence"] is None


@pytest.mark.asyncio
async def test_display_filters_do_not_re_rank_backend_results(monkeypatch):
    async def fake_recall_context(**kwargs):
        return {
            "results": [
                {
                    "id": "first",
                    "content": "first",
                    "memory_type": "fact",
                    "metadata": {"confidence": 0.9},
                },
                {
                    "id": "second",
                    "content": "second",
                    "memory_type": "fact",
                    "metadata": {"confidence": 0.8},
                },
            ]
        }

    monkeypatch.setattr(module, "recall_context", fake_recall_context)
    manager = module.AGUIMemoryManager()

    result = await manager.search_memories(
        {"user_id": "user-1", "tenant_id": "tenant-1"},
        "query",
        filters={"type": "fact", "confidence_min": 0.5},
    )

    assert [item["id"] for item in result] == ["first", "second"]


@pytest.mark.asyncio
async def test_update_delegates_without_ui_generated_cognitive_metadata(monkeypatch):
    captured = {}

    async def fake_update_memory(*, memory_id, updates, user_ctx):
        captured["memory_id"] = memory_id
        captured["updates"] = updates
        captured["user_ctx"] = user_ctx
        return {"status": "success"}

    monkeypatch.setattr(module, "update_memory", fake_update_memory)
    manager = module.AGUIMemoryManager()
    user_ctx = {"user_id": "user-1", "tenant_id": "tenant-1"}

    success = await manager.update_memory_with_metadata(
        user_ctx,
        "memory-1",
        {"content": "updated"},
        {"source": "editor"},
    )

    assert success is True
    assert captured["memory_id"] == "memory-1"
    assert captured["updates"]["metadata"] == {"source": "editor"}
    assert "ag_ui_type" not in captured["updates"]
    assert "confidence" not in captured["updates"]
    assert captured["user_ctx"] == user_ctx


def test_module_has_no_cognitive_nlp_or_ranking_dependencies():
    source = module.__file__
    assert source is not None

    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()

    forbidden = (
        "SpacyService",
        "DistilBertService",
        "_classify_memory_type",
        "_calculate_semantic_similarity",
        "_rank_search_results",
        "_get_semantic_relationships",
    )
    for token in forbidden:
        assert token not in text
