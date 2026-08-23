import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "ai_karen_engine"
CORE_MODEL_RUNTIME = SRC / "core" / "model_runtime"


def _load_module(name: str, path: pathlib.Path):
    """Load a module in isolation, mocking heavy dependencies."""
    numpy_mock = types.ModuleType("numpy")
    sys.modules.setdefault("numpy", numpy_mock)

    pkg_name = "ai_karen_engine.core.model_runtime"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(CORE_MODEL_RUNTIME)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    for parent in [
        "ai_karen_engine.core",
        "ai_karen_engine",
    ]:
        if parent not in sys.modules:
            mod = types.ModuleType(parent)
            mod.__path__ = []
            mod.__package__ = parent
            sys.modules[parent] = mod

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def provider_policy_module():
    """Load provider_policy without triggering package __init__."""
    path = CORE_MODEL_RUNTIME / "provider_policy.py"
    return _load_module("provider_policy_isolated", path)


def test_builtin_engines_allowed(provider_policy_module):
    evaluate_provider_policy = provider_policy_module.evaluate_provider_policy
    
    decision = evaluate_provider_policy("vllm")
    assert decision.allowed is True
    assert decision.classification == "builtin_engine"
    
    decision = evaluate_provider_policy("builtin_vllm")
    assert decision.allowed is True
    assert decision.classification == "builtin_engine"

def test_specialized_runtimes(provider_policy_module):
    evaluate_provider_policy = provider_policy_module.evaluate_provider_policy
    
    decision = evaluate_provider_policy("transformers")
    assert decision.allowed is True
    assert decision.classification == "specialized_runtime"
    
    decision = evaluate_provider_policy("builtin_transformers")
    assert decision.allowed is True
    assert decision.classification == "specialized_runtime"

def test_local_openai_endpoints(provider_policy_module):
    evaluate_provider_policy = provider_policy_module.evaluate_provider_policy
    
    # Test allowed when enabled
    decision = evaluate_provider_policy("ollama", local_enabled=True)
    assert decision.allowed is True
    assert decision.classification == "local_openai_endpoint"
    
    decision = evaluate_provider_policy("lm_studio", local_enabled=True)
    assert decision.allowed is True
    assert decision.classification == "local_openai_endpoint"
    
    decision = evaluate_provider_policy("llama_cpp", local_enabled=True)
    assert decision.allowed is True
    assert decision.classification == "local_openai_endpoint"
    
    # Test rejected when disabled
    decision = evaluate_provider_policy("ollama", local_enabled=False)
    assert decision.allowed is False
    assert decision.classification == "local_openai_endpoint"
    assert decision.reason == "local_provider_disabled"

def test_cloud_providers(provider_policy_module):
    evaluate_provider_policy = provider_policy_module.evaluate_provider_policy
    
    # Test allowed when enabled
    decision = evaluate_provider_policy("gemini", external_enabled=True)
    assert decision.allowed is True
    assert decision.classification == "cloud_provider"
    
    decision = evaluate_provider_policy("openai", external_enabled=True)
    assert decision.allowed is True
    assert decision.classification == "cloud_provider"
    
    # Test rejected when disabled
    decision = evaluate_provider_policy("gemini", external_enabled=False)
    assert decision.allowed is False
    assert decision.classification == "cloud_provider"
    assert decision.reason == "external_provider_disabled"

def test_removed_internal_providers_rejected(provider_policy_module):
    evaluate_provider_policy = provider_policy_module.evaluate_provider_policy
    
    removed_providers = [
        "gguf", "local_gguf", "local", "default-model"
    ]
    for p in removed_providers:
        decision = evaluate_provider_policy(p)
        assert decision.allowed is False
        assert decision.classification == "removed_internal_provider"
        assert decision.reason == "removed_internal_provider"

    # llama.cpp is now a local OpenAI-compatible endpoint, not removed
    decision = evaluate_provider_policy("llama_cpp")
    assert decision.allowed is True
    assert decision.classification == "local_openai_endpoint"

def test_normalization(provider_policy_module):
    evaluate_provider_policy = provider_policy_module.evaluate_provider_policy
    
    decision = evaluate_provider_policy("  Vllm  ")
    assert decision.provider == "vllm"
    assert decision.allowed is True
    
    decision = evaluate_provider_policy("llama-cpp")
    assert decision.provider == "llama_cpp"
    assert decision.classification == "local_openai_endpoint"
    
    decision = evaluate_provider_policy("local-gguf")
    assert decision.provider == "local_gguf"
    assert decision.classification == "removed_internal_provider"
