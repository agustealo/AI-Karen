"""Tests for OpenAICompatibleAdapter."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from unittest.mock import patch, MagicMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "ai_karen_engine"
CORE_MODEL_RUNTIME = SRC / "core" / "model_runtime"


def _load_module(name: str, path: pathlib.Path):
    """Load a module in isolation."""
    numpy_mock = types.ModuleType("numpy")
    sys.modules.setdefault("numpy", numpy_mock)

    pkg_name = "ai_karen_engine.core.model_runtime"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(CORE_MODEL_RUNTIME)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    for parent in ["ai_karen_engine.core", "ai_karen_engine"]:
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
def adapter_module():
    path = CORE_MODEL_RUNTIME / "openai_compatible_adapter.py"
    return _load_module("openai_compatible_adapter_isolated", path)


class TestOpenAICompatibleAdapter:
    def test_create_local_endpoint(self, adapter_module):
        OpenAICompatibleAdapter = adapter_module.OpenAICompatibleAdapter
        RuntimeEngine = adapter_module.RuntimeEngine

        adapter = OpenAICompatibleAdapter(
            target_id="lmstudio-desktop",
            base_url="http://localhost:1234/v1",
            runtime_engine=RuntimeEngine.LMSTUDIO,
        )
        assert adapter.target_id == "lmstudio-desktop"
        assert adapter.base_url == "http://localhost:1234/v1"
        assert adapter.runtime_engine == RuntimeEngine.LMSTUDIO
        assert adapter.kind == adapter_module.EndpointKind.LOCAL_ENDPOINT

    def test_to_inference_target(self, adapter_module):
        OpenAICompatibleAdapter = adapter_module.OpenAICompatibleAdapter
        RuntimeEngine = adapter_module.RuntimeEngine
        CapabilityDescriptor = adapter_module.CapabilityDescriptor

        adapter = OpenAICompatibleAdapter(
            target_id="vllm-prod",
            base_url="http://gpu:8000/v1",
            runtime_engine=RuntimeEngine.VLLM,
            locality=adapter_module.Locality.LAN,
        )
        target = adapter.to_inference_target(
            capabilities=CapabilityDescriptor(chat=True, streaming=True),
            health="healthy",
        )
        assert target.target_id == "vllm-prod"
        assert target.runtime_engine == RuntimeEngine.VLLM
        assert target.locality == adapter_module.Locality.LAN
        assert target.supports_capability("chat") is True

    def test_create_local_endpoint_factory(self, adapter_module):
        create_local_endpoint = adapter_module.create_local_endpoint
        RuntimeEngine = adapter_module.RuntimeEngine

        adapter = create_local_endpoint(
            runtime_engine=RuntimeEngine.OLLAMA,
            base_url="http://localhost:11434/v1",
            target_id="ollama-local",
        )
        assert adapter.target_id == "ollama-local"
        assert adapter.runtime_engine == RuntimeEngine.OLLAMA

    def test_create_cloud_endpoint_factory(self, adapter_module):
        create_cloud_endpoint = adapter_module.create_cloud_endpoint
        RuntimeEngine = adapter_module.RuntimeEngine

        adapter = create_cloud_endpoint(
            runtime_engine=RuntimeEngine.REMOTE_API,
            base_url="https://api.openai.com/v1",
            provider_name="openai",
            target_id="openai-endpoint",
        )
        assert adapter.target_id == "openai-endpoint"
        assert adapter.kind == adapter_module.EndpointKind.CLOUD_PROVIDER
        assert adapter.locality == adapter_module.Locality.CLOUD

    def test_discover_capabilities_success(self, adapter_module):
        OpenAICompatibleAdapter = adapter_module.OpenAICompatibleAdapter
        RuntimeEngine = adapter_module.RuntimeEngine

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "model-chat", "object": "model"},
            ]
        }

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.side_effect = [mock_response, mock_response]

        mock_httpx = MagicMock()
        mock_httpx.Client.return_value = mock_client_instance

        with patch.dict(sys.modules, {"httpx": mock_httpx}):
            adapter = OpenAICompatibleAdapter(
                target_id="test-endpoint",
                base_url="http://localhost:1234/v1",
                runtime_engine=RuntimeEngine.LMSTUDIO,
            )
            caps = adapter.discover_capabilities()
            assert caps.chat is True

    def test_check_health_healthy(self, adapter_module):
        OpenAICompatibleAdapter = adapter_module.OpenAICompatibleAdapter
        RuntimeEngine = adapter_module.RuntimeEngine

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_response

        mock_httpx = MagicMock()
        mock_httpx.Client.return_value = mock_client_instance

        with patch.dict(sys.modules, {"httpx": mock_httpx}):
            adapter = OpenAICompatibleAdapter(
                target_id="test-endpoint",
                base_url="http://localhost:1234/v1",
                runtime_engine=RuntimeEngine.LMSTUDIO,
            )
            health = adapter.check_health()
            assert health == "healthy"

    def test_check_health_unavailable(self, adapter_module):
        OpenAICompatibleAdapter = adapter_module.OpenAICompatibleAdapter
        RuntimeEngine = adapter_module.RuntimeEngine

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.side_effect = Exception("Connection refused")

        mock_httpx = MagicMock()
        mock_httpx.Client.return_value = mock_client_instance

        with patch.dict(sys.modules, {"httpx": mock_httpx}):
            adapter = OpenAICompatibleAdapter(
                target_id="test-endpoint",
                base_url="http://localhost:1234/v1",
                runtime_engine=RuntimeEngine.LMSTUDIO,
            )
            health = adapter.check_health()
            assert health == "unavailable"
