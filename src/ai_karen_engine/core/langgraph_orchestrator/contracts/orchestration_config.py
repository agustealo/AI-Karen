from dataclasses import dataclass, asdict
from typing import Dict, Any, Set


@dataclass
class LangGraphOrchestrationConfig:
    """Configuration for orchestration system."""

    enable_auth_gate: bool = True
    enable_safety_gate: bool = True
    enable_memory_fetch: bool = True
    enable_approval_gate: bool = False
    streaming_enabled: bool = False
    checkpoint_enabled: bool = True
    max_retries: int = 3
    timeout_seconds: int = 300
    memory_recall_top_k: int = 10

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "LangGraphOrchestrationConfig":
        """Create config from dictionary."""
        allowed_fields = cls.__annotations__.keys()
        filtered_config = {k: v for k, v in config_dict.items() if k in allowed_fields}
        config = cls(**filtered_config)
        config.validate()
        return config

    def to_public_dict(self) -> Dict[str, Any]:
        """Convert to public dictionary (exclude sensitive fields)."""
        return asdict(self)

    @classmethod
    def allowed_update_fields(cls) -> Set[str]:
        """Return set of fields that can be updated."""
        return set(cls.__annotations__.keys())

    def validate(self) -> bool:
        """Validate configuration."""
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if not 1 <= self.memory_recall_top_k <= 50:
            raise ValueError("memory_recall_top_k must be between 1 and 50")
        return True
