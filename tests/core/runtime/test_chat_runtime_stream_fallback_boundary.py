"""A streamed response may recover only before content reaches the client."""

from __future__ import annotations

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


@pytest.mark.parametrize(
    ("streamed_text", "expected"),
    [
        ("", True),
        ("Hello", False),
        (" ", False),
        ("\n", False),
        ("Partial answer from original provider", False),
    ],
)
def test_fallback_requires_zero_emitted_content(
    streamed_text: str, expected: bool,
) -> None:
    assert ChatRuntime._can_recover_stream_with_fallback(streamed_text) is expected
