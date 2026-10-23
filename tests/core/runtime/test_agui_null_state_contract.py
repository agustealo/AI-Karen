"""AG-UI initial state compatibility without weakening ingress policy."""

import pytest
from pydantic import ValidationError

from ai_karen_engine.api_routes.chat.runtime import AGUIRunRequest


def _run(**overrides):
    data = {
        "threadId": "conversation-123",
        "runId": "run-123",
        "messages": [{"role": "user", "content": "Hello Karen"}],
    }
    data.update(overrides)
    return AGUIRunRequest.model_validate(data)


def test_null_initial_state_normalizes_to_empty_dictionary():
    assert _run(state=None).state == {}


def test_omitted_initial_state_is_empty():
    assert _run().state == {}


def test_empty_dictionary_is_accepted():
    assert _run(state={}).state == {}


def test_nonempty_state_remains_visible_to_authorization_gate():
    assert _run(state={"unauthorized": True}).state == {"unauthorized": True}


@pytest.mark.parametrize("value", [[], "null", 0, False, [1]])
def test_non_dictionary_state_still_fails_validation(value):
    with pytest.raises(ValidationError):
        _run(state=value)
