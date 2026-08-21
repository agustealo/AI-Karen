from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class EngineConfig:
    enabled: bool = True
    type: str = "builtin_provider_engine"
    fallback_eligible: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    note: str | None = None
    base_url: str | None = None


@dataclass(slots=True)
class ExpressionPolicyConfig:
    allow_third_party_engines: bool = True
    allow_external_engines: bool = False
    require_admin_for_external: bool = True
    default_timeout_ms: int = 30000


@dataclass(slots=True)
class ExpressionSettings:
    active_engine: str = "builtin"
    engines: dict[str, EngineConfig] = field(
        default_factory=lambda: {
            "builtin": EngineConfig(enabled=True, type="builtin_provider_engine", fallback_eligible=True),
            "local": EngineConfig(enabled=True, type="openai_compatible", fallback_eligible=True),
            "cloud": EngineConfig(enabled=False, type="openai_compatible", fallback_eligible=True),
        }
    )
    policies: ExpressionPolicyConfig = field(default_factory=ExpressionPolicyConfig)
    engine_fallback_order: list[str] = field(default_factory=lambda: ["builtin", "local", "cloud"])
    local_first_mode: bool = True
    provider_fallback_policy: str = "ordered"
    third_party_endpoint_url: str | None = None

    @classmethod
    def load_from_config(cls) -> ExpressionSettings:
        """Loads expression settings from the global config manager."""
        try:
            from ai_karen_engine.config.config_manager import config_manager
            
            # Get the expression block from config
            expr_cfg = config_manager.get_config_value("expression", default={})
            print(f"DEBUG: Loaded expr_cfg: {expr_cfg}")
            
            settings = cls()
            if not expr_cfg:
                return settings
                
            settings.active_engine = expr_cfg.get("active_engine", settings.active_engine)
            settings.engine_fallback_order = expr_cfg.get("fallback_order", settings.engine_fallback_order)
            settings.local_first_mode = expr_cfg.get("local_first_mode", settings.local_first_mode)
            
            # Update granular engine configuration
            persistent_engines = expr_cfg.get("engines", {})
            enabled_engines = expr_cfg.get("enabled_engines", [])
            
            # 1. Update existing engines and add new ones from persistent_engines
            from ai_karen_engine.core.model_runtime.provider_policy import evaluate_provider_policy
            
            for engine_id, p_cfg in persistent_engines.items():
                if engine_id not in settings.engines:
                    # Determine type based on policy
                    decision = evaluate_provider_policy(engine_id)
                    engine_type = "openai_compatible"
                    if decision.classification == "builtin_engine":
                        engine_type = "builtin_provider_engine"
                    
                    # Add new engine from config
                    settings.engines[engine_id] = EngineConfig(
                        enabled=p_cfg.get("enabled", True),
                        type=p_cfg.get("type", engine_type),
                        fallback_eligible=p_cfg.get("fallback_eligible", True),
                        metadata=p_cfg.get("metadata", {}),
                    )
                else:
                    # Update existing engine
                    engine_cfg = settings.engines[engine_id]
                    engine_cfg.enabled = p_cfg.get("enabled", engine_cfg.enabled)
                    engine_cfg.fallback_eligible = p_cfg.get("fallback_eligible", engine_cfg.fallback_eligible)
                    engine_cfg.metadata = p_cfg.get("metadata") or engine_cfg.metadata
            
            print(f"DEBUG: Engines after loop 1: {[(k, e.enabled) for k, e in settings.engines.items()]}")

            # 2. Process legacy enabled_engines list and builtin defaults
            if "enabled_engines" in expr_cfg:
                for engine_id, engine_cfg in settings.engines.items():
                    if engine_id in enabled_engines:
                        engine_cfg.enabled = True
                    elif engine_id not in persistent_engines:
                        # Builtin is usually always enabled unless explicitly in config as disabled
                        if engine_id == "builtin" and "builtin" not in enabled_engines:
                            engine_cfg.enabled = False
            
            print(f"DEBUG: Engines after loop 2: {[(k, e.enabled) for k, e in settings.engines.items()]}")
            
            # Policies
            policy_cfg = expr_cfg.get("policies", {})
            settings.policies.allow_third_party_engines = policy_cfg.get("allow_third_party", settings.policies.allow_third_party_engines)
            settings.policies.allow_external_engines = policy_cfg.get("allow_external", settings.policies.allow_external_engines)
            
            return settings
        except Exception:
            # Fallback to defaults on any config error
            return cls()

_expression_settings_instance: Optional[ExpressionSettings] = None

def get_expression_settings() -> ExpressionSettings:
    """Get the global expression settings instance."""
    global _expression_settings_instance
    if _expression_settings_instance is None:
        _expression_settings_instance = ExpressionSettings.load_from_config()
    return _expression_settings_instance

def reload_expression_settings():
    """Reload expression settings from config."""
    global _expression_settings_instance
    _expression_settings_instance = ExpressionSettings.load_from_config()
    return _expression_settings_instance
