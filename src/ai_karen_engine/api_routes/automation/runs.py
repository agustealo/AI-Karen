import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.scheduling.automation_service import get_automation_service, AutomationService
from ai_karen_engine.core.automation.contracts import AgentRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-runs", tags=["agent-runs"])

@router.get("/", response_model=List[AgentRun])
async def list_all_runs(
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """List all agent runs across all triggers."""
    return await service.get_run_history()

@router.get("/{run_id}", response_model=AgentRun)
async def get_run(
    run_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """Get a specific agent run."""
    runs = await service.get_run_history()
    for r in runs:
        if r.id == run_id:
            return r
    raise HTTPException(status_code=404, detail="Run not found")

@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """Cancel an active agent run."""
    # Implementation placeholder
    return {"message": f"Run {run_id} cancellation requested"}
