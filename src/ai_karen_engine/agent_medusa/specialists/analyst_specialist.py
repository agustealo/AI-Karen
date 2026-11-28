from typing import Any, Dict, Optional
import json
import logging
import re
from .specialist_base import SpecialistBase
from ..contracts.subagent_contract import SubagentContract, AgentCapability
from ..contracts.specialist_execution import SpecialistExecutionContext
from ..specialists.bridges import GenerationBridge

logger = logging.getLogger(__name__)

class AnalystSpecialist(SpecialistBase):
    """The Analyst: specialized in parsing intent and structuring data.

    PromptRuntime owns the versioned Analyst contract and final assembly.
    Model work flows through GenerationBridge without inline fallback.
    """

    PROMPT_CONTRACT_ID = "karen.agent.analyst.intent"
    PROMPT_VERSION = "v1.0.0"

    def __init__(self):
        contract = SubagentContract(
            agent_id="analyst",
            role="Specialist in query analysis, intent detection, and structuring raw inputs",
            capabilities=[AgentCapability.REASONING]
        )
        super().__init__(contract)

    async def _process(
        self,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        execution: Optional[SpecialistExecutionContext] = None,
    ) -> Dict[str, Any]:
        query = input_data.get("query", "")
        self.logger.info("medusa_analyst_processing_query")

        messages = [{"role": "user", "content": query}]

        bridge = GenerationBridge()
        try:
            full_response = await bridge.invoke(
                request_id=execution.trajectory_id if execution else "analyst",
                correlation_id=execution.correlation_id if execution else "analyst",
                messages=messages,
                prompt_contract_id=self.PROMPT_CONTRACT_ID,
                prompt_version=self.PROMPT_VERSION,
                policy_decision_id=execution.policy_decision_id if execution else None,
                provider_constraints=getattr(execution.authorized_plan, "provider_constraints", {}) if execution else None,
                model_constraints=getattr(execution.authorized_plan, "model_constraints", {}) if execution else None,
                execution=execution,
            )

            json_match = re.search(r"\{.*\}", full_response, re.DOTALL)
            if json_match is None:
                raise ValueError("analyst_response_missing_json")
            result = json.loads(json_match.group(0))
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("intent"), str)
                or not result["intent"].strip()
                or not isinstance(result.get("key_terms"), list)
                or not all(isinstance(term, str) for term in result["key_terms"])
                or type(result.get("requires_research")) is not bool
            ):
                raise ValueError("analyst_response_invalid_schema")
            return {
                "intent": result["intent"],
                "structured_query": {"raw": query, "key_terms": result["key_terms"]},
                "suggested_next_specialist": (
                    "researcher" if result["requires_research"] else None
                ),
            }
        except Exception as exc:
            self.logger.warning(
                "medusa_analyst_analysis_failed",
                extra={"error_type": type(exc).__name__},
            )
            # Preserve permission/budget/receipt errors for the coordinator.
            # Invalid model output is a failed step, not a guessed intent.
            raise
