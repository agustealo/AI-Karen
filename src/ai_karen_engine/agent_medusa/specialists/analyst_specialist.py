from typing import Any, Dict, Optional
import logging
from .specialist_base import SpecialistBase
from ..contracts.subagent_contract import SubagentContract, AgentCapability
from ..contracts.specialist_execution import SpecialistExecutionContext
from ..specialists.bridges import GenerationBridge, resolve_prompt_text

logger = logging.getLogger(__name__)

ANALYST_PROMPT = """
Analyze the following user query for Karen AI.
Detect the primary intent (e.g., weather, information, task) and extract key terms.

User Query: {query}

Respond with a JSON object:
{{
  "intent": "string",
  "key_terms": ["list", "of", "terms"],
  "requires_research": boolean
}}
"""


class AnalystSpecialist(SpecialistBase):
    """The Analyst: specialized in parsing intent and structuring data.

    Prompt lives in PromptRegistry (karen.agent.analyst.intent@v1) for
    versioned reproducibility (A10); falls back to inline text when the
    registry is unavailable. Model work flows through GenerationBridge.
    """

    PROMPT_CONTRACT_ID = "karen.agent.analyst.intent"
    PROMPT_VERSION = "v1"

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
        self.logger.info(f"Analyst processing query: {query}")

        system_prompt = resolve_prompt_text(self.PROMPT_CONTRACT_ID, self.PROMPT_VERSION, ANALYST_PROMPT)
        messages = [
            {"role": "system", "content": "You are Karen's Analyst specialist."},
            {"role": "user", "content": system_prompt.format(query=query)},
        ]

        bridge = GenerationBridge()
        try:
            full_response = await bridge.invoke(
                request_id=execution.trajectory_id if execution else "analyst",
                correlation_id=execution.correlation_id if execution else "analyst",
                messages=messages,
                prompt_contract_id=self.PROMPT_CONTRACT_ID,
                policy_decision_id=execution.policy_decision_id if execution else None,
                provider_constraints=getattr(execution.authorized_plan, "provider_constraints", {}) if execution else None,
                model_constraints=getattr(execution.authorized_plan, "model_constraints", {}) if execution else None,
                execution=execution,
            )

            import json
            import re
            json_match = re.search(r'\{.*\}', full_response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                return {
                    "intent": result.get("intent", "information_request"),
                    "structured_query": {"raw": query, "key_terms": result.get("key_terms", [])},
                    "suggested_next_specialist": "researcher" if result.get("requires_research") else None,
                }
        except Exception as e:
            self.logger.warning(f"LLM analysis failed, falling back: {e}")

        intent = "information_request" if "?" in query else "task_request"
        return {
            "intent": intent,
            "structured_query": {"raw": query, "key_terms": []},
            "suggested_next_specialist": "researcher",
        }
