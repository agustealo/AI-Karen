import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from ai_karen_engine.core.automation.contracts import (
    AgentAutomation,
    AgentRun,
    AutomationDraft,
    ExecutionStatus,
    AutomationTrigger,
)

logger = logging.getLogger(__name__)

class AutomationService:
    """Generic Automation Service for managing agent and workflow automations."""

    def __init__(self):
        self._automations: Dict[str, AgentAutomation] = {}
        self._runs: Dict[str, AgentRun] = {}
        self._drafts: Dict[str, AutomationDraft] = {}
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        # Load from DB in real implementation
        self._initialized = True
        logger.info("AutomationService initialized")

    async def create_draft(self, user_intent: str, user_context: Dict[str, Any]) -> AutomationDraft:
        """Create an automation draft based on user intent."""
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"
        
        # In a real implementation, this would call CORTEX/LLM to interpret the intent
        # and build a structured plan. For now, we'll return a mock draft.
        
        draft = AutomationDraft(
            draft_id=draft_id,
            name="New Automation",
            goal=user_intent,
            trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
            execution={
                "agent_id": "diagnostics",
                "agent_name": "Diagnostics Agent",
                "tools": []
            },
            memory={
                "can_read": True,
                "can_write": True,
                "write_mode": "summary_only"
            },
            approval={
                "required_to_create": True,
                "required_before_execution": False
            },
            notification={
                "channels": ["chat"]
            }
        )
        
        self._drafts[draft_id] = draft
        return draft

    async def confirm_draft(self, draft_id: str, user_id: str) -> AgentAutomation:
        """Convert a draft into an active automation."""
        if draft_id not in self._drafts:
            raise ValueError(f"Draft {draft_id} not found")
            
        draft = self._drafts.pop(draft_id)
        automation_id = f"auto_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        
        automation = AgentAutomation(
            id=automation_id,
            name=draft.name,
            description=draft.goal,
            trigger=draft.trigger,
            execution=draft.execution,
            memory=draft.memory,
            approval=draft.approval,
            notification=draft.notification,
            risk_level=draft.risk_level,
            created_at=now,
            updated_at=now,
            created_by_user_id=user_id
        )
        
        self._automations[automation_id] = automation
        return automation

    async def list_automations(self, user_id: Optional[str] = None) -> List[AgentAutomation]:
        """List all automations."""
        if user_id:
            return [a for a in self._automations.values() if a.created_by_user_id == user_id]
        return list(self._automations.values())

    async def get_automation(self, automation_id: str) -> Optional[AgentAutomation]:
        """Get a specific automation."""
        return self._automations.get(automation_id)

    async def delete_automation(self, automation_id: str) -> bool:
        """Delete an automation."""
        if automation_id in self._automations:
            del self._automations[automation_id]
            return True
        return False

    async def start_run(self, automation_id: Optional[str], trigger_source: str, **kwargs) -> AgentRun:
        """Start a new agent/automation run."""
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        correlation_id = kwargs.get("correlation_id", f"corr_{uuid.uuid4().hex[:8]}")
        
        run = AgentRun(
            id=run_id,
            automation_id=automation_id,
            correlation_id=correlation_id,
            status=ExecutionStatus.RUNNING,
            trigger_source=trigger_source,
            started_at=datetime.now(timezone.utc),
            agent_id=kwargs.get("agent_id"),
            agent_name=kwargs.get("agent_name"),
            workflow_id=kwargs.get("workflow_id"),
            workflow_name=kwargs.get("workflow_name"),
            metadata=kwargs.get("metadata", {})
        )
        
        self._runs[run_id] = run
        return run

    async def complete_run(self, run_id: str, summary: str, trace: List[Dict[str, Any]] = None):
        """Complete a run successfully."""
        if run_id in self._runs:
            run = self._runs[run_id]
            run.status = ExecutionStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.summary = summary
            run.trace = trace or []
            run.latency_ms = (run.completed_at - run.started_at).total_seconds() * 1000

    async def fail_run(self, run_id: str, error: str):
        """Mark a run as failed."""
        if run_id in self._runs:
            run = self._runs[run_id]
            run.status = ExecutionStatus.FAILED
            run.completed_at = datetime.now(timezone.utc)
            run.error = error
            run.latency_ms = (run.completed_at - run.started_at).total_seconds() * 1000

    async def get_run_history(self, automation_id: Optional[str] = None) -> List[AgentRun]:
        """Get run history."""
        if automation_id:
            return [r for r in self._runs.values() if r.automation_id == automation_id]
        return list(self._runs.values())

_automation_service: Optional[AutomationService] = None

def get_automation_service() -> AutomationService:
    global _automation_service
    if _automation_service is None:
        _automation_service = AutomationService()
    return _automation_service
