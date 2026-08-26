from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EngineConfig:
    enabled: bool = True
    type: str = "openai_compatible"
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
    """Expression routing configuration.

    Chat generation is provider-agnostic. Local OpenAI-compatible endpoints are
    the default execution surface; specialized ML runtimes remain capabilities
    of Core and are not exposed as a parallel chat-provider authority.
    """

    active_engine: str = "local"
    engines: dict[str, EngineConfig] = field(
        default_factory=lambda: {
            "local": EngineConfig(
                enabled=True,
                type="openai_compatible",
                fallback_eligible=True,
            ),
            "cloud": EngineConfig(
                enabled=False,
                type="openai_compatible",
                fallback_eligible=True,
            ),
        }
    )
    policies: ExpressionPolicyConfig = field(default_factory=ExpressionPolicyConfig)
    engine_fallback_order: list[str] = field(default_factory=lambda: ["local", "cloud"])
    local_first_mode: bool = True
    provider_fallback_policy: str = "ordered"
    third_party_endpoint_url: str | None = None
    deployment_profile: str = "desktop_local"

    @classmethod
    def load_from_config(cls) -> ExpressionSettings:
        """Load expression settings from the canonical global config manager."""
        try:
            from ai_karen_engine.config.config_manager import config_manager

            expr_cfg = config_manager.get_config_value("expression", default={})
            settings = cls()
            if not expr_cfg:
                return settings

            configured_active = str(
                expr_cfg.get("active_engine", settings.active_engine)
            ).strip()
            if configured_active == "builtin":
                logger.warning(
                    "Retired expression engine 'builtin' requested; using 'local'."
                )
                configured_active = "local"
            settings.active_engine = configured_active or "local"

            configured_fallbacks = list(
                expr_cfg.get("fallback_order", settings.engine_fallback_order)
            )
            settings.engine_fallback_order = [
                "local" if engine_id == "builtin" else engine_id
                for engine_id in configured_fallbacks
                if engine_id != "disabled"
            ]
            settings.engine_fallback_order = list(
                dict.fromkeys(settings.engine_fallback_order)
            ) or ["local", "cloud"]

            settings.local_first_mode = expr_cfg.get(
                "local_first_mode", settings.local_first_mode
            )
            settings.deployment_profile = expr_cfg.get(
                "deployment_profile", settings.deployment_profile
            )

            persistent_engines = expr_cfg.get("engines", {})
            enabled_engines = set(expr_cfg.get("enabled_engines", []))

            for raw_engine_id, p_cfg in persistent_engines.items():
                engine_id = "local" if raw_engine_id == "builtin" else raw_engine_id
                if raw_engine_id == "builtin":
                    logger.warning(
                        "Retired expression engine config 'builtin' mapped to 'local'."
                    )

                if engine_id not in settings.engines:
                    settings.engines[engine_id] = EngineConfig(
                        enabled=p_cfg.get("enabled", True),
                        type="openai_compatible",
                        fallback_eligible=p_cfg.get("fallback_eligible", True),
                        metadata=p_cfg.get("metadata", {}),
                        note=p_cfg.get("note"),
                        base_url=p_cfg.get("base_url"),
                    )
                    continue

                engine_cfg = settings.engines[engine_id]
                engine_cfg.enabled = p_cfg.get("enabled", engine_cfg.enabled)
                engine_cfg.type = "openai_compatible"
                engine_cfg.fallback_eligible = p_cfg.get(
                    "fallback_eligible", engine_cfg.fallback_eligible
                )
                engine_cfg.metadata = p_cfg.get("metadata") or engine_cfg.metadata
                engine_cfg.note = p_cfg.get("note", engine_cfg.note)
                engine_cfg.base_url = p_cfg.get("base_url", engine_cfg.base_url)

            if "enabled_engines" in expr_cfg:
                normalized_enabled = {
                    "local" if engine_id == "builtin" else engine_id
                    for engine_id in enabled_engines
                }
                for engine_id, engine_cfg in settings.engines.items():
                    if engine_id in normalized_enabled:
                        engine_cfg.enabled = True
                    elif engine_id not in persistent_engines:
                        engine_cfg.enabled = False

            if settings.active_engine not in settings.engines:
                logger.warning(
                    "Unknown active expression engine '%s'; using 'local'.",
                    settings.active_engine,
                )
                settings.active_engine = "local"

            policy_cfg = expr_cfg.get("policies", {})
            settings.policies.allow_third_party_engines = policy_cfg.get(
                "allow_third_party",
                settings.policies.allow_third_party_engines,
            )
            settings.policies.allow_external_engines = policy_cfg.get(
                "allow_external",
                settings.policies.allow_external_engines,
            )
            settings.policies.require_admin_for_external = policy_cfg.get(
                "require_admin_for_external",
                settings.policies.require_admin_for_external,
            )
            settings.policies.default_timeout_ms = int(
                policy_cfg.get(
                    "default_timeout_ms",
                    settings.policies.default_timeout_ms,
                )
            )
            return settings
        except Exception:
            logger.exception("Failed to load expression settings; using safe defaults")
            return cls()


_expression_settings_instance: Optional[ExpressionSettings] = None


def get_expression_settings() -> ExpressionSettings:
    """Get the global expression settings instance."""
    global _expression_settings_instance
    if _expression_settings_instance is None:
        _expression_settings_instance = ExpressionSettings.load_from_config()
    return _expression_settings_instance


def reload_expression_settings() -> ExpressionSettings:
    """Reload expression settings from config."""
    global _expression_settings_instance
    _expression_settings_instance = ExpressionSettings.load_from_config()
    return _expression_settings_instance
