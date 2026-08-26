"""
Production model settings API routes.

These routes back the Karen AI theme "Model" settings tab with persisted
provider selection, encrypted API key storage, and local model discovery.
"""

from __future__ import annotations

import re
import asyncio
import json
import logging
import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ai_karen_engine.auth.session import get_current_user


from ai_karen_engine.config.llm_provider_config import (
    AuthenticationType,
    DEFAULT_OLLAMA_BASE_URL,
    MODEL_SETTINGS_PROVIDER_ORDER,
    ProviderAuthentication,
    ProviderConfig,
    ProviderEndpoint,
    ProviderLimits,
    ProviderModel,
    ProviderType,
    get_provider_config_manager,
    get_provider_execution_spec,
    is_docker,
)
from ai_karen_engine.core.model_runtime.model_discovery_service import (
    get_model_discovery_service,
)
from ai_karen_engine.integrations.llm_registry import get_registry
from ai_karen_engine.services.formatting.settings_manager import get_settings_manager
from ai_karen_engine.core.security.secrets.secrets import get_secret_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings/model", tags=["model-settings"])
LEGACY_OLLAMA_IN_STACK_URL = "http://ollama:11434"
OLLAMA_HOST_RUNTIME = "host"
OLLAMA_CONTAINER_RUNTIME = "container"
DEFAULT_OLLAMA_CONTAINER_BASE_URL = "http://ollama:11434"
OLLAMA_RUNTIME_CACHE_TTL_SECONDS = 10.0
_ollama_runtime_status_cache: Dict[str, tuple[float, "RuntimeOptionPayload"]] = {}

PROVIDER_DOC_URLS = {
    "openai": "https://platform.openai.com/docs",
    "gemini": "https://ai.google.dev/gemini-api/docs",
    "anthropic": "https://docs.anthropic.com/en/api/messages",
    "meta": "https://www.llama.com/docs/overview/",
    "deepseek": "https://api-docs.deepseek.com/",
    "azure": "https://learn.microsoft.com/en-us/azure/ai-services/openai/reference",
    "amazon-nova": "https://docs.aws.amazon.com/nova/latest/userguide/getting-started.html",
    "moonshot": "https://platform.moonshot.ai/docs/api-reference",
    "mistral": "https://docs.mistral.ai/",
    "groq": "https://console.groq.com/docs/overview",
    "xai": "https://docs.x.ai/docs/overview",
    "qwen": "https://www.alibabacloud.com/help/en/model-studio/developer-reference/compatibility-of-openai-with-dashscope",
    "zai": "https://docs.z.ai/api-reference/introduction",
    "siliconflow": "https://docs.siliconflow.cn/en/api-reference/chat-completions/chat-completions",
    "together": "https://docs.together.ai/docs/chat-overview",
    "fireworks": "https://docs.fireworks.ai/api-reference/post-chatcompletions",
    "deepinfra": "https://deepinfra.com/docs/openai_api",
    "huggingface": "https://huggingface.co/docs/api-inference/index",
    "cohere": "https://docs.cohere.com/docs/chat-api",
    "novita": "https://novita.ai/docs/api-reference/model-apis-llm-create-chat-completion",
    "gmi-cloud": "https://docs.gmicloud.ai/",
    "ollama": "https://github.com/ollama/ollama/blob/main/docs/api.md",
}

SECRET_NAMES = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "meta": "META_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "amazon-nova": "AWS_BEDROCK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "xai": "XAI_API_KEY",
    "qwen": "QWEN_API_KEY",
    "zai": "ZAI_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
}


class ProviderModelPayload(BaseModel):
    id: str
    name: str
    family: str
    capabilities: List[str]
    size_gb: Optional[float] = None
    is_installed: bool = False


