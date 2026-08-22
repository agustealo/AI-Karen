"""
Feature Flags for AI Karen Resilience Layer.

Supports global defaults, tenant overrides, user overrides, and request overrides.
"""

from typing import Dict, Optional

class FeatureFlags:
    """Manages feature toggles across the Karen architecture."""

    def __init__(self):
        self._global_defaults: Dict[str, bool] = {
            "spacy_enabled": True,
            "distilbert_enabled": True,
            "memory_learning_enabled": True,
            "memory_shadow_mode_enabled": False,
            "memory_inspector_enabled": True,
            "memory_consent_controls_enabled": True,
            "memory_retention_controls_enabled": True,
            "memory_profile_corrections_enabled": True,
            "graph_relationships_enabled": True,
            "profile_synthesis_enabled": True,
            "elasticsearch_hybrid_enabled": True,
            "echocore_enabled": True,
            "reasoning_enabled": True,
            "reasoning_retrieval_enabled": True,
            "reasoning_causal_enabled": True,
            "reasoning_graph_enabled": True,
            "reasoning_soft_enabled": True,
            "reasoning_synthesis_enabled": True,
            "kro_orchestrator_enabled": True,
            "training_candidates_enabled": False, # Safer default
            "personalization_enabled": True,
            "organization_learning_enabled": False,
            "autonomous_learning_enabled": False,
        }
        self._tenant_overrides: Dict[str, Dict[str, bool]] = {}
        self._user_overrides: Dict[str, Dict[str, bool]] = {}

    def set_global(self, flag_name: str, value: bool) -> None:
        self._global_defaults[flag_name] = value

    def set_tenant_override(self, tenant_id: str, flag_name: str, value: bool) -> None:
        if tenant_id not in self._tenant_overrides:
            self._tenant_overrides[tenant_id] = {}
        self._tenant_overrides[tenant_id][flag_name] = value

    def set_user_override(self, user_id: str, flag_name: str, value: bool) -> None:
        if user_id not in self._user_overrides:
            self._user_overrides[user_id] = {}
        self._user_overrides[user_id][flag_name] = value

    def is_enabled(
        self,
        flag_name: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        request_overrides: Optional[Dict[str, bool]] = None
    ) -> bool:
        """Resolve feature flag with cascading precedence."""
        # 1. Request level override (highest precedence)
        if request_overrides and flag_name in request_overrides:
            return request_overrides[flag_name]

        # 2. User level override
        if user_id and user_id in self._user_overrides:
            if flag_name in self._user_overrides[user_id]:
                return self._user_overrides[user_id][flag_name]

        # 3. Tenant level override
        if tenant_id and tenant_id in self._tenant_overrides:
            if flag_name in self._tenant_overrides[tenant_id]:
                return self._tenant_overrides[tenant_id][flag_name]

        # 4. Global default (lowest precedence)
        return self._global_defaults.get(flag_name, False)

# Singleton instance
feature_flags = FeatureFlags()

def get_feature_flags() -> FeatureFlags:
    return feature_flags
