"""Generic governed specialist.

Used for custom / prompt-defined agents (A21) and skill/plugin composition.
Unlike native specialists, it carries NO hardcoded prompt and NO direct provider
or tool calls. It is composed entirely from the agent's registration:

    prompt contract (PromptRegistry)
    + allowed tools/plugins (ActionExecutionGate)
    + memory scope (canonical memory)
    + reasoning modes (ReasoningExecutor when requested)

This makes UI-created agents primarily configuration, not new Python files
(AGENT-LIVE-1: "skill/plugin composition").
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .specialist_base import SpecialistBase
from ..contracts.subagent_contract import SubagentContract, AgentCapability
from ..contracts.registration import AgentRegistration


class GenericGovernedSpecialist(SpecialistBase):
    """Specialist driven entirely by its AgentRegistration."""

    def __init__(self, registration: AgentRegistration) -> None:
        contract = SubagentContract(
            agent_id=registration.agent_id,
            role=registration.description or "Custom governed agent",
            capabilities=list(AgentCapability.REASONING),
        )
        super().__init__(contract)
        self.registration = registration

    async def _process(self, input_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        # STUB: composition seam. Real implementation wires:
        #  - prompt_contract_id/version -> PromptRegistry
        #  - GenerationBridge for model work (P0-2)
        #  - ToolBridge + ActionExecutionGate for side effects (P0-3)
        #  - canonical memory scopes (A12)
        #  - ReasoningExecutor for reasoning modes (A11)
        raise NotImplementedError(
            "GenericGovernedSpecialist execution is wired in AGENT-LIVE-1 "
            "(composes PromptRegistry + GenerationBridge + ActionExecutionGate)."
        )
