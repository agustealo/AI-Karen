"""Tests for the new inference target abstractions."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

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
def runtime_engine_module():
    path = CORE_MODEL_RUNTIME / "runtime_engine.py"
    return _load_module("runtime_engine_isolated", path)


@pytest.fixture(scope="module")
def inference_target_module():
    path = CORE_MODEL_RUNTIME / "inference_target.py"
    return _load_module("inference_target_isolated", path)


@pytest.fixture(scope="module")
def deployment_profile_module():
    path = CORE_MODEL_RUNTIME / "deployment_profile.py"
    return _load_module("deployment_profile_isolated", path)


class TestRuntimeEngine:
    def test_engine_values(self, runtime_engine_module):
        RuntimeEngine = runtime_engine_module.RuntimeEngine
        assert RuntimeEngine.LMSTUDIO == "lmstudio"
        assert RuntimeEngine.VLLM == "vllm"
        assert RuntimeEngine.SGLANG == "sglang"
        assert RuntimeEngine.LLAMACPP == "llamacpp"
        assert RuntimeEngine.OLLAMA == "ollama"
        assert RuntimeEngine.TRANSFORMERS == "transformers"

    def test_endpoint_kind_values(self, runtime_engine_module):
        EndpointKind = runtime_engine_module.EndpointKind
        assert EndpointKind.LOCAL_ENDPOINT == "local_endpoint"
        assert EndpointKind.CLOUD_PROVIDER == "cloud_provider"

    def test_locality_values(self, runtime_engine_module):
        Locality = runtime_engine_module.Locality
        assert Locality.LOCAL == "local"
        assert Locality.LAN == "lan"
        assert Locality.CLOUD == "cloud"


class TestInferenceTarget:
    def test_create_target(self, inference_target_module):
        InferenceTarget = inference_target_module.InferenceTarget
        CapabilityDescriptor = inference_target_module.CapabilityDescriptor
        RuntimeEngine = inference_target_module.RuntimeEngine
        EndpointKind = inference_target_module.EndpointKind
        EndpointProtocol = inference_target_module.EndpointProtocol
        Locality = inference_target_module.Locality

        target = InferenceTarget(
            target_id="lmstudio-desktop",
            kind=EndpointKind.LOCAL_ENDPOINT,
            protocol=EndpointProtocol.OPENAI_COMPATIBLE,
            provider_name="local",
            runtime_engine=RuntimeEngine.LMSTUDIO,
            base_url="http://localhost:1234/v1",
            locality=Locality.LOCAL,
            capabilities=CapabilityDescriptor(chat=True, streaming=True, tools=True),
        )
        assert target.target_id == "lmstudio-desktop"
        assert target.kind == EndpointKind.LOCAL_ENDPOINT
        assert target.protocol == EndpointProtocol.OPENAI_COMPATIBLE
        assert target.runtime_engine == RuntimeEngine.LMSTUDIO
        assert target.supports_capability("chat") is True
        assert target.supports_capability("streaming") is True
        assert target.supports_capability("vision") is False

    def test_target_to_dict(self, inference_target_module):
        InferenceTarget = inference_target_module.InferenceTarget
        CapabilityDescriptor = inference_target_module.CapabilityDescriptor
        RuntimeEngine = inference_target_module.RuntimeEngine
        EndpointKind = inference_target_module.EndpointKind
        EndpointProtocol = inference_target_module.EndpointProtocol
        Locality = inference_target_module.Locality

        target = InferenceTarget(
            target_id="vllm-prod",
            kind=EndpointKind.LOCAL_ENDPOINT,
            protocol=EndpointProtocol.OPENAI_COMPATIBLE,
            provider_name="local",
            runtime_engine=RuntimeEngine.VLLM,
            base_url="http://gpu-server:8000/v1",
            locality=Locality.LAN,
            capabilities=CapabilityDescriptor(chat=True, streaming=True),
        )
        data = target.to_dict()
        assert data["target_id"] == "vllm-prod"
        assert data["runtime_engine"] == "vllm"
        assert data["locality"] == "lan"
        assert data["capabilities"]["chat"] is True


class TestDeploymentProfile:
    def test_desktop_local_profile(self, deployment_profile_module):
        DeploymentProfile = deployment_profile_module.DeploymentProfile
        RuntimeEngine = deployment_profile_module.RuntimeEngine
        profile = deployment_profile_module.DESKTOP_LOCAL

        assert profile.name == "desktop_local"
        assert RuntimeEngine.LMSTUDIO in profile.preferred_engines
        assert RuntimeEngine.TRANSFORMERS in profile.excluded_engines
        assert profile.is_engine_allowed(RuntimeEngine.LMSTUDIO) is True
        assert profile.is_engine_allowed(RuntimeEngine.TRANSFORMERS) is False

    def test_gpu_server_profile(self, deployment_profile_module):
        DeploymentProfile = deployment_profile_module.DeploymentProfile
        RuntimeEngine = deployment_profile_module.RuntimeEngine
        profile = deployment_profile_module.GPU_SERVER

        assert profile.name == "gpu_server"
        assert RuntimeEngine.VLLM in profile.preferred_engines
        assert RuntimeEngine.LMSTUDIO in profile.excluded_engines
        assert profile.allow_external is True

    def test_offline_profile(self, deployment_profile_module):
        DeploymentProfile = deployment_profile_module.DeploymentProfile
        RuntimeEngine = deployment_profile_module.RuntimeEngine
        profile = deployment_profile_module.OFFLINE

        assert profile.allow_external is False
        assert RuntimeEngine.OLLAMA in profile.preferred_engines

    def test_get_deployment_profile(self, deployment_profile_module):
        profile = deployment_profile_module.get_deployment_profile("desktop_local")
        assert profile is not None
        assert profile.name == "desktop_local"

        profile = deployment_profile_module.get_deployment_profile("nonexistent")
        assert profile is None

    def test_get_default_profile(self, deployment_profile_module):
        profile = deployment_profile_module.get_default_profile()
        assert profile.name == "desktop_local"
