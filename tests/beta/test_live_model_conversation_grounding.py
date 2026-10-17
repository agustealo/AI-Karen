"""Live provider conversational grounding acceptance-contract tests."""

import pytest

from scripts.beta_live_model_smoke import _assert_grounded_name_answer


@pytest.mark.parametrize("answer", ["Zeus", "The name you gave is Zeus.", "You said Zeus."])
def test_grounded_personal_fact_is_accepted(answer: str) -> None:
    _assert_grounded_name_answer(answer, "Zeus")


@pytest.mark.parametrize(
    "answer",
    [
        "",
        "I do not know your name.",
        "Your name is Zeph.",
        "Zeus is a mythological figure. " + "Unrelated detail. " * 30,
    ],
)
def test_ungrounded_or_unfocused_answers_fail(answer: str) -> None:
    with pytest.raises(RuntimeError):
        _assert_grounded_name_answer(answer, "Zeus")
