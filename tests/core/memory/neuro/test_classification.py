from ai_karen_engine.core.memory.neuro.classification import classify_memory_candidate
from ai_karen_engine.core.memory.neuro.contracts import MemoryCandidate, MemoryClass


def _candidate(text: str, *, source: str = "conversation", metadata=None):
    return MemoryCandidate(
        id="1",
        text=text,
        memory_class=MemoryClass.EPISODIC,
        source=source,
        tenant_id="t",
        user_id="u",
        metadata=metadata or {},
    )


def test_semantic_fact_classification():
    assert classify_memory_candidate(_candidate("My favorite color is green")) is MemoryClass.SEMANTIC


def test_declared_procedural_class_wins_over_text_heuristic():
    candidate = _candidate(
        "opaque procedure payload",
        metadata={"memory_class": "procedural"},
    )
    assert classify_memory_candidate(candidate) is MemoryClass.PROCEDURAL


def test_redis_candidates_are_stm():
    assert classify_memory_candidate(_candidate("current session context", source="redis")) is MemoryClass.STM
