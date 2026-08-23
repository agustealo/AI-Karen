import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.services.scheduling.automation_service import get_automation_service, AutomationService
from ai_karen_engine.core.automation.contracts import (
    AgentAutomation,
    AgentRun,
    AutomationDraft,
    ExecutionStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/automations", tags=["automations"])

# Models for Request/Response
class DraftRequest(BaseModel):
    intent: str
    context: Dict[str, Any] = {}

class ConfirmRequest(BaseModel):
    draft_id: str

@router.post("/draft", response_model=AutomationDraft)
async def create_draft(
    request: DraftRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """Create an automation draft from user intent."""
    try:
        return await service.create_draft(request.intent, request.context)
    except Exception as e:
        logger.error(f"Error creating draft: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/confirm", response_model=AgentAutomation)
async def confirm_draft(
    request: ConfirmRequest,
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """Confirm a draft and create an active automation."""
    try:
        user_id = user.get("user_id") or user.get("id") or "anonymous"
        return await service.confirm_draft(request.draft_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error confirming draft: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[AgentAutomation])
async def list_automations(
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """List all automations."""
    return await service.list_automations(user_id=user.get("user_id"))

@router.get("/{automation_id}", response_model=AgentAutomation)
async def get_automation(
    automation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """Get a specific automation."""
    auto = await service.get_automation(automation_id)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    return auto

@router.delete("/{automation_id}")
async def delete_automation(
    automation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """Delete an automation."""
    success = await service.delete_automation(automation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"message": "Automation deleted"}

@router.get("/{automation_id}/runs", response_model=List[AgentRun])
async def list_automation_runs(
    automation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """List runs for an automation."""
    return await service.get_run_history(automation_id=automation_id)

@router.post("/{automation_id}/run")
async def trigger_automation(
    automation_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    service: AutomationService = Depends(get_automation_service)
):
    """Manually trigger an automation."""
    auto = await service.get_automation(automation_id)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
        
    # Start a run
    run = await service.start_run(
        automation_id=automation_id,
        trigger_source="manual",
        agent_id=auto.execution.agent_id,
        agent_name=auto.execution.agent_name,
        workflow_id=auto.execution.workflow_id,
        workflow_name=auto.execution.workflow_name
    )
    
    # In real implementation, this would trigger background execution
    # For now we'll just return the run record
    return run
