"""
Public API Routes

These routes provide basic system information without requiring authentication.
Used for initial frontend loading and system status checks.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
try:
    from pydantic import BaseModel
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel

from ai_karen_engine.core.runtime.operational_health import get_operational_health_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public"])


class SystemInfo(BaseModel):
    """Basic system information."""
    name: str = "AI Karen Engine"
    version: str = "1.0.0"
    status: str = "operational"
    authentication_required: bool = True
    features: List[str] = []


class PublicProviderInfo(BaseModel):
    """Public provider information (no sensitive data)."""
    name: str
    description: str
    category: str
    provider_type: str  # local, remote, hybrid
    requires_api_key: bool
    documentation_url: Optional[str] = None


@router.get("/system/info", response_model=SystemInfo)
async def get_system_info():
    """Get basic system information without authentication."""
    try:
        return SystemInfo(
            name="AI Karen Engine",
            version="1.0.0",
            status="operational",
            authentication_required=True,
            features=[
                "Multi-provider LLM support",
                "Intelligent error responses", 
                "Session persistence",
                "Role-based access control",
                "Training orchestration",
                "Model management"
            ]
        )
    except Exception as e:
        logger.error("Failed to get system info", extra={"error_type": type(e).__name__})
        raise HTTPException(status_code=500, detail="Failed to retrieve system information")


@router.get("/providers/basic", response_model=List[PublicProviderInfo])
async def get_basic_provider_info():
    """Get basic provider information without authentication."""
    try:
        # Return basic provider info that doesn't require authentication
        basic_providers = [
            PublicProviderInfo(
                name="openai",
                description="OpenAI GPT models",
                category="LLM",
                provider_type="remote",
                requires_api_key=True,
                documentation_url="https://platform.openai.com/docs"
            ),
            PublicProviderInfo(
                name="gemini",
                description="Google Gemini models",
                category="LLM", 
                provider_type="remote",
                requires_api_key=True,
                documentation_url="https://ai.google.dev/docs"
            ),
            PublicProviderInfo(
                name="local",
                description="Local model execution",
                category="LLM",
                provider_type="local",
                requires_api_key=False
            ),
            PublicProviderInfo(
                name="huggingface",
                description="Hugging Face models",
                category="LLM",
                provider_type="hybrid",
                requires_api_key=False,
                documentation_url="https://huggingface.co/docs"
            )
        ]
        
        return basic_providers
        
    except Exception as e:
        logger.error("Failed to get basic provider info", extra={"error_type": type(e).__name__})
        raise HTTPException(status_code=500, detail="Failed to retrieve provider information")


@router.get("/health", response_model=Dict[str, Any])
async def public_health_check(request: Request) -> Dict[str, Any]:
    """Project canonical runtime readiness without leaking internal diagnostics.

    The public endpoint reports observed readiness only. It never invents
    authentication health or provider availability from a static list.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return {
            "status": "degraded",
            "timestamp": timestamp,
            "services": {"api": "operational", "readiness": "unavailable"},
            "message": "Runtime readiness unavailable",
        }

    try:
        result = await get_operational_health_service().readiness(
            environment=str(getattr(settings, "environment", "production")),
        )
        components = result.as_dict().get("components", {})
        return {
            "status": "healthy" if result.ready else "degraded",
            "timestamp": timestamp,
            "services": {
                "api": "operational",
                "configuration": components.get("configuration", "unknown"),
                "database": components.get("database", "unknown"),
                "redis": components.get("redis", "unknown"),
            },
            "message": "Runtime ready" if result.ready else "Runtime not ready",
        }
    except Exception as exc:
        logger.error(
            "Public readiness check failed",
            extra={"error_type": type(exc).__name__},
        )
        return {
            "status": "degraded",
            "timestamp": timestamp,
            "services": {"api": "operational", "readiness": "unavailable"},
            "message": "Runtime readiness unavailable",
        }
