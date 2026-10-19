"""Offline contract tests for the genuine, optional local tool-call proof.

All provider replies here are *test fixtures*. They never satisfy the live
model activation gate; that gate must run on the configured self-hosted model.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import deepagents_live_tool_smoke as proof


def _real_call(nonce: str):
    return {
        "id": "real-provider-issued-id-1",
        "type": "function",
        "function": {
            "name": "karen_readonly_probe",
            "arguments": '{"nonce":"' + nonce + '"}',
        },
    }


def test_accepts_structured_tool_call_and_actual_provider_id():
    call_id, name, args = proof._extract_real_call(
        {"role": "assistant", "tool_calls": [_real_call("probe-a")]},
        "probe-a",
    )
    assert call_id == "real-provider-issued-id-1"
    assert name == "karen_readonly_probe"
    assert args == {"nonce": "probe-a"}


@pytest.mark.parametrize("message,reason", [
    ({"content": "I would call a tool if one existed"}, "exactly one"),
    ({"tool_calls": []}, "exactly one"),
    ({"tool_calls": [{"id": "call", "type": "function",
                     "function": {"name": "wrong", "arguments": "{}"}}]},
     "unregistered"),
    ({"tool_calls": [{"id": "call", "type": "function",
                     "function": {"name": "karen_readonly_probe",
                                  "arguments": "not-json"}}]},
     "malformed"),
    ({"tool_calls": [{"id": "call", "type": "function",
                     "function": {"name": "karen_readonly_probe",
                                  "arguments": "{}"}}]},
     "nonce"),
])
def test_rejects_fabricated_plain_text_or_wrong_tool_identity(message, reason):
    with pytest.raises(RuntimeError, match=reason):
        proof._extract_real_call(message, "test-nonce")


def test_rejects_external_targets_and_embedded_credentials():
    for target in [
        "https://example.org/v1",
        "http://models.example.org/v1",
        "http://username:password@localhost:11434/v1",
    ]:
        with pytest.raises(RuntimeError, match="local|authenticated"):
            proof._require_local_target(target, allow_private_hostname=False)
    proof._require_local_target(
        "http://127.0.0.1:11434/v1", allow_private_hostname=False
    )


def test_local_smoke_uses_live_tool_wire_roundtrip_without_executing_tool(monkeypatch):
    nonce = "test-generated-nonce"
    monkeypatch.setenv("BETA_MODEL_PROVIDER", "registered-local-provider")
    monkeypatch.setattr(
        proof.SmokeConfig, "from_environment",
        lambda: SimpleNamespace(
            base_url="http://localhost:11434/v1",
            model="registered-local-model",
            api_key=None,
            timeout_seconds=30,
        ),
    )
    monkeypatch.setattr(proof.secrets, "token_hex", lambda size: nonce)
    captured = []

    def local_http(url, *, method, api_key, body, timeout_seconds):
        del method, api_key, timeout_seconds
        captured.append((url, body))
        if len(captured) == 1:
            return 200, {
                "model": "registered-local-model",
                "choices": [{"message": {
                    "role": "assistant", "content": "",
                    "tool_calls": [_real_call(nonce)],
                }}],
            }, 14.0
        return 200, {
            "model": "registered-local-model",
            "choices": [{"message": {
                "role": "assistant",
                "content": "VERIFIED_" + nonce,
            }}],
        }, 14.0

    monkeypatch.setattr(proof, "_request_json", local_http)
    result = proof.run()
    assert result.reply_verified
    assert result.provider == "registered-local-provider"
    assert result.model == "registered-local-model"
    assert len(captured) == 2
    assert captured[0][1]["tools"][0]["function"]["name"] == "karen_readonly_probe"
    assert captured[1][1]["messages"][-2] == {
        "role": "tool",
        "tool_call_id": "real-provider-issued-id-1",
        "content": '{"probe": "ok", "nonce": "test-generated-nonce"}',
    }
    assert result.public_summary()["external_tool_executed"] is False


def test_live_proof_fails_if_provider_changes_model(monkeypatch):
    monkeypatch.setattr(
        proof.SmokeConfig, "from_environment",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:11434/v1",
            model="selected-model",
            api_key=None,
            timeout_seconds=30,
        ),
    )
    monkeypatch.setenv("BETA_MODEL_PROVIDER", "registered-local-provider")
    monkeypatch.setattr(
        proof, "_request_json",
        lambda *args, **kwargs: (
            200, {"model": "different-model",
                  "choices": [{"message": {"role": "assistant", "content": "hi"}}]},
            1.0,
        ),
    )
    with pytest.raises(RuntimeError, match="changed model identity"):
        proof.run()


def test_live_proof_requires_explicit_selected_model(monkeypatch):
    monkeypatch.setenv("BETA_MODEL_PROVIDER", "registered-local-provider")
    monkeypatch.setattr(
        proof.SmokeConfig, "from_environment",
        lambda: SimpleNamespace(
            base_url="http://localhost:11434/v1",
            model=None,
            api_key=None,
            timeout_seconds=30,
        ),
    )
    with pytest.raises(RuntimeError, match="explicit provider and model"):
        proof.run()