class ProviderPayload(BaseModel):
    id: str
    display_name: str
    description: str
    type: str
    provider_type: Optional[str] = None
    icon_name: str
    doc_url: str
    supports_model_discovery: bool
    supports_base_url_override: bool
    default_base_url: Optional[str] = None
    requires_api_key: bool = False
    api_key_status: str  # missing, configured, masked
    api_key_configured: bool = False
    api_key_env_var: Optional[str] = None
    models: List[ProviderModelPayload]
    selected_model: Optional[str] = None
    base_url: Optional[str] = None
    api_key_header: Optional[str] = "Authorization"
    api_key_prefix: Optional[str] = "Bearer"
    custom_headers: Optional[Dict[str, str]] = None
    runtime_options: Optional[List[RuntimeOptionPayload]] = None
    is_configured: bool = False
    healthy: bool = True
    user_selectable: bool = True
    enabled: bool = True
    policy_allowed: bool = True
    policy_rejection_reason: Optional[str] = None
    runtime_engine: Optional[str] = None
    supports_streaming: bool = True
    supports_tools: bool = False
    degraded_reason: Optional[str] = None
    required_config_fields: List[str] = Field(default_factory=list)
    safe_diagnostic_metadata: Dict[str, Any] = Field(default_factory=dict)


class ModelSettingsResponse(BaseModel):
    providers: List[ProviderPayload]
    selected_provider: str
    selected_model: str
    active_provider: str
    active_model: str
    default_provider: str = "builtin_transformers"
    default_model: str = "auto"
    fallback_hierarchy: List[str]


class ModelSettingsUpdateRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    api_key_header: Optional[str] = None
    api_key_prefix: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None


class ProviderModelsResponse(BaseModel):
    provider: str
    base_url: Optional[str] = None
    models: List[ProviderModelPayload]
    discovered_at: str


class ProviderSettingsValidationRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class ExpressionEngineStatus(BaseModel):
    enabled: bool
    fallback_eligible: bool
    type: str
    note: Optional[str] = None
    base_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExpressionSettingsResponse(BaseModel):
    active_engine: str
    enabled_engines: List[str]
    fallback_order: List[str]
    allow_third_party: bool
    allow_external: bool
    engines: Dict[str, ExpressionEngineStatus]


class ExpressionSettingsUpdateRequest(BaseModel):
    active_engine: Optional[str] = None
    enabled_engines: Optional[List[str]] = None
    fallback_order: Optional[List[str]] = None
    allow_third_party: Optional[bool] = None
    allow_external: Optional[bool] = None
    engine_configs: Optional[Dict[str, Dict[str, Any]]] = None


