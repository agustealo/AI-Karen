"""Trusted implementation resolver for Medusa agents.

Closes the split authority described in P0-4 / A4:

    PlanStep.agent_id
            -> MedusaRegistry.get_agent
            -> AgentRegistration.implementation_id
            -> TrustedImplementationFactory.resolve
            -> executable specialist

No hardcoded specialist dictionary in the coordinator. Only explicitly trusted
implementation identifiers resolve to executable specialists.

Security boundary: only implementations registered in this factory are
resolvable. Never import arbitrary classes from user input.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .contracts.registration import AgentRegistration

logger = logging.getLogger(__name__)


# Resolver returns a callable that constructs a specialist instance.
ImplementationFactory = Callable[[AgentRegistration], Any]


class TrustedImplementationFactory:
    """Maps trusted implementation identifiers to specialist constructors."""

    def __init__(self) -> None:
        # Built-in native implementations.
        self._implementations: Dict[str, ImplementationFactory] = {}

    def register_implementation(self, implementation_id: str, factory: ImplementationFactory) -> None:
        self._implementations[implementation_id] = factory

    def resolve(self, registration: AgentRegistration) -> Any:
        """Resolve a registration to an executable specialist instance."""
        impl_id = getattr(registration, "implementation_id", None)
        if impl_id and impl_id in self._implementations:
            return self._implementations[impl_id](registration)
        raise ValueError(
            f"No trusted implementation registered for agent {registration.agent_id!r} "
            f"(implementation_id={impl_id!r})"
        )


# Module-level registry so coordinator/planner share one factory.
_FACTORY: Optional[TrustedImplementationFactory] = None


def get_implementation_factory() -> TrustedImplementationFactory:
    global _FACTORY
    if _FACTORY is None:
        _FACTORY = TrustedImplementationFactory()
        _register_builtins(_FACTORY)
    return _FACTORY


def _register_builtins(factory: TrustedImplementationFactory) -> None:
    """Wire built-in native specialists.

    Lazy imports avoid a hard dependency cycle with specialists at import time.
    """
    from .specialists.analyst_specialist import AnalystSpecialist
    from .specialists.researcher_specialist import ResearcherSpecialist

    factory.register_implementation(
        "karen.agent.analyst.native",
        lambda reg: AnalystSpecialist(),
    )
    factory.register_implementation(
        "karen.agent.researcher.native",
        lambda reg: ResearcherSpecialist(),
    )
