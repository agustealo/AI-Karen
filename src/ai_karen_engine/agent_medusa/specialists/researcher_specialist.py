from typing import Any, Dict, Optional
import logging
from .specialist_base import SpecialistBase
from ..contracts.subagent_contract import SubagentContract, AgentCapability
from ..contracts.specialist_execution import SpecialistExecutionContext
from ..specialists.bridges import GenerationBridge, ToolBridge, resolve_prompt_text

logger = logging.getLogger(__name__)

SYNTHESIS_PROMPT = """
As a Researcher Agent, summarize the following tool findings for the query: "{query}"

Findings:
{findings}
"""


class ResearcherSpecialist(SpecialistBase):
    """The Researcher: specialized in gathering context and executing tool-based searches.

    Prompt lives in PromptRegistry (karen.agent.researcher.synthesis@v1) for
    versioned reproducibility (A10). Tool side effects flow through ToolBridge ->
    ActionExecutionGate; model synthesis through GenerationBridge.
    """

    PROMPT_CONTRACT_ID = "karen.agent.researcher.synthesis"
    PROMPT_VERSION = "v1"

    def __init__(self):
        contract = SubagentContract(
            agent_id="researcher",
            role="Specialist in gathering external/internal context and using search tools",
            capabilities=[AgentCapability.WEB_SEARCH, AgentCapability.MEMORY_RETRIEVAL]
        )
        super().__init__(contract)

    async def _process(
        self,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        execution: Optional[SpecialistExecutionContext] = None,
    ) -> Dict[str, Any]:
        self.logger.info("Researcher gathering context")

        query = input_data.get("raw", input_data.get("query", ""))
        tool_results = []

        if query:
            tool_name = "web_search"
            try:
                self.logger.info(f"Researcher executing tool via gate: {tool_name}")
                result = await ToolBridge().execute(
                    tool_name=tool_name,
                    parameters={"query": query},
                    authorized_plan=execution.authorized_plan,
                    tenant_id=execution.tenant_id,
                    user_id=execution.user_id,
                    policy_decision_id=execution.policy_decision_id,
                    trajectory_id=execution.trajectory_id,
                    agent_id="researcher",
                    step_id=execution.step_id,
                    execution=execution,
                )
                if result.get("success"):
                    tool_results.append({"tool": tool_name, "result": result.get("result")})
            except Exception as e:
                self.logger.warning(f"Researcher tool execution failed: {e}")

        if tool_results:
            import json
            findings_data = json.dumps(tool_results, indent=2, default=str)
            system_prompt = resolve_prompt_text(self.PROMPT_CONTRACT_ID, self.PROMPT_VERSION, SYNTHESIS_PROMPT)
            messages = [
                {"role": "system", "content": "You are Karen's Researcher specialist."},
                {"role": "user", "content": system_prompt.format(query=query, findings=findings_data)},
            ]
            try:
                summary = await GenerationBridge().invoke(
                    request_id=execution.trajectory_id if execution else "researcher",
                    correlation_id=execution.correlation_id if execution else "researcher",
                    messages=messages,
                    prompt_contract_id=self.PROMPT_CONTRACT_ID,
                    policy_decision_id=execution.policy_decision_id if execution else None,
                    provider_constraints=getattr(execution.authorized_plan, "provider_constraints", {}) if execution else None,
                    model_constraints=getattr(execution.authorized_plan, "model_constraints", {}) if execution else None,
                    execution=execution,
                )
                return {
                    "search_results": tool_results,
                    "context_found": summary.strip(),
                    "confidence": 0.9,
                }
            except Exception:
                pass

        return {
            "search_results": tool_results,
            "context_found": f"Found {len(tool_results)} results related to {query}" if tool_results else "No additional context found.",
            "confidence": 0.5,
        }
