"""Runtime engine taxonomy for inference targets."""
from __future__ import annotations

from enum import Enum


class RuntimeEngine(str, Enum):
    """Canonical runtime engine identifiers."""

    LMSTUDIO = "lmstudio"
    VLLM = "vllm"
    SGLANG = "sglang"
    LLAMACPP = "llamacpp"
    TENSORRTLLM = "tensorrt_llm"
    OLLAMA = "ollama"
    TRANSFORMERS = "transformers"
    REMOTE_API = "remote_api"
    CUSTOM = "custom"


class EndpointKind(str, Enum):
    """Classification of inference target kind."""

    LOCAL_ENDPOINT = "local_endpoint"
    CLOUD_PROVIDER = "cloud_provider"


class EndpointProtocol(str, Enum):
    """Protocol used by an inference endpoint."""

    OPENAI_COMPATIBLE = "openai_compatible"
    NATIVE = "native"


class Locality(str, Enum):
    """Network locality of an inference target."""

    LOCAL = "local"
    LAN = "lan"
    CLOUD = "cloud"
