from __future__ import annotations

from typing import Any

from ai_karen_engine.core.reasoning.soft_reasoning.engine import (
    SoftReasoningEngine,
    WritebackConfig,
)


class FakeEmbeddings:
    def embed(self, text: str) -> list[float]:
        return [float(len(text) or 1), 1.0]


class FakeStore:
    def __init__(self) -> None:
        self.raise_on_search = False
        self.search_scores: dict[str, float] = {}
        self.upserts: list[dict[str, Any]] = []

    def upsert(self, vector: list[float], payload: dict[str, Any]) -> int:
        self.upserts.append(payload)
        return len(self.upserts)

    def batch_upsert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> list[int]:
        self.upserts.extend(payloads)
        return list(range(100, 100 + len(payloads)))

    def search(
        self,
        vector: list[float],
        *,
        top_k: int = 10,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        del top_k, metadata_filter
        if self.raise_on_search:
            raise RuntimeError("backend unavailable")
        text_length = int(vector[0])
        score = self.search_scores.get(str(text_length), 0.0)
        return [{"id": "existing", "score": score, "payload": {}}]

    def delete(self, ids) -> None:
        del ids

    def count(self) -> int:
        return len(self.upserts)


def _engine(store: FakeStore) -> SoftReasoningEngine:
    return SoftReasoningEngine(
        store=store,
        embeddings=FakeEmbeddings(),
        writeback=WritebackConfig(novelty_gate=0.18, importance_gate=0.30),
    )


def test_writeback_config_accepts_importance_gate() -> None:
    config = WritebackConfig(importance_gate=0.42)
    assert config.importance_gate == 0.42


def test_novelty_backend_failure_rejects_writeback() -> None:
    store = FakeStore()
    store.raise_on_search = True
    engine = _engine(store)

    result = engine.ingest("must-not-write")

    assert result is None
    assert store.upserts == []


def test_force_write_explicitly_bypasses_novelty_failure() -> None:
    store = FakeStore()
    store.raise_on_search = True
    engine = _engine(store)

    result = engine.ingest("explicit-write", force=True)

    assert result == 1
    assert [item["text"] for item in store.upserts] == ["explicit-write"]


def test_batch_ids_preserve_original_item_indexes() -> None:
    store = FakeStore()
    # len("duplicate") == 9. A score of 0.95 gives entropy 0.05 and is rejected.
    store.search_scores["9"] = 0.95
    engine = _engine(store)

    results = engine.batch_ingest(
        [
            ("duplicate", {"slot": 0}),
            ("novel-item", {"slot": 1}),
            ("", {"slot": 2}),
            ("another-novel", {"slot": 3}),
        ]
    )

    assert results == [None, 100, None, 101]
    assert [item["slot"] for item in store.upserts] == [1, 3]
