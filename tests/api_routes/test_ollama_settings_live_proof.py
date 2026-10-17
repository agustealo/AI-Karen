"""Regression contracts for the real Ollama Settings-to-runtime smoke harness."""

from __future__ import annotations

import pytest

from scripts.ci.ollama_settings_live_proof import (
    LiveProofError,
    assert_default_runtime_response,
    assert_inventory_matches,
    assert_saved_selection,
    installed_models,
    native_ollama_root,
)


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://host.docker.internal:11434/v1/", "http://host.docker.internal:11434"),
        ("http://ollama:11434/api", "http://ollama:11434"),
    ],
)
def test_ollama_native_inventory_uses_native_api(endpoint: str, expected: str) -> None:
    assert native_ollama_root(endpoint) == expected


@pytest.mark.parametrize("endpoint", [
    "file:///etc/passwd",
    "http://user:secret@localhost:11434",
    "http://localhost:11434/v1?something=1",
])
def test_discovery_probe_rejects_non_endpoint_urls(endpoint: str) -> None:
    with pytest.raises(LiveProofError):
        native_ollama_root(endpoint)


def test_native_inventory_reads_exact_installed_model_ids() -> None:
    assert installed_models({
        "models": [{"name": "smollm2:135m"}, {"model": "qwen2.5:0.5b"}],
    }) == ["smollm2:135m", "qwen2.5:0.5b"]


def test_backend_inventory_must_match_daemon_not_saved_defaults() -> None:
    native = ["smollm2:135m", "qwen2.5:0.5b"]
    assert_inventory_matches(native, {
        "provider": "ollama",
        "models": [
            {"id": "qwen2.5:0.5b", "is_installed": True},
            {"id": "smollm2:135m", "is_installed": True},
        ],
    })
    with pytest.raises(LiveProofError, match="differ"):
        assert_inventory_matches(native, {
            "provider": "ollama",
            "models": [{"id": "saved-default:fake", "is_installed": True}],
        })
    with pytest.raises(LiveProofError, match="unverified"):
        assert_inventory_matches(native, {
            "provider": "ollama",
            "models": [{"id": "smollm2:135m", "is_installed": False}],
        })


def test_settings_round_trip_requires_host_source_and_selected_model() -> None:
    response = {
        "selected_provider": "ollama",
        "selected_model": "smollm2:135m",
        "chat_response_mode": "non_streaming",
        "providers": [{
            "id": "ollama",
            "selected_model": "smollm2:135m",
            "runtime_source": "host",
        }],
    }
    assert_saved_selection(response, "smollm2:135m")
    response["providers"][0]["selected_model"] = "not-installed"
    with pytest.raises(LiveProofError):
        assert_saved_selection(response, "smollm2:135m")


def test_default_runtime_must_not_relabel_fallback_as_ollama_success() -> None:
    good = {
        "content": "Hello!",
        "model": "smollm2:135m",
        "metadata": {
            "actual_provider": "ollama-local",
            "actual_model": "smollm2:135m",
            "response_source": "model",
            "fallback_level": 0,
            "degraded_mode": False,
        },
    }
    assert_default_runtime_response(good, "smollm2:135m")

    for actual_provider, actual_model, fallback_level in (
        ("fallback", "smollm2:135m", 0),
        ("ollama", "a-different-model", 0),
        ("ollama", "smollm2:135m", 1),
    ):
        changed = {
            **good,
            "metadata": {
                **good["metadata"],
                "actual_provider": actual_provider,
                "actual_model": actual_model,
                "fallback_level": fallback_level,
            },
        }
        with pytest.raises(LiveProofError):
            assert_default_runtime_response(changed, "smollm2:135m")
