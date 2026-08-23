from ai_karen_engine.core.errors.response_validation import validate_response_text


def test_reject_prompt_leakage_patterns():
    assert not validate_response_text('[transformers:auto] You are Karen...')
    assert not validate_response_text('Assistant: hello')
    assert not validate_response_text('Answer only the user\'s latest message...')


def test_reject_raw_tool_json_by_default():
    assert not validate_response_text('{"tool_name":"search","arguments":{"q":"x"}}')


def test_accept_normal_text():
    assert validate_response_text('Here is the answer to your question.')
