"""Native research through the canonical governed tool and generation bridges."""

from typing import Any, Dict, Optional
import json

from .specialist_base import SpecialistBase
from ..contracts.subagent_contract import SubagentContract, AgentCapability
from ..contracts.specialist_execution import SpecialistExecutionContext
from ..specialists.bridges import GenerationBridge, ToolBridge

class ResearcherSpecialist(SpecialistBase):
    """Collect acknowledged tool evidence and synthesize through local generation."""

    PROMPT_CONTRACT_ID = "karen.agent.researcher.synthesis"
    PROMPT_VERSION = "v1.0.0"

    def __init__(self):
        super().__init__(SubagentContract(
            agent_id="researcher",
            role="Specialist in gathering external/internal context and using search tools",
            capabilities=[AgentCapability.WEB_SEARCH, AgentCapability.MEMORY_RETRIEVAL],
        ))

    async def _process(
        self,
        input_data: Dict[str, Any],
        context: Dict[str, Any],
        execution: Optional[SpecialistExecutionContext] = None,
    ) -> Dict[str, Any]:
        if execution is None:
            raise PermissionError("researcher_execution_authority_required")
        query = input_data.get("raw", input_data.get("query", ""))
        if not isinstance(query, str) or not query.strip():
            raise ValueError("researcher_query_required")

        from ai_karen_engine.core.runtime.prompt import get_prompt_runtime_service

        # A missing synthesis contract must not trigger a paid/external tool.
        get_prompt_runtime_service().require_active_prompt_definition(
            self.PROMPT_CONTRACT_ID, self.PROMPT_VERSION
        )
        # ToolBridge owns authorization, accounting and durable receipts.
        # Never interpret a denial or uncertain receipt as a successful search.
        tool_name = "web_search"
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
        if not isinstance(result, dict) or result.get("success") is not True:
            raise RuntimeError("researcher_tool_result_unacknowledged")
        if "result" not in result or result["result"] is None:
            raise RuntimeError("researcher_tool_evidence_missing")

        tool_results = [{"tool": tool_name, "result": result["result"]}]
        messages = [{
            "role": "user",
            "content": json.dumps({"query": query, "findings": tool_results}, default=str),
        }]
        # Do not return private raw findings after a failed or denied synthesis.
        # The coordinator owns failure handling; no synthetic confidence score.
        summary = await GenerationBridge().invoke(
            request_id=execution.trajectory_id,
            correlation_id=execution.correlation_id,
            messages=messages,
            prompt_contract_id=self.PROMPT_CONTRACT_ID,
            prompt_version=self.PROMPT_VERSION,
            policy_decision_id=execution.policy_decision_id,
            provider_constraints=execution.authorized_plan.provider_constraints,
            model_constraints=getattr(execution.authorized_plan, "model_constraints", {}),
            execution=execution,
        )
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError("researcher_synthesis_empty")
        return {
            "search_results": tool_results,
            "context_found": summary.strip(),
        }
