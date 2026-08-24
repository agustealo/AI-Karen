"""
Admin Provider Service — wraps ProviderRegistryService with admin-specific
logic, audit logging, and tenant-aware operations.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Type

from ai_karen_engine.core.model_runtime.provider_registry_service import (
    ProviderRegistryService,
    ProviderRegistration,
    ProviderCapability,
    ProviderStatus,
    get_provider_registry_service,
)
from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpoint
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)

logger = get_logger(__name__)


@dataclass
class AdminProviderFilter:
    """Filter criteria for admin provider listing."""

    category: Optional[str] = None
    capability: Optional[ProviderCapability] = None
    available_only: bool = False
    limit: int = 100
    offset: int = 0


class AdminProviderService:
    """
    Admin-facing wrapper around ProviderRegistryService.

    Adds:
    - Structured audit events for all mutations
    - Admin-specific filtering and model inventory queries
    - Tenant boundary notes (registry is global, but endpoints may be tenant-scoped)
    """

    def __init__(self, registry: Optional[ProviderRegistryService] = None) -> None:
        self._registry = registry or get_provider_registry_service()
        self._audit = get_audit_logger()

    def _audit_mutation(
        self,
        action: str,
        provider_id: Optional[str],
        operator_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit an admin audit event for a provider mutation."""
        event = AuditEvent(
            event_type=AuditEventType.SYSTEM_EVENT,
            severity=AuditSeverity.INFO,
            message=f"admin_provider_{action}",
            user_id=operator_id,
            metadata={
                "provider_id": provider_id,
                "action": action,
                **(metadata or {}),
            },
        )
        self._audit.log_audit_event(event)

    def list_providers(
        self,
        provider_filter: AdminProviderFilter,
        operator_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List providers with admin filtering."""
        names = self._registry.get_all_provider_names()
        providers: List[Dict[str, Any]] = []
        for name in names:
            status = self._registry.get_provider_status(name)
            endpoint = self._registry.get_provider_endpoint(name)
            if provider_filter.available_only and (not status or not status.is_available):
                continue
            if provider_filter.capability and (not status or provider_filter.capability not in status.capabilities):
                continue
            registration = self._registry._provider_registrations.get(name)
            providers.append(
                {
                    "name": name,
                    "is_available": status.is_available if status else False,
                    "health_status": status.health_status.value if status else "unknown",
                    "has_api_key": status.has_api_key if status else False,
                    "capabilities": [c.value for c in status.capabilities] if status else [],
                    "category": registration.category if registration else "unknown",
                    "tenant_scoped": getattr(endpoint, "tenant_scoped", False),
                }
            )
        self._audit_mutation(
            action="list",
            provider_id=None,
            operator_id=operator_id,
            metadata={"count": len(providers)},
        )
        return providers

    def get_provider_status(
        self,
        provider_id: str,
        operator_id: Optional[str] = None,
    ) -> Optional[ProviderStatus]:
        """Get provider status with audit logging."""
        status = self._registry.get_provider_status(provider_id)
        if status:
            self._audit_mutation(
                action="read_status",
                provider_id=provider_id,
                operator_id=operator_id,
            )
        return status

    def register_provider_endpoint(
        self,
        endpoint: ProviderEndpoint,
        *,
        operator_id: Optional[str] = None,
    ) -> ProviderEndpoint:
        """Register a provider endpoint with audit logging."""
        endpoint = self._registry.register_configured_endpoint(
            {
                "provider_id": endpoint.provider_id,
                "display_name": endpoint.display_name,
                "endpoint_type": endpoint.endpoint_type.value if hasattr(endpoint.endpoint_type, "value") else str(endpoint.endpoint_type),
                "base_url": endpoint.base_url,
                "api_key_env": endpoint.api_key_env,
                "enabled": endpoint.enabled,
                "builtin": endpoint.builtin,
                "tenant_scoped": endpoint.tenant_scoped,
                "timeout_seconds": endpoint.timeout_seconds,
                "supports_streaming": endpoint.supports_streaming,
                "supports_embeddings": endpoint.supports_embeddings,
                "supports_models_endpoint": endpoint.supports_models_endpoint,
                "fallback_eligible": endpoint.fallback_eligible,
                "capabilities": list(endpoint.capabilities),
                "default_model": endpoint.default_model,
                "metadata": dict(endpoint.metadata),
            }
        )
        self._audit_mutation(
            action="register_endpoint",
            provider_id=endpoint.provider_id,
            operator_id=operator_id,
            metadata={"display_name": endpoint.display_name},
        )
        return endpoint

    def register_openai_compatible_endpoint(
        self,
        provider_id: str,
        display_name: str,
        *,
        base_url: str,
        api_key_env: Optional[str] = None,
        supports_streaming: bool = True,
        supports_embeddings: bool = False,
        supports_models_endpoint: bool = True,
        capabilities: Optional[List[str]] = None,
        default_model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        operator_id: Optional[str] = None,
    ) -> ProviderEndpoint:
        """Register an OpenAI-compatible endpoint with audit logging."""
        endpoint = self._registry.register_openai_compatible_endpoint(
            provider_id=provider_id,
            display_name=display_name,
            base_url=base_url,
            api_key_env=api_key_env,
            supports_streaming=supports_streaming,
            supports_embeddings=supports_embeddings,
            supports_models_endpoint=supports_models_endpoint,
            capabilities=capabilities,
            default_model=default_model,
            metadata=metadata,
        )
        self._audit_mutation(
            action="register_openai_compatible",
            provider_id=provider_id,
            operator_id=operator_id,
            metadata={"display_name": display_name, "base_url": base_url},
        )
        return endpoint

    def get_system_status(
        self,
        operator_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get overall provider system status with audit logging."""
        status = self._registry.get_system_status()
        self._audit_mutation(
            action="system_status",
            provider_id=None,
            operator_id=operator_id,
        )
        return status

    def get_registered_models(
        self,
        provider_id: str,
        healthy_only: bool = True,
        operator_id: Optional[str] = None,
    ) -> List[str]:
        """Get registered models for a provider with audit logging."""
        models = self._registry.get_registered_models(provider_id, healthy_only=healthy_only)
        self._audit_mutation(
            action="list_models",
            provider_id=provider_id,
            operator_id=operator_id,
            metadata={"model_count": len(models)},
        )
        return models