@router.get("/expression", response_model=ExpressionSettingsResponse)
async def get_expression_settings(
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get the current expression engine settings."""
    try:
        from ai_karen_engine.config.config_manager import config_manager
        from ai_karen_engine.core.expression.settings import ExpressionSettings

        # Always use the standardized defaults as base
        defaults = ExpressionSettings()
        expr_cfg = config_manager.get_config_value("expression", default={})

        # Build response, preferring persisted config over code defaults
        engines_data = {}
        for eid, cfg in defaults.engines.items():
            persistent_cfg = expr_cfg.get("engines", {}).get(eid, {})
            engines_data[eid] = {
                "enabled": persistent_cfg.get("enabled", cfg.enabled),
                "fallback_eligible": persistent_cfg.get(
                    "fallback_eligible", cfg.fallback_eligible
                ),
                "type": cfg.type,
                "note": persistent_cfg.get("note") or cfg.note,
                "base_url": persistent_cfg.get("base_url") or cfg.base_url,
                "metadata": persistent_cfg.get("metadata") or cfg.metadata or {},
            }

        return {
            "active_engine": expr_cfg.get("active_engine", defaults.active_engine),
            "enabled_engines": expr_cfg.get(
                "enabled_engines", [e for e, c in engines_data.items() if c["enabled"]]
            ),
            "fallback_order": expr_cfg.get("fallback_order", defaults.engine_fallback_order),
            "allow_third_party": expr_cfg.get("policies", {}).get(
                "allow_third_party", defaults.policies.allow_third_party_engines
            ),
            "allow_external": expr_cfg.get("policies", {}).get(
                "allow_external", defaults.policies.allow_external_engines
            ),
            "engines": engines_data,
        }
    except Exception as e:
        logger.exception(f"Failed to get expression settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/expression", response_model=ExpressionSettingsResponse)
async def update_expression_settings(
    request: ExpressionSettingsUpdateRequest,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update the expression engine settings."""
    logger.info(f"Updating expression settings: {request}")
    # check if user is admin
    roles = (current_user.get("roles", []) if isinstance(current_user, dict) else getattr(current_user, "roles", []))
    if "admin" not in roles and "super_admin" not in roles:
        logger.warning(f"Unauthorized expression settings update attempt by {current_user}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to update expression settings",
        )

    from ai_karen_engine.config.config_manager import config_manager

    expr_cfg = config_manager.get_config_value("expression", default={})
    logger.debug(f"Current expression config: {expr_cfg}")

    try:
        if request.active_engine is not None:
            expr_cfg["active_engine"] = request.active_engine

        if request.enabled_engines is not None:
            expr_cfg["enabled_engines"] = request.enabled_engines

        if request.fallback_order is not None:
            # Enforce max 4 engines + Emergency Static rule implicitly in gateway
            expr_cfg["fallback_order"] = request.fallback_order

        if request.engine_configs is not None:
            current_engines = expr_cfg.get("engines", {})
            for eid, updates in request.engine_configs.items():
                existing = current_engines.get(eid, {})
                # Deep merge simple fields and metadata
                current_engines[eid] = {**existing, **updates}
                if "metadata" in updates and "metadata" in existing:
                     current_engines[eid]["metadata"] = {**existing["metadata"], **updates["metadata"]}
            expr_cfg["engines"] = current_engines
        if request.allow_third_party is not None or request.allow_external is not None:
            policies = expr_cfg.get("policies", {})
            if request.allow_third_party is not None:
                policies["allow_third_party"] = request.allow_third_party
            if request.allow_external is not None:
                policies["allow_external"] = request.allow_external
            expr_cfg["policies"] = policies

        from ai_karen_engine.config.config_manager import update_config
        logger.info(f"Saving updated expression config: {expr_cfg}")
        update_config({"expression": expr_cfg})

        return await get_expression_settings(current_user=current_user)
    except Exception as e:
        logger.exception(f"Failed to update expression settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ProviderSettingsValidationResponse(BaseModel):
    provider: str
    valid: bool
    message: str
    models_discovered: Optional[int] = None


class OllamaPullRequest(BaseModel):
    model: str
    base_url: Optional[str] = None


class RuntimeOptionPayload(BaseModel):
    source: str
    label: str


class CustomProviderTemplate(BaseModel):
    id: str
    display_name: str
    description: str
    default_base_url: Optional[str] = None
    icon_name: str = "openai"
    doc_url: str = "https://platform.openai.com/docs/api-reference"
    supports_model_discovery: bool = True
    supports_base_url_override: bool = True


CUSTOM_PROVIDER_TEMPLATES = [
    CustomProviderTemplate(
        id="ollama",
        display_name="Ollama",
        description="Local Ollama server (OpenAI-compatible endpoint)",
        default_base_url="http://host.docker.internal:11434/v1",
        icon_name="ollama",
    ),
    CustomProviderTemplate(
        id="lm-studio",
        display_name="LM Studio",
        description="LM Studio local server",
        default_base_url="http://localhost:1234/v1",
        icon_name="openai",
    ),
    CustomProviderTemplate(
        id="vllm-openai",
        display_name="vLLM (OpenAI API)",
        description="Remote or local vLLM OpenAI-compatible server",
        icon_name="vllm",
    ),
]


@router.get("", response_model=ModelSettingsResponse)
async def get_model_settings(
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get all model settings including provider details."""
    return await build_model_settings_payload()


@router.put("", response_model=ModelSettingsResponse)
async def update_model_settings(
    request: ModelSettingsUpdateRequest,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update primary provider, model, or specific provider settings."""

    # check if user is admin
    roles = (current_user.get("roles", []) if isinstance(current_user, dict) else getattr(current_user, "roles", []))
    if "admin" not in roles and "super_admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to update model settings",
        )

    settings = get_settings_manager()
    provider_manager = get_provider_config_manager()

    if request.provider:
        normalized_provider = _normalize_provider_id(request.provider)
        settings.set_setting("provider", normalized_provider, save=False)

    if request.model:
        settings.set_setting("model", request.model, save=False)
        settings.set_setting("last_selected_model", request.model, save=False)

    if request.provider and request.model:
        settings.set_setting(
            f"model_providers.{_normalize_provider_id(request.provider)}.last_model",
            request.model,
            save=False,
        )

    if request.base_url is not None:
        if request.provider:
            provider_id = _normalize_provider_id(request.provider)
            settings.set_setting(
                f"model_providers.{provider_id}.base_url",
                request.base_url,
                save=False,
            )
            # Also update the ProviderConfigManager for persistence across reloads
            try:
                provider_config = provider_manager.get_provider(provider_id)
                if provider_config and provider_config.endpoint:
                    # Update the dataclass field
                    provider_config.endpoint.base_url = request.base_url
                    provider_manager.update_provider(provider_id, {"endpoint": provider_config.endpoint})
            except Exception as e:
                logger.warning(f"Failed to update provider config for {provider_id}: {e}")

    if request.api_key is not None or request.clear_api_key:
        if not request.provider:
            raise HTTPException(
                status_code=400, detail="Provider ID is required when setting API key"
            )

        provider_id = _normalize_provider_id(request.provider)
        secret_manager = get_secret_manager()
        # Dynamically determine secret name if not in static mapping
        secret_name = SECRET_NAMES.get(provider_id) or f"{provider_id.upper().replace('-', '_')}_API_KEY"

        if secret_name:
            if request.clear_api_key:
                secret_manager.delete_secret(secret_name)
            else:
                secret_manager.set_secret(secret_name, request.api_key, description=f"{provider_id} API key")
            
            # CRITICAL: Invalidate the registry cache so the new key is picked up immediately
            try:
                from ai_karen_engine.integrations.llm_registry import get_registry
                get_registry().invalidate_provider_cache(provider_id)
                logger.info(f"Invalidated provider cache for {provider_id} due to API key update")
            except Exception as e:
                logger.warning(f"Failed to invalidate provider cache for {provider_id}: {e}")

    if request.api_key_header is not None:
        provider_id = _normalize_provider_id(request.provider)
        settings.set_setting(
            f"model_providers.{provider_id}.api_key_header",
            request.api_key_header,
            save=False,
        )
        # Persist to ProviderConfigManager
        try:
            provider_config = provider_manager.get_provider(provider_id)
            if provider_config and provider_config.authentication:
                provider_config.authentication.api_key_header = request.api_key_header
                provider_manager.update_provider(provider_id, {"authentication": provider_config.authentication})
        except: pass
        
        # Trigger cache invalidation for header changes too
        try:
            from ai_karen_engine.integrations.llm_registry import get_registry
            get_registry().invalidate_provider_cache(provider_id)
        except: pass

    if request.api_key_prefix is not None:
        provider_id = _normalize_provider_id(request.provider)
        settings.set_setting(
            f"model_providers.{provider_id}.api_key_prefix",
            request.api_key_prefix,
            save=False,
        )
        # Persist to ProviderConfigManager
        try:
            provider_config = provider_manager.get_provider(provider_id)
            if provider_config and provider_config.authentication:
                provider_config.authentication.api_key_prefix = request.api_key_prefix
                provider_manager.update_provider(provider_id, {"authentication": provider_config.authentication})
        except: pass

        # Trigger cache invalidation for prefix changes
        try:
            from ai_karen_engine.integrations.llm_registry import get_registry
            get_registry().invalidate_provider_cache(provider_id)
        except: pass

    if request.custom_headers is not None:
        provider_id = _normalize_provider_id(request.provider)
        settings.set_setting(
            f"model_providers.{provider_id}.custom_headers",
            request.custom_headers,
            save=False,
        )
        # Persist to ProviderConfigManager
        try:
            provider_config = provider_manager.get_provider(provider_id)
            if provider_config and provider_config.authentication:
                provider_config.authentication.custom_headers = request.custom_headers
                provider_manager.update_provider(provider_id, {"authentication": provider_config.authentication})
        except: pass

        # Trigger cache invalidation for custom header changes
        try:
            from ai_karen_engine.integrations.llm_registry import get_registry
            get_registry().invalidate_provider_cache(provider_id)
        except: pass

    settings._save_settings()
    
    # Final global invalidation to be sure
    if request.provider:
        try:
            from ai_karen_engine.integrations.llm_registry import get_registry
            get_registry().invalidate_provider_cache(_normalize_provider_id(request.provider))
        except: pass

    return await build_model_settings_payload()


@router.get("/providers/{provider_id}/models", response_model=ProviderModelsResponse)
async def get_provider_models(
    provider_id: str,
    base_url: Optional[str] = None,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Discover models for a specific provider."""
    try:
        discovery_service = get_model_discovery_service()
        provider_manager = get_provider_config_manager()

        # Normalize provider ID
        normalized_id = _normalize_provider_id(provider_id)

        # Get provider config
        provider = provider_manager.get_provider(normalized_id)
        if not provider:
            # Try to find by display name or other matches if ID doesn't hit directly
            all_providers = provider_manager.list_providers()
            for p in all_providers:
                if _normalize_provider_id(p.name) == normalized_id:
                    provider = p
                    break

        p_models = []

        # 1. Add static models from config if found
        if provider:
            for m in (provider.models or []):
                p_models.append(
                    ProviderModelPayload(
                        id=m.id,
                        name=m.name,
                        family=m.family or "unknown",
                        capabilities=list(m.capabilities or []),
                        is_installed=True,
                    )
                )

        # 2. Add models from discovery service
        discovery_models = []
        try:
            discovery_models = await discovery_service.get_models_async(runtime=normalized_id)
        except Exception as e:
            logger.warning(f"Model discovery failed for {normalized_id}: {e}")

        # 3. Special handling for dynamic discovery (Ollama and OpenAI-compatible/vLLM)
        dynamic_model_names = []
        try:
            target_url = base_url
            if not target_url and provider and provider.endpoint:
                target_url = provider.endpoint.base_url

            if target_url:
                if normalized_id == "ollama":
                    from ai_karen_engine.integrations.providers.ollama_provider import OllamaProvider
                    ollama = OllamaProvider(base_url=target_url, timeout=2, max_retries=0)
                    loop = asyncio.get_running_loop()
                    dynamic_model_names = await loop.run_in_executor(None, ollama.get_models)
                elif provider and provider.provider_type.value in ["remote", "hybrid"]:
                    # Try generic OpenAI compatible discovery
                    from ai_karen_engine.integrations.providers.openai_compatible_provider import OpenAICompatibleProvider
                    
                    # Prepare API key if available
                    api_key = None
                    if provider and provider.name:
                        api_key = provider_manager.get_api_key(provider.name)
                        
                    client = OpenAICompatibleProvider(base_url=target_url, api_key=api_key, timeout=2, max_retries=0)
                    loop = asyncio.get_running_loop()
                    dynamic_model_names = await loop.run_in_executor(None, client.get_models)

                for name in dynamic_model_names:
                    if not any(m.id == name for m in p_models):
                        p_models.append(ProviderModelPayload(
                            id=name,
                            name=name,
                            family=normalized_id,
                            capabilities=["text", "chat_completion", "streaming"],
                            is_installed=True
                        ))
        except Exception as e:
            logger.warning(f"Dynamic model discovery failed for {normalized_id}: {e}")

        for dm in discovery_models:
            if not any(m.id == dm.model_id for m in p_models):
                p_models.append(
                    ProviderModelPayload(
                        id=dm.model_id,
                        name=dm.display_name or dm.name,
                        family=dm.model_type or "unknown",
                        capabilities=list(dm.capabilities),
                        size_gb=float(dm.size_bytes / (1024**3))
                        if dm.size_bytes
                        else None,
                        is_installed=bool(dm.weights_present),
                    )
                )

        return {
            "provider": provider_id,
            "base_url": base_url,
            "models": p_models,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception(f"Failed to get models for provider {provider_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate")
async def validate_provider_settings(
    request: ProviderSettingsValidationRequest,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Validate provider settings (API key, base URL)."""
    try:
        provider_id = _normalize_provider_id(request.provider)
        
        # Simple validation for now - check if API key is provided if required
        # and try to discover models if base_url is provided.
        
        if request.api_key and len(request.api_key) < 3:
             return {"valid": False, "message": "Invalid API key format"}

        # Return success with count if we can find any models
        # (This is a lightweight check)
        discovery_service = get_model_discovery_service()
        models = discovery_service.get_models(runtime=provider_id)
        
        return {
            "valid": True, 
            "message": "Settings verified",
            "models_discovered": len(models)
        }
        
    except Exception as e:
        logger.error(f"Validation failed for {request.provider}: {e}")
        return {"valid": False, "message": f"Validation failed: {str(e)}"}


async def build_model_settings_payload() -> Dict[str, Any]:
    """Build the canonical ModelSettingsResponse dictionary."""
    settings = get_settings_manager()
    provider_manager = get_provider_config_manager()
    discovery_service = get_model_discovery_service()

    all_providers = provider_manager.list_providers()
    active_provider_id = _normalize_provider_id(settings.get_setting("provider"))
    active_model = settings.get_setting("model")

    providers_payload = []
    for provider in all_providers:
        # 1. Start with known models from provider configuration
        p_models = []
        for m in (provider.models or []):
             p_models.append(ProviderModelPayload(
                id=m.id,
                name=m.name,
                family=m.family or "unknown",
                capabilities=list(m.capabilities or []),
                is_installed=True
            ))

        # 2. Add models from discovery service if applicable
        discovery_error = None
        discovery_models = []

        try:
            discovery_models = await discovery_service.get_models_async(runtime=provider.name)
        except Exception as e:
            logger.warning(
                f"Model discovery failed for provider {provider.name}: {e}",
                exc_info=True
            )
            discovery_error = str(e)
            # Continue with empty models from discovery

        for dm in discovery_models:
            if not any(m.id == dm.model_id for m in p_models):
                p_models.append(ProviderModelPayload(
                    id=dm.model_id,
                    name=dm.display_name or dm.name,
                    family=dm.model_type or "unknown",
                    capabilities=list(dm.capabilities),
                    size_gb=float(dm.size_bytes / (1024**3)) if dm.size_bytes else None,
                    is_installed=bool(dm.weights_present)
                ))

        # Endpoint settings from storage
        override = _get_provider_override(provider.name)
        
        # Runtime options for local providers
        runtime_options = None
        if provider.name == "ollama":
            runtime_options = await _get_ollama_runtime_options()

        api_key_status = _get_api_key_status(provider.name, provider)
        
        # Determine if provider is configured and healthy
        from ai_karen_engine.config.runtime_provider_manager import get_runtime_provider_manager
        runtime_manager = get_runtime_provider_manager()
        health_statuses = runtime_manager.get_all_provider_health()
        
        is_configured = api_key_status in ["configured", "not_required"]
        healthy = True
        degraded_reason = None
        
        health_info = health_statuses.get(provider.name)
        if health_info:
            healthy = health_info.is_healthy
            if not healthy:
                degraded_reason = health_info.error_message
            
        # Local providers like Ollama are only configured if they have available runtime options
        # or if a base_url has been manually set.
        if provider.name == "ollama" and not override.get("base_url"):
             if runtime_options and not any(opt.available for opt in runtime_options):
                 is_configured = False

        # Required config fields
        required_fields = []
        if provider.authentication and provider.authentication.type == AuthenticationType.API_KEY:
            required_fields.append("api_key")
        if _supports_base_url_override(provider):
            required_fields.append("base_url")

        execution_spec = get_provider_execution_spec(provider.name) or {}
        runtime_engine = str(
            execution_spec.get("runtime_engine")
            or provider.name.replace("builtin_", "")
        )
        if provider.name == "custom":
            runtime_engine = "openai_compatible"

        providers_payload.append(ProviderPayload(
            id=provider.name,
            display_name=provider.display_name,
            description=provider.description,
            type=provider.provider_type.value,
            provider_type=provider.provider_type.value,
            icon_name=provider.name if provider.name in {"openai", "gemini", "anthropic", "meta", "huggingface", "vllm", "ollama"} else "openai",
            doc_url=PROVIDER_DOC_URLS.get(provider.name, ""),
            supports_model_discovery=bool(execution_spec.get("supports_model_discovery")),
            supports_base_url_override=_supports_base_url_override(provider),
            default_base_url=provider.endpoint.base_url if provider.endpoint else None,
            requires_api_key=bool(provider.authentication and provider.authentication.type == AuthenticationType.API_KEY),
            api_key_status=api_key_status,
            api_key_configured=api_key_status == "configured",
            api_key_env_var=provider.authentication.api_key_env_var if provider.authentication else None,
            models=p_models,
            selected_model=_normalize_selected_model_for_provider(provider.name, override.get("last_model") or provider.default_model),
            base_url=override.get("base_url"),
            api_key_header=str(override.get("api_key_header", provider.authentication.api_key_header if provider.authentication else "Authorization")),
            api_key_prefix=str(override.get("api_key_prefix", provider.authentication.api_key_prefix if provider.authentication else "Bearer")),
            custom_headers=override.get("custom_headers"),
            runtime_options=runtime_options,
            is_configured=is_configured,
            healthy=healthy,
            user_selectable=bool(provider.priority > 0),
            enabled=bool(provider.enabled),
            policy_allowed=True,
            policy_rejection_reason=None,
            runtime_engine=runtime_engine,
            supports_streaming=bool(provider.capabilities and "streaming" in provider.capabilities),
            supports_tools=bool(provider.capabilities and "tool_use" in provider.capabilities),
            degraded_reason=degraded_reason,
            required_config_fields=required_fields,
            safe_diagnostic_metadata={
                "connection_target": override.get("base_url") or (provider.endpoint.base_url if provider.endpoint else "internal"),
                "is_docker": is_docker(),
                "execution_family": execution_spec.get("execution_family"),
                "adapter_class": execution_spec.get("adapter_class"),
                "adapter_module": execution_spec.get("adapter_module"),
                "runtime_engine": execution_spec.get("runtime_engine") or runtime_engine,
                "execution_notes": execution_spec.get("notes"),
            }
        ))

    return {
        "providers": providers_payload,
        "selected_provider": str(active_provider_id or "builtin_transformers"),
        "selected_model": str(active_model or "auto"),
        "active_provider": str(active_provider_id or "builtin_transformers"),
        "active_model": str(active_model or "auto"),
        "default_provider": "builtin_transformers",
        "default_model": "auto",
        "fallback_hierarchy": list(settings.get_setting("llm_providers.fallback_hierarchy") or [
            "builtin_transformers", "fallback", "openai", "gemini"
        ])
    }


def _normalize_provider_id(pid: Any) -> str:
    return str(pid or "").lower().replace("-", "_").replace(" ", "_")


def _get_provider_override(provider_name: str) -> Dict[str, Any]:
    settings = get_settings_manager()
    return settings.get_setting(f"model_providers.{provider_name}") or {}


def _get_api_key_status(provider_name: str, provider: ProviderConfig) -> str:
    if not provider.authentication or provider.authentication.type == AuthenticationType.NONE:
        return "not_required"
    
    secret_manager = get_secret_manager()
    secret_name = SECRET_NAMES.get(provider_name)
    if secret_name and secret_manager.get_secret(secret_name):
        return "configured"
    
    # Check env var
    env_var = provider.authentication.api_key_env_var
    if env_var and os.getenv(env_var):
        return "configured"
        
    return "missing"


def _get_saved_api_key(provider_name: str, provider: ProviderConfig) -> Optional[str]:
    secret_manager = get_secret_manager()
    secret_name = SECRET_NAMES.get(provider_name)
    if secret_name:
        return secret_manager.get_secret(secret_name)
    return None


def _normalize_base_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    # Ensure scheme
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def _normalize_ollama_base_url(url: str) -> str:
    """Ollama specific normalization (ensure /v1)"""
    if not url.endswith("/v1") and not url.endswith("/v1/"):
        return url.rstrip("/") + "/v1"
    return url


def _supports_base_url_override(provider: ProviderConfig) -> bool:
    return provider.provider_type in {ProviderType.LOCAL, ProviderType.HYBRID, ProviderType.CUSTOM} or provider.name in {"openai", "azure", "vllm"}


def _normalize_selected_model_for_provider(provider_name: str, model_id: Any) -> str:
    model_id = str(model_id or "").strip()
    if not model_id:
        return ""
    # Built-in providers often use absolute paths
    return model_id


def _is_custom_provider(provider: ProviderConfig) -> bool:
    return provider.capabilities is not None and "custom_endpoint" in provider.capabilities


def _infer_family(model_id: str) -> str:
    mid = model_id.lower()
    if "llama" in mid: return "llama"
    if "gpt" in mid: return "gpt"
    if "claude" in mid: return "claude"
    if "gemini" in mid: return "gemini"
    if "phi" in mid: return "phi"
    if "qwen" in mid: return "qwen"
    return "unknown"


async def _get_ollama_runtime_options() -> List["RuntimeOptionPayload"]:
    """Detect and return available Ollama runtimes."""
    options = []
    
    # Option 1: Host Ollama
    host_url = normalize_display_base_url(DEFAULT_OLLAMA_BASE_URL)
    host_available = await _probe_ollama_health(host_url)
    options.append(RuntimeOptionPayload(
        source=OLLAMA_HOST_RUNTIME,
        label="Local Host (System Service)",
        available=host_available,
        base_url=host_url,
        status="Online" if host_available else "Not detected",
        message="Running as a service on your machine. Best for performance." if host_available else "Ensure Ollama is installed and running on your PC.",
        setup_command="curl -fsSL https://ollama.com/install.sh | sh" if not host_available else None
    ))

    # Option 2: Container Ollama
    container_url = normalize_display_base_url(DEFAULT_OLLAMA_CONTAINER_BASE_URL)
    container_available = await _probe_ollama_health(container_url)
    options.append(RuntimeOptionPayload(
        source=OLLAMA_CONTAINER_RUNTIME,
        label="Docker Container",
        available=container_available,
        base_url=container_url,
        status="Online" if container_available else "Not detected",
        message="Running inside the Kari Docker stack. Isolated and portable." if container_available else "Requires 'ollama' service in docker-compose.yml.",
        setup_command="docker compose up -d ollama" if not container_available else None
    ))

    return options


async def _probe_ollama_health(base_url: str) -> bool:
    """Probe an Ollama endpoint for health."""
    try:
        # Strip /v1 for health check if present
        health_url = base_url.replace("/v1", "") + "/api/tags"
        
        loop = asyncio.get_event_loop()
        def _check():
            try:
                with urlopen(health_url, timeout=1.0) as response:
                    return response.getcode() == 200
            except:
                return False
                
        return await loop.run_in_executor(None, _check)
    except:
        return False


def normalize_display_base_url(address: str) -> str:
    """Normalize display base URL by removing /api prefix if present."""
    cleaned = address.strip()
    # Remove /api prefix if present
    cleaned = re.sub(r'^(.+?)/api/', r'\1/', cleaned)
    # Remove trailing slash
    cleaned = re.sub(r'/$', '', cleaned)
    return cleaned


@router.post("/providers/custom", response_model=ModelSettingsResponse)
async def add_custom_openai_provider(
    request: Dict[str, Any],
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Add a new custom OpenAI-compatible provider."""
    # Simplified version for now
    name = request.get("name")
    display_name = request.get("display_name")
    base_url = request.get("base_url")
    model_id = request.get("model")
    
    if not name or not base_url or not model_id:
        raise HTTPException(status_code=400, detail="Name, base_url, and model are required")

    provider_manager = get_provider_config_manager()
    settings = get_settings_manager()
    
    normalized_name = _normalize_provider_id(name)
    
    # Create config
    provider = ProviderConfig(
        name=normalized_name,
        display_name=display_name or name,
        description=request.get("description", f"Custom provider: {name}"),
        provider_type=ProviderType.CUSTOM,
        endpoint=ProviderEndpoint(
            base_url=base_url,
        ),
        authentication=ProviderAuthentication(
            type=AuthenticationType.API_KEY,
            api_key_env_var=f"{normalized_name.upper().replace('-', '_')}_API_KEY",
            api_key_header=request.get("api_key_header", "Authorization"),
            api_key_prefix=request.get("api_key_prefix", "Bearer"),
        ),
        models=[
            ProviderModel(
                id=model_id,
                name=model_id,
                family=_infer_family(model_id),
                capabilities={"text"},
                supports_streaming=True,
            )
        ],
        default_model=model_id,
        capabilities={"custom_endpoint"},
    )

    provider_manager.add_provider(provider)
    
    # Invalidate registry cache for the new provider
    try:
        from ai_karen_engine.integrations.llm_registry import get_registry
        get_registry().invalidate_provider_cache(normalized_name)
    except: pass

    settings.set_setting("provider", provider.name, save=False)
    settings.set_setting("model", model_id, save=False)
    settings.set_setting(f"model_providers.{provider.name}.base_url", base_url, save=False)
    # Save auth metadata to general settings as well for UI display consistency
    settings.set_setting(f"model_providers.{provider.name}.api_key_header", provider.authentication.api_key_header, save=False)
    settings.set_setting(f"model_providers.{provider.name}.api_key_prefix", provider.authentication.api_key_prefix, save=False)
    
    settings._save_settings()
    
    return await build_model_settings_payload()


class ProviderSettingsValidationResponse(BaseModel):
    provider: str
    valid: bool
    message: str
    models_discovered: Optional[int] = None


class OllamaPullRequest(BaseModel):
    model: str
    base_url: Optional[str] = None


class RuntimeOptionPayload(BaseModel):
    source: str
    label: str
    available: bool
    base_url: str
    status: str
    message: str
    setup_command: Optional[str] = None
