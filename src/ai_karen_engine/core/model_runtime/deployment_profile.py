"""Deployment profiles for inference target selection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ai_karen_engine.core.model_runtime.runtime_engine import RuntimeEngine


@dataclass(frozen=True)
class DeploymentProfile:
    """Deployment profile configuration.

    Profiles define preferred inference targets for different environments.
    """

    name: str
    description: str
    preferred_engines: List[RuntimeEngine]
    optional_engines: List[RuntimeEngine] = field(default_factory=list)
    excluded_engines: List[RuntimeEngine] = field(default_factory=list)
    default_locality: str = "local"
    allow_external: bool = False
    max_fallback_attempts: int = 3

    def is_engine_allowed(self, engine: RuntimeEngine) -> bool:
        """Check if an engine is allowed by this profile."""
        if engine in self.excluded_engines:
            return False
        return True

    def engine_priority(self, engine: RuntimeEngine) -> int:
        """Return priority for an engine (lower = preferred)."""
        try:
            return self.preferred_engines.index(engine)
        except ValueError:
            pass
        try:
            return len(self.preferred_engines) + self.optional_engines.index(engine)
        except ValueError:
            return 999


# Canonical deployment profiles
DESKTOP_LOCAL = DeploymentProfile(
    name="desktop_local",
    description="Developer desktop with LM Studio as primary local manager",
    preferred_engines=[RuntimeEngine.LMSTUDIO, RuntimeEngine.LLAMACPP],
    optional_engines=[RuntimeEngine.OLLAMA],
    excluded_engines=[RuntimeEngine.TRANSFORMERS],
    default_locality="local",
    allow_external=False,
    max_fallback_attempts=2,
)

HEADLESS_LOCAL = DeploymentProfile(
    name="headless_local",
    description="Headless local server without GUI model manager",
    preferred_engines=[RuntimeEngine.LLAMACPP, RuntimeEngine.VLLM],
    optional_engines=[RuntimeEngine.SGLANG, RuntimeEngine.OLLAMA],
    excluded_engines=[RuntimeEngine.TRANSFORMERS, RuntimeEngine.TENSORRTLLM],
    default_locality="local",
    allow_external=False,
    max_fallback_attempts=2,
)

GPU_SERVER = DeploymentProfile(
    name="gpu_server",
    description="Production GPU server with high-throughput serving",
    preferred_engines=[RuntimeEngine.VLLM, RuntimeEngine.SGLANG],
    optional_engines=[RuntimeEngine.TENSORRTLLM],
    excluded_engines=[RuntimeEngine.LMSTUDIO, RuntimeEngine.TRANSFORMERS],
    default_locality="local",
    allow_external=True,
    max_fallback_attempts=3,
)

HYBRID = DeploymentProfile(
    name="hybrid",
    description="Mixed local and cloud deployment",
    preferred_engines=[RuntimeEngine.LMSTUDIO, RuntimeEngine.VLLM, RuntimeEngine.SGLANG],
    optional_engines=[RuntimeEngine.LLAMACPP, RuntimeEngine.OLLAMA],
    excluded_engines=[RuntimeEngine.TRANSFORMERS],
    default_locality="local",
    allow_external=True,
    max_fallback_attempts=3,
)

OFFLINE = DeploymentProfile(
    name="offline",
    description="Fully offline operation, no external targets",
    preferred_engines=[RuntimeEngine.LMSTUDIO, RuntimeEngine.LLAMACPP, RuntimeEngine.OLLAMA],
    optional_engines=[RuntimeEngine.VLLM, RuntimeEngine.SGLANG],
    excluded_engines=[RuntimeEngine.TRANSFORMERS],
    default_locality="local",
    allow_external=False,
    max_fallback_attempts=2,
)

PROFILES: dict[str, DeploymentProfile] = {
    "desktop_local": DESKTOP_LOCAL,
    "headless_local": HEADLESS_LOCAL,
    "gpu_server": GPU_SERVER,
    "hybrid": HYBRID,
    "offline": OFFLINE,
}


def get_deployment_profile(name: str) -> Optional[DeploymentProfile]:
    """Get a deployment profile by name."""
    return PROFILES.get(name)


def get_default_profile() -> DeploymentProfile:
    """Get the default deployment profile."""
    return DESKTOP_LOCAL
