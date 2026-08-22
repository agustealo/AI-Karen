from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.model_runtime.model_selection_algorithm import ModelSelectionAlgorithm
from ai_karen_engine.core.model_runtime.provider_registry_service import ProviderRegistryService


@dataclass
class ProductionDecision:
    provider: Optional[str]
    model: Optional[str]
    fallback_level: int
    fallback_chain: List[str]
    degraded_mode_reason: Optional[str]
    telemetry: Dict[str, Any]


class ProductionDecisionService:
    """Canonical production decision entrypoint for provider/model selection."""

    _LEVEL_BY_PATH = {
        "user_preference": 0,
        "system_defaults": 1,
        "registry_fallback": 2,
        "hard_fallback": 3,
        "degraded_mode": 4,
    }

    def __init__(
        self,
        provider_registry: ProviderRegistryService,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.provider_registry = provider_registry
        self.selector = ModelSelectionAlgorithm(
            provider_registry=provider_registry,
            config=config,
        )

    async def select(self, user_preferences: Optional[Dict[str, str]] = None, context: Optional[Dict[str, Any]] = None) -> ProductionDecision:
        user_preferences = user_preferences or {}
        result = await self.selector.select_provider_and_model(user_preferences=user_preferences, context=context)
        fallback_chain = self._extract_fallback_chain(result.selection_log)
        degraded_reason = result.rationale if result.selection_path == "degraded_mode" else None
        return ProductionDecision(
            provider=result.provider,
            model=result.model,
            fallback_level=self._LEVEL_BY_PATH.get(result.selection_path, 99),
            fallback_chain=fallback_chain,
            degraded_mode_reason=degraded_reason,
            telemetry={
                "selection_path": result.selection_path,
                "fallback_level": self._LEVEL_BY_PATH.get(result.selection_path, 99),
                "fallback_chain": fallback_chain,
                "chosen_provider": result.provider,
                "chosen_model": result.model,
                "degraded_mode_reason": degraded_reason,
                "fallback_attempts": result.fallback_attempts,
                "health_checks_performed": result.health_checks_performed,
            },
        )

    @staticmethod
    def _extract_fallback_chain(selection_log: List[str]) -> List[str]:
        chain: List[str] = []
        for entry in selection_log:
            if "Trying" not in entry and "selected" not in entry:
                continue
            cleaned = entry.replace("Step 1: Trying user preference - ", "")
            cleaned = cleaned.replace("Step 2: Trying system default hierarchy - ", "")
            cleaned = cleaned.replace("Step 2b: Registry fallback selected - ", "")
            cleaned = cleaned.replace("Step 3: Trying hard final fallback - ", "")
            cleaned = cleaned.strip()
            if cleaned and cleaned not in chain:
                chain.append(cleaned)
        return chain


_service: Optional[ProductionDecisionService] = None


def get_production_decision_service() -> ProductionDecisionService:
    global _service
    if _service is None:
        _service = ProductionDecisionService(provider_registry=ProviderRegistryService())
    return _service
