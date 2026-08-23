"""
Copilot Settings API Routes

This module provides secure API endpoints for copilot settings management
with proper RBAC enforcement and comprehensive audit logging.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from pydantic import BaseModel, ConfigDict, Field

from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.services.audit.audit_logger import get_audit_logger
from ai_karen_engine.core.security.secrets.secrets import get_secret_manager
from ai_karen_engine.services.formatting.settings_manager import get_settings_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings/copilot", tags=["copilot-settings"])


# Request/Response Models
class SetApiKeyRequest(BaseModel):
    """Request model for setting API key."""

    api_key: Optional[str] = Field(None, description="API key to set (null to remove)")


class ApiKeyStatusResponse(BaseModel):
    """Response model for API key status."""

    present: bool = Field(description="Whether API key is present")
    last_updated: Optional[str] = Field(None, description="Last update timestamp")
    provider_compatible: List[str] = Field(
        default_factory=list, description="Compatible providers"
    )


class ToggleCloudRequest(BaseModel):
    """Request model for toggling cloud features."""

    enabled: bool = Field(description="Whether to enable cloud features")


class CloudToggleResponse(BaseModel):
    """Response model for cloud toggle."""

    enabled: bool = Field(description="Current cloud features status")
    requirements_met: Dict[str, bool] = Field(description="Requirements validation")


class SetProfileRequest(BaseModel):
    """Request model for setting LLM profile."""

    profile_id: str = Field(description="Profile ID to activate")


class ProfileResponse(BaseModel):
    """Response model for profile information."""

    profile_id: str = Field(description="Active profile ID")
    profile_name: str = Field(description="Profile display name")
    routing_strategy: str = Field(description="Routing strategy")
    cloud_enabled: bool = Field(description="Whether cloud routing is enabled")


class SettingsStatusResponse(BaseModel):
    """Response model for comprehensive settings status."""

    cloud_validation: Dict[str, Any] = Field(description="Cloud feature validation")
    feature_flags: Dict[str, Any] = Field(description="Feature flags status")
    copilot_settings: Dict[str, Any] = Field(description="Copilot configuration")
    secrets: Dict[str, Any] = Field(description="Secrets status")


# Authentication and Authorization
async def require_admin_user(
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
) -> Dict[str, Any]:
    """
    Require admin user authentication.

    Args:
        user_ctx: Current user context from authentication

    Returns:
        User context if user is admin

    Raises:
        HTTPException: If user is not admin or not authenticated
    """
    if not user_ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    user_roles = user_ctx.get("roles", [])
    if "admin" not in user_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )

    return user_ctx


async def get_request_metadata(request: Request) -> Dict[str, str]:
    """Extract request metadata for audit logging."""
    xff = request.headers.get("x-forwarded-for")
    ip = (
        xff.split(",")[0].strip()
        if xff
        else (request.client.host if request.client else "unknown")
    )
    return {
        "ip_address": ip,
        "user_agent": request.headers.get("user-agent", ""),
        "correlation_id": getattr(request.state, "correlation_id", str(uuid.uuid4())),
    }


# API Key Management Endpoints
@router.get("/key", response_model=ApiKeyStatusResponse)
async def get_api_key_status(
    user: Dict[str, Any] = Depends(require_admin_user),
    request_meta: Dict[str, str] = Depends(get_request_metadata),
):
    """
    Get API key status (admin only).

    Returns presence information without exposing the actual key value.
    """
    try:
        secret_manager = get_secret_manager()
        audit_logger = get_audit_logger()

        # Get secret status
        status_info = secret_manager.get_secret_status("COPILOT_API_KEY")

        # Validate format if key exists
        provider_compatible = []
        if status_info["exists"]:
            # Get the actual key for validation (not returned to client)
            api_key = secret_manager.get_secret("COPILOT_API_KEY")
            if api_key:
                validation = secret_manager.validate_secret_format(
                    "COPILOT_API_KEY", api_key
                )
                provider_compatible = validation.get("provider_compatible", [])

        # Log audit event
        audit_logger.log_audit_event(
            {
                "event_type": "secret.accessed",
                "user_id": user["user_id"],
                "details": {
                    "secret_name": "COPILOT_API_KEY",
                    "action": "status_check",
                    "present": status_info["exists"],
                },
                "correlation_id": request_meta["correlation_id"],
                "ip_address": request_meta["ip_address"],
                "user_agent": request_meta["user_agent"],
                "surface": "api",
            }
        )

        return ApiKeyStatusResponse(
            present=status_info["exists"],
            last_updated=status_info.get("updated_at"),
            provider_compatible=provider_compatible,
        )

    except Exception as e:
        logger.error(f"Failed to get API key status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve API key status",
        )


@router.put("/key", response_model=ApiKeyStatusResponse)
async def set_api_key(
    request: SetApiKeyRequest,
    user: Dict[str, Any] = Depends(require_admin_user),
    request_meta: Dict[str, str] = Depends(get_request_metadata),
):
    """
    Set or update copilot API key (admin only).

    Pass null/empty api_key to remove the existing key.
    """
    try:
        secret_manager = get_secret_manager()
        audit_logger = get_audit_logger()

        if request.api_key:
            # Validate API key format
            validation = secret_manager.validate_secret_format(
                "COPILOT_API_KEY", request.api_key
            )

            if not validation["valid"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid API key format: {', '.join(validation['errors'])}",
                )

            # Set the API key
            success = secret_manager.set_secret(
                "COPILOT_API_KEY",
                request.api_key,
                "Copilot API key for cloud LLM providers",
            )

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to store API key",
                )

            # Log audit event
            audit_logger.log_audit_event(
                {
                    "event_type": "copilot.api_key.set",
                    "user_id": user["user_id"],
                    "details": {
                        "action": "api_key_updated",
                        "provider_compatible": validation.get(
                            "provider_compatible", []
                        ),
                        "validation_warnings": validation.get("warnings", []),
                    },
                    "correlation_id": request_meta["correlation_id"],
                    "ip_address": request_meta["ip_address"],
                    "user_agent": request_meta["user_agent"],
                    "surface": "api",
                }
            )

            return ApiKeyStatusResponse(
                present=True,
                last_updated=datetime.utcnow().isoformat(),
                provider_compatible=validation.get("provider_compatible", []),
            )

        else:
            # Remove API key
            success = secret_manager.delete_secret("COPILOT_API_KEY")

            # Log audit event (always log, even if key didn't exist)
            audit_logger.log_audit_event(
                {
                    "event_type": "copilot.api_key.removed",
                    "user_id": user["user_id"],
                    "details": {"action": "api_key_removed"},
                    "correlation_id": request_meta["correlation_id"],
                    "ip_address": request_meta["ip_address"],
                    "user_agent": request_meta["user_agent"],
                    "surface": "api",
                }
            )

            return ApiKeyStatusResponse(
                present=False,
                last_updated=datetime.utcnow().isoformat(),
                provider_compatible=[],
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set API key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update API key",
        )


# Cloud Features Management
@router.post("/toggle", response_model=CloudToggleResponse)
async def toggle_cloud_features(
    request: ToggleCloudRequest,
    user: Dict[str, Any] = Depends(require_admin_user),
    request_meta: Dict[str, str] = Depends(get_request_metadata),
):
    """
    Enable/disable cloud copilot features (admin only).
    """
    try:
        settings_manager = get_settings_manager()
        audit_logger = get_audit_logger()

        # Get current state
        current_state = settings_manager.get_feature_flag("copilot_cloud_enabled")

        # Update feature flag
        settings_manager.set_feature_flag("copilot_cloud_enabled", request.enabled)

        # Validate cloud requirements
        cloud_validation = settings_manager.validate_cloud_features()

        # Log audit event
        audit_logger.log_audit_event(
            {
                "event_type": "copilot.cloud_toggle",
                "user_id": user["user_id"],
                "details": {
                    "enabled": request.enabled,
                    "previous_state": current_state,
                    "requirements_met": cloud_validation["requirements_met"],
                },
                "correlation_id": request_meta["correlation_id"],
                "ip_address": request_meta["ip_address"],
                "user_agent": request_meta["user_agent"],
                "surface": "api",
            }
        )

        return CloudToggleResponse(
            enabled=request.enabled,
            requirements_met=cloud_validation["requirements_met"],
        )

    except Exception as e:
        logger.error(f"Failed to toggle cloud features: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle cloud features",
        )


# LLM Profile Management
@router.get("/profile", response_model=ProfileResponse)
async def get_active_profile(user: Dict[str, Any] = Depends(require_admin_user)):
    """
    Get currently active LLM profile.
    """
    try:
        settings_manager = get_settings_manager()

        # Get active profile ID
        active_profile_id = settings_manager.get_copilot_setting(
            "default_profile", "local_default"
        )

        # This would normally load from llm_profiles.yml
        # For now, return basic information
        profile_info = {
            "local_default": {
                "name": "Local First",
                "routing_strategy": "local_first_optional_cloud",
                "cloud_enabled": False,
            },
            "local_plus_cloud": {
                "name": "Local + Optional Cloud",
                "routing_strategy": "local_first_optional_cloud",
                "cloud_enabled": True,
            },
            "cloud_preferred": {
                "name": "Cloud Preferred",
                "routing_strategy": "cloud_first_local_fallback",
                "cloud_enabled": True,
            },
        }

        profile = profile_info.get(active_profile_id, profile_info["local_default"])

        return ProfileResponse(
            profile_id=active_profile_id,
            profile_name=profile["name"],
            routing_strategy=profile["routing_strategy"],
            cloud_enabled=profile["cloud_enabled"],
        )

    except Exception as e:
        logger.error(f"Failed to get active profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve active profile",
        )


@router.put("/profile", response_model=ProfileResponse)
async def set_active_profile(
    request: SetProfileRequest,
    user: Dict[str, Any] = Depends(require_admin_user),
    request_meta: Dict[str, str] = Depends(get_request_metadata),
):
    """
    Set active LLM profile (admin only).
    """
    try:
        settings_manager = get_settings_manager()
        audit_logger = get_audit_logger()

        # Validate profile ID
        valid_profiles = ["local_default", "local_plus_cloud", "cloud_preferred"]
        if request.profile_id not in valid_profiles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid profile ID. Valid options: {', '.join(valid_profiles)}",
            )

        # Get current profile
        current_profile = settings_manager.get_copilot_setting(
            "default_profile", "local_default"
        )

        # Set new profile
        settings_manager.set_copilot_setting("default_profile", request.profile_id)

        # Get profile information
        profile_info = {
            "local_default": {
                "name": "Local First",
                "routing_strategy": "local_first_optional_cloud",
                "cloud_enabled": False,
            },
            "local_plus_cloud": {
                "name": "Local + Optional Cloud",
                "routing_strategy": "local_first_optional_cloud",
                "cloud_enabled": True,
            },
            "cloud_preferred": {
                "name": "Cloud Preferred",
                "routing_strategy": "cloud_first_local_fallback",
                "cloud_enabled": True,
            },
        }

        profile = profile_info[request.profile_id]

        # Log audit event
        audit_logger.log_audit_event(
            {
                "event_type": "copilot.profile.changed",
                "user_id": user["user_id"],
                "details": {
                    "new_profile": request.profile_id,
                    "profile_name": profile["name"],
                    "previous_profile": current_profile,
                    "routing_strategy": profile["routing_strategy"],
                },
                "correlation_id": request_meta["correlation_id"],
                "ip_address": request_meta["ip_address"],
                "user_agent": request_meta["user_agent"],
                "surface": "api",
            }
        )

        return ProfileResponse(
            profile_id=request.profile_id,
            profile_name=profile["name"],
            routing_strategy=profile["routing_strategy"],
            cloud_enabled=profile["cloud_enabled"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set active profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set active profile",
        )


# Comprehensive Status Endpoint
@router.get("/status", response_model=SettingsStatusResponse)
async def get_settings_status(user: Dict[str, Any] = Depends(require_admin_user)):
    """
    Get comprehensive copilot settings status (admin only).
    """
    try:
        settings_manager = get_settings_manager()

        # Get comprehensive status
        status_info = settings_manager.get_settings_status()

        return SettingsStatusResponse(
            cloud_validation=status_info["cloud_validation"],
            feature_flags=status_info["feature_flags"],
            copilot_settings=status_info["copilot_settings"],
            secrets=status_info["secrets"],
        )

    except Exception as e:
        logger.error(f"Failed to get settings status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve settings status",
        )
