from __future__ import annotations

from contextlib import nullcontext

from ai_karen_engine.core.runtime.soft_reasoning_token import (
    DEFAULT_SOFT_REASONING_MARKER,
    SoftReasoningTokenManager,
)


class FakeTokenizer:
    unk_token_id = 0

    def __init__(self, *, existing: bool = False) -> None:
        self._vocab = {"<unk>": 0, "hello": 1}
        if existing:
            self._vocab[DEFAULT_SOFT_REASONING_MARKER] = 2
        self.add_calls = 0

    def convert_tokens_to_ids(self, token: str) -> int:
        return self._vocab.get(token, self.unk_token_id)

    def get_vocab(self) -> dict[str, int]:
        return dict(self._vocab)

    def add_special_tokens(self, payload: dict[str, list[str]]) -> int:
        self.add_calls += 1
        added = 0
        for token in payload["additional_special_tokens"]:
            if token not in self._vocab:
                self._vocab[token] = len(self._vocab)
                added += 1
        return added

    def __len__(self) -> int:
        return len(self._vocab)


class FakeModel:
    def __init__(self) -> None:
        self.resize_calls: list[int] = []

    def resize_token_embeddings(self, size: int) -> None:
        self.resize_calls.append(size)


class FakeRuntime:
    def __init__(self, *, existing: bool = False) -> None:
        self.model = FakeModel()
        self.tokenizer = FakeTokenizer(existing=existing)

    def generation_components(self):
        return self.model, self.tokenizer, nullcontext()


def test_marker_manager_adds_and_resizes_exactly_once() -> None:
    runtime = FakeRuntime()
    manager = SoftReasoningTokenManager()

    first = manager.ensure(runtime)
    second = manager.ensure(runtime)

    assert first.token == DEFAULT_SOFT_REASONING_MARKER
    assert first.token_id == second.token_id
    assert first.vocabulary_resized is True
    assert second.vocabulary_resized is False
    assert runtime.tokenizer.add_calls == 1
    assert runtime.model.resize_calls == [len(runtime.tokenizer)]


def test_marker_manager_reuses_existing_vocab_without_model_mutation() -> None:
    runtime = FakeRuntime(existing=True)

    marker = SoftReasoningTokenManager().ensure(runtime)

    assert marker.token_id == 2
    assert marker.vocabulary_resized is False
    assert runtime.tokenizer.add_calls == 0
    assert runtime.model.resize_calls == []
