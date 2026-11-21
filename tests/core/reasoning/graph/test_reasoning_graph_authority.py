"""KIS-GRAPH-01C2J: legacy reasoning cannot publish unscoped memory graphs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.reasoning.graph import reasoning


class _FakeICE:
    def __init__(self, **kwargs):
        self.calls = []

    def process(self, text, *, metadata=None):
        self.calls.append((text, metadata))
        return SimpleNamespace(
            memory_matches=[{
                "payload": {"text": "private memory across a source revocation"},
                "score": 0.99,
            }],
            entropy=0.1,
            top_score=0.99,
        )


def test_explicit_legacy_mirroring_is_denied_before_initialization():
    with pytest.raises(ValueError, match="Legacy reasoning graph mirroring is disabled"):
        reasoning.ReasoningGraph(
            llm=object(), engine=object(), enable_graph_mirroring=True,
        )


def test_reasoning_preserves_inference_without_unscoped_graph(monkeypatch):
    monkeypatch.setattr(reasoning, "PremiumICEWrapper", _FakeICE)
    instance = reasoning.ReasoningGraph(llm=object(), engine=object())
    first = instance.run("tenant A request", metadata={"tenant_id": "tenant-a"})
    second = instance.run("tenant B request", metadata={"tenant_id": "tenant-b"})

    assert len(first.memory_matches) == 1
    assert len(second.memory_matches) == 1
    assert instance._ice.calls == [
        ("tenant A request", {"tenant_id": "tenant-a"}),
        ("tenant B request", {"tenant_id": "tenant-b"}),
    ]
    assert instance.capsule_graph is None
    assert instance.visualize_capsule_cli() is None
    assert instance.capsule_dot() is None
    assert not hasattr(instance, "_capsule_graph")


@pytest.mark.asyncio
async def test_async_reasoning_does_not_retain_memory_graph(monkeypatch):
    monkeypatch.setattr(reasoning, "PremiumICEWrapper", _FakeICE)
    instance = reasoning.ReasoningGraph(llm=object(), engine=object())
    result = await instance.arun(
        "tenant A request", metadata={"tenant_id": "tenant-a"},
    )
    assert result.memory_matches[0]["payload"]["text"].startswith("private memory")
    assert instance.capsule_graph is None
    assert instance.visualize_capsule_cli() is None
    assert instance.capsule_dot() is None
