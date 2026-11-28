"""
Production model settings API routes.

These routes back the Karen AI theme "Model" settings tab with persisted
provider selection, encrypted API key storage, and local model discovery.
"""

from __future__ import annotations

import re
import asyncio
import uuid
import json
import logging
import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ai_karen_engine.auth.rbac_middleware import Permission, require_permission
from ai_karen_engine.services.admin.admin_provider_service import AdminProviderService

from ai_karen_engine.auth.session import get_current_user


from ai_karen_engine.config.llm_provider_config import (
    AuthenticationType,
    DEFAULT_OLLAMA_BASE_URL,
    MODEL_SETTINGS_PROVIDER_ORDER,
    OPENAI_COMPATIBLE_PROVIDER_DEFAULTS,
    ProviderAuthentication,
    ProviderConfig,
    ProviderEndpoint,
    ProviderLimits,
    ProviderModel,
    ProviderType,
    get_provider_config_manager,
    get_provider_execution_spec,
    is_docker,
    resolve_provider_name,
)
from ai_karen_engine.core.model_runtime.model_discovery_service import (
    get_model_discovery_service,
)
from ai_karen_engine.core.model_runtime.ollama_model_inventory import (
    resolve_ollama_inventory_endpoint,
)
from ai_karen_engine.integrations.providers.ollama_provider import (
    discover_installed_ollama_models,
)
from ai_karen_engine.integrations.llm_registry import get_registry
from ai_karen_engine.services.formatting.settings_manager import get_settings_manager
from ai_karen_engine.core.security.secrets.secrets import get_secret_manager
from ai_karen_engine.config.provider_authentication import (
    AuthenticationStatus,
    get_provider_auth_manager,
)

logger = logging.getLogger(__name__)

from ai_karen_engine.database.models.identity_vault import (
    CredentialCreate,
    CredentialSecretCreate,
    ProviderDefinitionCreate,
    ProviderType as VaultProviderType,
)
from ai_karen_engine.services.identity_vault.credential_vault_service import (
    get_credential_vault_service,
)

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
    "nous": "https://portal.nousresearch.com/api-docs",
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
    "nous": "NOUS_API_KEY",
}


class ProviderModelPayload(BaseModel):
    id: str
    name: str
    family: str
    capabilities: List[str]
    size_gb: Optional[float] = None
    is_installed: bool = False
    source: Literal["configured_catalog", "local_runtime", "provider_live", "ollama_native"] = "configured_catalog"


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
    runtime_source: Optional[Literal["host", "container"]] = None
    runtime_options: Optional[List[RuntimeOptionPayload]] = None
    is_configured: bool = False
    # Missing observed status is unverified, never healthy by default.
    healthy: bool = False
    # Health state is distinct from whether execution is currently permitted.
    # Unknown means no completed provider probe, not an observed failure.
    health_status: str = "unknown"
    health_last_checked_at: Optional[datetime] = None
    user_selectable: bool = True
    enabled: bool = True
    chat_enabled: bool = True
    chat_model_visibility: Dict[str, bool] = Field(default_factory=dict)
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
    chat_response_mode: Literal["streaming_first", "auto", "non_streaming"] = "streaming_first"


class ModelSettingsUpdateRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    api_key_header: Optional[str] = None
    api_key_prefix: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None
    runtime_source: Optional[Literal["host", "container"]] = None
    chat_response_mode: Optional[Literal["streaming_first", "auto", "non_streaming"]] = None


class ProviderChatAccessRequest(BaseModel):
    """Workspace administrator's explicit chat picker publication settings."""

    model_config = ConfigDict(extra="forbid")
    provider_enabled: Optional[bool] = None
    chat_enabled: Optional[bool] = None
    model_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    model_enabled: Optional[bool] = None


class ProviderModelsResponse(BaseModel):
    provider: str
    base_url: Optional[str] = None
    models: List[ProviderModelPayload]
    discovery_status: Literal["ready", "catalog_only", "empty"] = "empty"
    inventory_source: Literal["configured_catalog", "local_runtime", "provider_live", "ollama_native", "mixed", "none"] = "none"
    live_discovery_failed: bool = False
    workspace_inventory_verified: bool = False
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
    available: bool
    base_url: str
    status: str
    message: str
    setup_command: Optional[str] = None


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



_MODEL_KEY_CREDENTIAL_TYPE = "model_api_key"
_MODEL_KEY_PROVIDER_MARKER = {"managed_for": _MODEL_KEY_CREDENTIAL_TYPE}


class ConsumerModelStorageReceipt(BaseModel):
    provider: str
    storage_enabled: bool
    runtime_authorized: bool = False


class ConsumerModelKeyCreate(BaseModel):
    """Personal credential ingress, with no caller-controlled tenant or endpoint."""

    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=2, max_length=64)
    api_key: SecretStr = Field(repr=False)


class ConsumerModelKeyReceipt(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    masked_hint: Optional[str] = None
    chat_consent_enabled: bool = False
    chat_consent_model_id: Optional[str] = None
    # Storage or consent is not a grant to run an external model.
    runtime_authorized: bool = False


class ConsumerModelKeyList(BaseModel):
    credentials: List[ConsumerModelKeyReceipt]
    limit: int
    offset: int


class ConsumerModelChatConsentRequest(BaseModel):
    """One authenticated owner action, with no caller-supplied tenant or key."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool
    model_id: Optional[str] = Field(default=None, max_length=255)


class ConsumerModelChatConsentReceipt(BaseModel):
    credential_id: uuid.UUID
    consent_enabled: bool
    model_id: Optional[str] = None
    # Consent is not RuntimePolicy authorization or external model readiness.
    runtime_authorized: bool = False


def _consumer_key_identity(user: Any) -> tuple[uuid.UUID, str]:
    """Use the authenticated user and tenant from get_current_user only."""
    if not isinstance(user, dict):
        raise HTTPException(status_code=403, detail="Authenticated identity required")
    actor = user.get("user_id")
    if (
        not isinstance(actor, str)
        or not actor
        or actor != actor.strip()
        or len(actor) > 255
    ):
        raise HTTPException(status_code=403, detail="Authenticated owner required")
    try:
        tenant = uuid.UUID(str(user.get("tenant_id") or ""))
    except (TypeError, AttributeError, ValueError):
        raise HTTPException(status_code=403, detail="Explicit UUID tenant required") from None
    return tenant, actor


def _consumer_key_material(secret: SecretStr) -> str:
    key = secret.get_secret_value()
    if (
        not key
        or key != key.strip()
        or len(key.encode("utf-8")) > 4096
        or any(ord(char) < 32 or ord(char) == 127 for char in key)
    ):
        raise HTTPException(status_code=422, detail="Invalid API key format")
    return key


def _eligible_personal_key_provider(provider_name: str) -> tuple[str, ProviderConfig]:
    """One configured-provider policy for admin provisioning and user key writes."""
    canonical = _normalize_provider_id(provider_name)
    provider = get_provider_config_manager().get_provider(canonical)
    if (
        canonical not in MODEL_SETTINGS_PROVIDER_ORDER
        or canonical in {"custom", "fallback"}
        or provider is None
        or provider.name != canonical
        or not provider.enabled
        or not provider.chat_enabled
        or provider.provider_type not in {ProviderType.EXTERNAL, ProviderType.HYBRID}
        or provider.authentication is None
        or provider.authentication.type != AuthenticationType.API_KEY
    ):
        raise HTTPException(
            status_code=403, detail="Personal credentials not permitted for provider"
        )
    return canonical, provider


def _provisioned_model_key_provider(definition: Any, provider_name: str) -> bool:
    """Recognize only the canonical system-managed tenant provider namespace."""
    return bool(
        definition is not None
        and definition.provider_id == provider_name
        and definition.enabled is True
        and definition.is_system is True
        and str(getattr(definition.provider_type, "value", definition.provider_type))
        == VaultProviderType.API_KEY.value
        and definition.config == _MODEL_KEY_PROVIDER_MARKER
    )


@router.post(
    "/credentials/providers/{provider_id}/provision",
    response_model=ConsumerModelStorageReceipt,
)
async def provision_consumer_model_key_provider(
    provider_id: str,
    current_user: Any = Depends(require_permission(Permission.ADMIN_PROVIDERS_MANAGE)),
) -> ConsumerModelStorageReceipt:
    """Permit personal key storage only after an authorized tenant admin grants it.

    This creates an Identity Vault provider definition only. It does not
    authorize an external model, issue a key, or change chat runtime policy.
    """
    tenant, actor = _consumer_key_identity(current_user)
    canonical, approved = _eligible_personal_key_provider(provider_id)
    vault = get_credential_vault_service()
    try:
        existing = await vault.get_provider(canonical, tenant)
        if existing is None:
            existing = await vault.create_provider(
                ProviderDefinitionCreate(
                    provider_id=canonical,
                    display_name=approved.display_name,
                    provider_type=VaultProviderType.API_KEY,
                    config=dict(_MODEL_KEY_PROVIDER_MARKER),
                    supported_capabilities=["chat"],
                    enabled=True,
                    is_system=True,
                ),
                tenant,
                actor,
            )
    except Exception as exc:
        logger.warning(
            "personal_model_provider_provisioning_unavailable",
            extra={"provider": canonical, "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503, detail="Tenant credential provider could not be provisioned"
        ) from None

    if not _provisioned_model_key_provider(existing, canonical):
        raise HTTPException(
            status_code=409,
            detail="Tenant provider definition conflicts with model key storage",
        )
    return ConsumerModelStorageReceipt(
        provider=canonical, storage_enabled=True, runtime_authorized=False
    )


def _consumer_key_receipt(record: Any, provider: str) -> ConsumerModelKeyReceipt:
    """Show saved owner consent distinctly from the unavailable execution grant."""
    metadata = getattr(record, "credential_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    consent = metadata.get("personal_model_chat_consent")
    selected_model = (
        consent.get("model_id")
        if isinstance(consent, dict) and consent.get("enabled") is True
        else None
    )
    if (
        not isinstance(selected_model, str)
        or not selected_model
        or selected_model != selected_model.strip()
        or selected_model == "auto"
        or len(selected_model) > 255
    ):
        selected_model = None
    return ConsumerModelKeyReceipt(
        id=record.id,
        provider=provider,
        status=str(getattr(record.status, "value", record.status)),
        masked_hint=record.masked_hint,
        chat_consent_enabled=selected_model is not None,
        chat_consent_model_id=selected_model,
        runtime_authorized=False,
    )


def _consumer_vault_error(exc: Exception) -> HTTPException:
    logger.warning(
        "consumer_model_vault_unavailable",
        extra={"error_type": type(exc).__name__},
    )
    return HTTPException(status_code=503, detail="Credential Vault unavailable")


@router.get("/credentials", response_model=ConsumerModelKeyList)
async def list_consumer_model_keys(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: Any = Depends(get_current_user),
) -> ConsumerModelKeyList:
    tenant, actor = _consumer_key_identity(current_user)
    vault = get_credential_vault_service()
    try:
        owned = await vault.list_owned_credentials(
            tenant, actor, limit=limit, offset=offset
        )
        providers = await vault.list_providers(tenant, limit=1000)
    except Exception as exc:
        raise _consumer_vault_error(exc) from None
    provider_names = {provider.id: provider.provider_id for provider in providers}
    return ConsumerModelKeyList(
        credentials=[
            _consumer_key_receipt(
                record, provider_names.get(record.provider_id, "unavailable")
            )
            for record in owned
        ],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/credentials", response_model=ConsumerModelKeyReceipt, status_code=201
)
async def create_consumer_model_key(
    payload: ConsumerModelKeyCreate,
    current_user: Any = Depends(get_current_user),
) -> ConsumerModelKeyReceipt:
    tenant, actor = _consumer_key_identity(current_user)
    key = _consumer_key_material(payload.api_key)
    # Reuse the exact provider policy enforced by the admin provisioning route.
    canonical, _ = _eligible_personal_key_provider(payload.provider)

    vault = get_credential_vault_service()
    try:
        definition = await vault.get_provider(canonical, tenant)
    except Exception as exc:
        raise _consumer_vault_error(exc) from None
    if not _provisioned_model_key_provider(definition, canonical):
        # A similarly named plugin or manually created Vault provider must
        # never authorize consumer model credential storage.
        raise HTTPException(
            status_code=409, detail="Tenant provider credential storage is not enabled"
        )

    try:
        result = await get_provider_auth_manager().validate_candidate_api_key(
            canonical, key
        )
    except Exception as exc:
        logger.warning(
            "consumer_model_key_probe_unavailable",
            extra={"provider": canonical, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503, detail="Provider validation unavailable") from None
    if result.status != AuthenticationStatus.VALID:
        raise HTTPException(
            status_code=422, detail="Provider did not verify the API key; nothing was saved"
        )

    try:
        record = await vault.create_owned_credential(
            CredentialCreate(
                name=f"Personal {canonical} model API key",
                provider_id=definition.id,
                credential_type=_MODEL_KEY_CREDENTIAL_TYPE,
                masked_hint=f"••••{key[-4:]}",
            ),
            [CredentialSecretCreate(secret_type="api_key", encrypted_value=key)],
            tenant,
            actor,
        )
    except Exception as exc:
        raise _consumer_vault_error(exc) from None
    return _consumer_key_receipt(record, canonical)


@router.post(
    "/credentials/{credential_id}/chat-consent",
    response_model=ConsumerModelChatConsentReceipt,
)
async def set_consumer_model_chat_consent(
    credential_id: uuid.UUID,
    payload: ConsumerModelChatConsentRequest,
    request: Request,
    current_user: Any = Depends(get_current_user),
) -> ConsumerModelChatConsentReceipt:
    """Persist a deliberately selected model for one owned personal key.

    Storage remains separate from RuntimePolicy authorization. The credential
    identifier is a resource locator only; the Vault checks its real owner,
    tenant, purpose, lifecycle and system-managed provider before committing.
    """
    tenant, actor = _consumer_key_identity(current_user)
    if payload.enabled and (
        not payload.model_id
        or payload.model_id != payload.model_id.strip()
        or payload.model_id == "auto"
    ):
        raise HTTPException(
            status_code=422,
            detail="An explicit model is required for personal chat consent",
        )
    correlation_id = str(
        getattr(request.state, "correlation_id", "") or uuid.uuid4()
    )
    try:
        updated = await get_credential_vault_service().set_owned_personal_model_chat_consent(
            credential_id=credential_id,
            tenant_id=tenant,
            user_id=actor,
            model_id=payload.model_id,
            enabled=payload.enabled,
            correlation_id=correlation_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid personal model consent selection",
        ) from None
    except PermissionError:
        raise HTTPException(
            status_code=409,
            detail="Personal model consent unavailable for this credential",
        ) from None
    except Exception as exc:
        raise _consumer_vault_error(exc) from None
    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Personal credential not found",
        )
    return ConsumerModelChatConsentReceipt(
        credential_id=credential_id,
        consent_enabled=payload.enabled,
        model_id=payload.model_id if payload.enabled else None,
        runtime_authorized=False,
    )


@router.post("/credentials/{credential_id}/revoke")
async def revoke_consumer_model_key(
    credential_id: uuid.UUID,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, bool]:
    tenant, actor = _consumer_key_identity(current_user)
    try:
        revoked = await get_credential_vault_service().revoke_owned_credential(
            credential_id, tenant, actor, reason="consumer_request"
        )
    except Exception as exc:
        raise _consumer_vault_error(exc) from None
    if not revoked:
        raise HTTPException(status_code=404, detail="Personal credential not found")
    return {"locally_revoked": True, "provider_revocation_verified": False}


@router.delete("/credentials/{credential_id}")
async def delete_consumer_model_key(
    credential_id: uuid.UUID,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, bool]:
    tenant, actor = _consumer_key_identity(current_user)
    try:
        deleted = await get_credential_vault_service().delete_owned_credential(
            credential_id, tenant, actor
        )
    except Exception as exc:
        raise _consumer_vault_error(exc) from None
    if not deleted:
        # The Vault refuses deletion while active references still exist.
        raise HTTPException(
            status_code=409, detail="Credential unavailable or has active bindings"
        )
    return {"locally_deleted": True, "provider_revocation_verified": False}


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

    # Vendor credentials may only be used with their documented endpoint.
    # A custom upstream must be registered under the governed custom-provider
    # workflow, never by redirecting a preconfigured vendor's bearer token.
    if request.provider == "nous" and request.base_url is not None:
        approved = OPENAI_COMPATIBLE_PROVIDER_DEFAULTS["nous"]["base_url"]
        if _discovery_url_key(request.base_url) != _discovery_url_key(approved):
            raise HTTPException(
                status_code=403,
                detail="Nous Portal API credentials require the approved Nous endpoint",
            )

    # Validate the selected runtime against backend-owned endpoints before
    # persisting any part of this settings update.
    if request.runtime_source is not None:
        if _normalize_provider_id(request.provider) != "ollama":
            raise HTTPException(status_code=400, detail="Runtime source is only supported for Ollama")
        options = await _get_ollama_runtime_options()
        option = next((item for item in options if item.source == request.runtime_source), None)
        if option is None or not option.available:
            raise HTTPException(status_code=409, detail="Selected Ollama runtime is unavailable")
        if request.base_url and _discovery_url_key(request.base_url, ollama=True) != _discovery_url_key(option.base_url, ollama=True):
            raise HTTPException(status_code=400, detail="Runtime source and endpoint do not match")

    # Connection edits identify their target provider but must not silently
    # replace the workspace's default model. Only a complete model choice
    # requests a new default.
    if request.provider and request.model:
        normalized_provider = _normalize_provider_id(request.provider)
        settings.set_setting("provider", normalized_provider, save=False)

    if request.runtime_source is not None:
        settings.set_setting("model_providers.ollama.runtime_source", request.runtime_source, save=False)

    if request.chat_response_mode is not None:
        settings.set_setting("chat_response_mode", request.chat_response_mode, save=False)

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
                persisted = secret_manager.delete_secret(secret_name)
            else:
                persisted = secret_manager.set_secret(
                    secret_name, request.api_key, description=f"{provider_id} API key"
                )
            if not persisted:
                raise HTTPException(
                    status_code=503, detail="Credential persistence unavailable"
                )
            
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


@router.patch("/providers/{provider_id}/chat-access", response_model=ModelSettingsResponse)
async def update_provider_chat_access(
    provider_id: str,
    request: ProviderChatAccessRequest,
    current_user: Any = Depends(require_permission(Permission.ADMIN_PROVIDERS_MANAGE)),
) -> Dict[str, Any]:
    """Publish administrator-approved provider/model choices for chat selection.

    Publication is distinct from provider health, credentials, available
    inventory, and RuntimePolicy. No secret material enters this endpoint.
    """
    normalized_id = _normalize_provider_id(provider_id)
    manager = get_provider_config_manager()
    provider = manager.get_provider(normalized_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown model provider")
    if (request.model_id is None) != (request.model_enabled is None):
        raise HTTPException(status_code=422, detail="Model ID and selection flag are required together")
    if request.provider_enabled is None and request.chat_enabled is None and request.model_id is None:
        raise HTTPException(status_code=422, detail="Choose a provider or model control to update")

    if request.model_id is not None:
        # Only an inventory-backed or registered ID can receive a chat toggle.
        # A client must not populate arbitrary model identifiers via this route.
        known_models = {model.id for model in (provider.models or [])}
        if request.model_id not in known_models:
            if not provider.enabled:
                raise HTTPException(status_code=409, detail="Enable provider before selecting its models")
            try:
                live = await get_provider_models(normalized_id, current_user=current_user)
            except HTTPException as exc:
                raise HTTPException(status_code=409, detail="Model inventory is not verified") from exc
            known_models.update(
                model.id for model in live["models"]
                if model.source in {"provider_live", "local_runtime", "ollama_native"}
            )
            if request.model_id not in known_models:
                raise HTTPException(status_code=422, detail="Model is not in the configured or live inventory")

    try:
        updated = manager.set_chat_controls(
            normalized_id,
            provider_enabled=request.provider_enabled,
            chat_enabled=request.chat_enabled,
            model_id=request.model_id,
            model_enabled=request.model_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        logger.exception("Provider chat access persistence unavailable")
        raise HTTPException(status_code=503, detail="Provider chat access persistence unavailable") from exc

    # Reuse the existing administrative audit authority, never secret values.
    AdminProviderService()._audit_mutation(
        action="chat_access_changed",
        provider_id=normalized_id,
        operator_id=(
            current_user.get("user_id") if isinstance(current_user, dict)
            else getattr(current_user, "user_id", None)
        ),
        metadata={
            "provider_enabled": updated.enabled,
            "chat_enabled": updated.chat_enabled,
            "model_id": request.model_id,
            "model_enabled": request.model_enabled,
        },
    )
    try:
        get_registry().invalidate_provider_cache(normalized_id)
    except Exception:
        logger.warning("Provider cache invalidation unavailable for %s", normalized_id)
    return await build_model_settings_payload()


@router.get("/providers/{provider_id}/models", response_model=ProviderModelsResponse)
async def get_provider_models(
    provider_id: str,
    base_url: Optional[str] = None,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """List models from the selected, authorized provider endpoint.

    Local Ollama installations are authoritative for Ollama's inventory.
    A configured/default model is not evidence that its weights are installed.
    """
    normalized_id = _normalize_provider_id(provider_id)
    provider_manager = get_provider_config_manager()
    provider = provider_manager.get_provider(normalized_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown model provider")
    if not provider.enabled:
        raise HTTPException(status_code=409, detail="Model provider is disabled")

    override = _get_provider_override(normalized_id)
    saved_endpoint = override.get("base_url")
    configured_endpoint = provider.endpoint.base_url if provider.endpoint else None
    allowed_endpoints = {
        value for value in (saved_endpoint, configured_endpoint) if value
    }
    ollama_options = []
    if normalized_id == "ollama":
        ollama_options = await _get_ollama_runtime_options()
        allowed_endpoints.update(option.base_url for option in ollama_options)

    target_url = base_url or (
        resolve_ollama_inventory_endpoint(
            saved_base_url=saved_endpoint,
            configured_base_url=configured_endpoint,
            runtime_source=override.get("runtime_source"),
            runtime_options=ollama_options,
        ) if normalized_id == "ollama" else saved_endpoint or configured_endpoint
    )
    governed_vendor = OPENAI_COMPATIBLE_PROVIDER_DEFAULTS.get(normalized_id)
    if governed_vendor:
        approved = governed_vendor["base_url"]
        if (
            not target_url or not configured_endpoint
            or _discovery_url_key(target_url) != _discovery_url_key(approved)
            or _discovery_url_key(configured_endpoint) != _discovery_url_key(approved)
        ):
            raise HTTPException(
                status_code=403,
                detail="Vendor model discovery requires the approved endpoint",
            )
    if base_url:
        requested_key = _discovery_url_key(base_url, ollama=normalized_id == "ollama")
        authorized_keys = {
            _discovery_url_key(value, ollama=normalized_id == "ollama")
            for value in allowed_endpoints
        }
        if requested_key not in authorized_keys:
            raise HTTPException(
                status_code=403,
                detail="Model discovery requires a configured provider endpoint",
            )

    # A configured catalog entry is not evidence of provider discovery.
    live_discovery_failed = False
    workspace_inventory_verified = False
    by_id: Dict[str, ProviderModelPayload] = {
        model.id: ProviderModelPayload(
            id=model.id,
            name=model.name,
            family=model.family or "unknown",
            capabilities=list(model.capabilities or []),
            is_installed=False,
        )
        for model in (provider.models or [])
    }

    # Ollama's native model inventory is the source of truth. A failure must
    # be visible instead of silently replacing the inventory with defaults.
    if normalized_id == "ollama":
        if not target_url:
            raise HTTPException(status_code=503, detail="Ollama endpoint is not configured")
        try:
            names = await discover_installed_ollama_models(target_url)
        except Exception as exc:
            logger.warning("Ollama model discovery unavailable", exc_info=True)
            raise HTTPException(
                status_code=503, detail="Unable to retrieve installed Ollama models"
            ) from exc
        # A provider's configured default must not masquerade as an installed
        # model when its native API reports no matching model.
        by_id = {
            name: ProviderModelPayload(
                id=name,
                name=name,
                family="ollama",
                capabilities=[],
                is_installed=True,
                source="ollama_native",
            )
            for name in names
        }
    else:
        discovery_service = get_model_discovery_service()
        try:
            discovered = await discovery_service.get_models_async(runtime=normalized_id)
            for item in discovered:
                by_id[item.model_id] = ProviderModelPayload(
                    id=item.model_id,
                    name=item.display_name or item.name,
                    family=item.model_type or "unknown",
                    capabilities=list(item.capabilities),
                    size_gb=float(item.size_bytes / (1024 ** 3))
                    if item.size_bytes else None,
                    is_installed=bool(item.weights_present),
                    source="local_runtime",
                )
        except Exception:
            live_discovery_failed = True
            logger.warning("Local model discovery unavailable for %s", normalized_id, exc_info=True)

        if target_url and provider.provider_type in {ProviderType.REMOTE, ProviderType.HYBRID, ProviderType.CUSTOM}:
            from ai_karen_engine.core.model_runtime.provider_execution import (
                discover_openai_compatible_model_ids,
            )
            from ai_karen_engine.core.model_runtime.provider_registry_service import (
                get_provider_registry_service,
            )
            from ai_karen_engine.core.model_runtime.runtime_engine import EndpointKind

            try:
                api_key = provider_manager.get_api_key(provider.name)
                registry = None
                endpoint = None
                registration = None
                if governed_vendor and api_key:
                    registry = get_provider_registry_service()
                    endpoint = registry.get_provider_endpoint(normalized_id)
                    if (
                        endpoint is None
                        or endpoint.kind != EndpointKind.CLOUD_PROVIDER
                        or endpoint.tenant_scoped is not True
                        or not endpoint.base_url
                        or _discovery_url_key(endpoint.base_url) != _discovery_url_key(target_url)
                    ):
                        raise RuntimeError("workspace_inventory_endpoint_unverified")
                    registration = registry.capture_endpoint_registration(endpoint)
                    if registration is None:
                        raise RuntimeError("workspace_inventory_registration_unverified")

                live_models = await asyncio.to_thread(
                    discover_openai_compatible_model_ids,
                    target_url, api_key=api_key,
                )
                if registry is not None:
                    # Request-local connection evidence, never shared health.
                    current_provider = provider_manager.get_provider(normalized_id)
                    current_override = _get_provider_override(normalized_id)
                    if (
                        current_provider is None or not current_provider.enabled
                        or not current_provider.endpoint
                        or _discovery_url_key(current_provider.endpoint.base_url)
                        != _discovery_url_key(target_url)
                        or current_override.get("base_url") != saved_endpoint
                        or provider_manager.get_api_key(provider.name) != api_key
                        or registry.capture_endpoint_registration(endpoint) is not registration
                    ):
                        raise RuntimeError("workspace_inventory_observation_superseded")
                    workspace_inventory_verified = True

                for name in live_models:
                    by_id[name] = ProviderModelPayload(
                        id=name, name=name, family=normalized_id,
                        capabilities=[], is_installed=False, source="provider_live",
                    )
            except Exception as exc:
                live_discovery_failed = True
                logger.warning(
                    "remote_model_discovery_unavailable",
                    extra={"provider": normalized_id, "error_type": type(exc).__name__},
                )

    sources = {model.source for model in by_id.values()}
    if normalized_id == "ollama":
        inventory_source = "ollama_native"
        discovery_status = "ready" if by_id else "empty"
    else:
        live_sources = sources - {"configured_catalog"}
        discovery_status = (
            "ready" if live_sources else "catalog_only" if by_id else "empty"
        )
        inventory_source = (
            "mixed" if len(sources) > 1
            else next(iter(sources)) if sources else "none"
        )

    return {
        "provider": normalized_id,
        "base_url": target_url,
        "models": list(by_id.values()),
        "discovery_status": discovery_status,
        "inventory_source": inventory_source,
        "live_discovery_failed": live_discovery_failed,
        "workspace_inventory_verified": workspace_inventory_verified,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/validate")
async def validate_provider_settings(
    request: ProviderSettingsValidationRequest,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """Verify a candidate API key against the configured provider, not a catalog.

    This is an administrator-managed workspace setting. A model listing, saved
    key or merely nonempty input cannot establish authenticated access.
    """
    roles = (
        current_user.get("roles", [])
        if isinstance(current_user, dict)
        else getattr(current_user, "roles", [])
    )
    if "admin" not in roles and "super_admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to validate workspace credentials",
        )

    provider_id = _normalize_provider_id(request.provider)
    unverified = {
        "valid": False,
        "status": "unverified",
        "message": "Provider credential could not be verified",
        "models_discovered": 0,
    }
    try:
        provider = get_provider_config_manager().get_provider(provider_id)
        if provider is None or not provider.enabled:
            return {**unverified, "message": "Provider is unavailable"}
        if provider.authentication.type != AuthenticationType.API_KEY:
            return {
                **unverified,
                "status": "not_required",
                "message": "This provider does not require an API key",
            }
        if not request.api_key or not request.api_key.strip():
            return {**unverified, "message": "Enter an API key to verify"}

        # Do not let submitted key material follow a user-provided base URL.
        # The auth adapter probes only the endpoint already in provider config.
        if request.base_url is not None:
            if not provider.endpoint:
                return unverified
            if _discovery_url_key(request.base_url) != _discovery_url_key(
                provider.endpoint.base_url
            ):
                return {
                    **unverified,
                    "message": "The endpoint must be configured before validating credentials",
                }

        result = await get_provider_auth_manager().validate_candidate_api_key(
            provider_id, request.api_key
        )
        verified = result.status == AuthenticationStatus.VALID
        if verified:
            return {
                "valid": True,
                "status": "verified",
                "message": "Provider authenticated the submitted API key",
                "models_discovered": 0,
            }
        if result.status in {
            AuthenticationStatus.INVALID,
            AuthenticationStatus.INSUFFICIENT_PERMISSIONS,
        }:
            state = "invalid"
            message = "Provider rejected this credential"
        elif result.status == AuthenticationStatus.RATE_LIMITED:
            state = "unverified"
            message = "Provider rate limit prevented verification"
        else:
            state = "unverified"
            message = "Provider verification is unavailable"
        return {**unverified, "status": state, "message": message}
    except HTTPException:
        # Malformed client URLs must never be used for a candidate probe.
        return {**unverified, "message": "Invalid provider validation endpoint"}
    except Exception as exc:
        # Exception strings can contain keys, authorization headers or URLs.
        logger.warning(
            "provider_credential_validation_failed",
            extra={"provider": provider_id, "error_type": type(exc).__name__},
        )
        return unverified


async def build_model_settings_payload() -> Dict[str, Any]:
    """Build the canonical ModelSettingsResponse dictionary."""
    settings = get_settings_manager()
    provider_manager = get_provider_config_manager()
    discovery_service = get_model_discovery_service()

    # Health has one runtime owner. Never instantiate the retired config-side
    # health manager just to build a consumer settings payload.
    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        get_provider_registry_service,
    )

    canonical_registry = get_provider_registry_service()
    health_monitor = canonical_registry.health_monitor

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
                is_installed=False
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
                    is_installed=bool(dm.weights_present),
                    source="local_runtime",
                ))

        # Endpoint settings from storage
        override = _get_provider_override(provider.name)
        
        # Capture the actual inference destination and registry generation before
        # the asynchronous runtime-option probes. A configured alias alone is
        # not evidence that the selected option is the inference server.
        runtime_options = None
        ollama_probe_published = False
        selected_option = None
        if provider.name == "ollama":
            from ai_karen_engine.core.model_runtime.provider_execution import (
                _resolve_base_url,
            )

            endpoint = None
            registration = None
            wire_url = None
            if provider.enabled:
                try:
                    endpoint = canonical_registry.get_provider_endpoint(
                        canonical_registry.canonicalize_provider_id(provider.name)
                    )
                    if endpoint is not None:
                        registration = canonical_registry.capture_endpoint_health_registration(
                            endpoint
                        )
                        wire_url = _resolve_base_url(endpoint)
                except Exception:
                    logger.warning("ollama_probe_registration_unavailable")
            runtime_options = await _get_ollama_runtime_options()
            selected_source = override.get("runtime_source") or OLLAMA_HOST_RUNTIME
            selected_option = next(
                (option for option in runtime_options if option.source == selected_source),
                None,
            )
            try:
                current_override = _get_provider_override(provider.name)
                if (
                    endpoint is not None and registration is not None
                    and wire_url and selected_option is not None
                    and current_override.get("runtime_source") == override.get("runtime_source")
                    and current_override.get("base_url") == override.get("base_url")
                    and _resolve_base_url(endpoint) == wire_url
                    and _discovery_url_key(selected_option.base_url, ollama=True)
                    == _discovery_url_key(wire_url, ollama=True)
                    and (
                        not override.get("base_url")
                        or _discovery_url_key(override["base_url"], ollama=True)
                        == _discovery_url_key(wire_url, ollama=True)
                    )
                ):
                    ollama_probe_published = canonical_registry.publish_endpoint_health(
                        endpoint, registration, is_healthy=bool(selected_option.available),
                        response_time=None,
                    )
            except Exception:
                logger.warning("ollama_probe_health_publication_unavailable")

        api_key_status = _get_api_key_status(provider.name, provider)

        # Read the registry-owned observed health record by canonical ID.
        # Registration and configured keys never stand in for a successful
        # provider probe. This projection cannot grant RuntimePolicy access.
        canonical_provider_id = (
            canonical_registry.canonicalize_provider_id(provider.name)
            or provider.name
        )
        health_info = health_monitor.get_provider_health(canonical_provider_id)
        health_status = health_info.health_status.value
        health_last_checked_at = (
            health_info.last_checked_at
            if health_status != "unknown" else None
        )
        is_configured = api_key_status in ["configured", "not_required"]
        # Observed endpoint health does not override credential/configuration
        # eligibility. Keep these independent facts visible to the consumer.
        healthy = health_status == "healthy" and is_configured
        degraded_reason = (
            "provider_not_configured" if not is_configured
            else "provider_health_unverified" if health_status == "unknown"
            else "provider_health_degraded" if health_status == "degraded"
            else "provider_health_unavailable" if health_status in {"unhealthy", "unavailable"}
            else None
        )
        if not provider.enabled:
            health_status = "unavailable"
            healthy = False
            degraded_reason = "Provider disabled"
            
        # An unrelated or superseded option must not certify the selected
        # installation, even if the alias has an earlier healthy observation.
        if provider.name == "ollama" and provider.enabled:
            if not ollama_probe_published:
                healthy = False
                health_status = "unknown"
                health_last_checked_at = None
                degraded_reason = "Ollama selected endpoint health unverified"
            if (
                (ollama_probe_published or not override.get("base_url"))
                and (selected_option is None or not selected_option.available)
            ):
                is_configured = False
                healthy = False
                degraded_reason = "Selected Ollama runtime is unavailable"
                health_status = "unavailable"

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
            runtime_source=override.get("runtime_source") if provider.name == "ollama" else None,
            is_configured=is_configured,
            healthy=healthy,
            health_status=health_status,
            health_last_checked_at=health_last_checked_at,
            user_selectable=bool(provider.priority > 0),
            enabled=bool(provider.enabled),
            chat_enabled=bool(getattr(provider, 'chat_enabled', True)),
            chat_model_visibility=dict(getattr(provider, 'chat_model_visibility', {}) or {}),
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
        ]),
        "chat_response_mode": settings.get_setting("chat_response_mode", "streaming_first"),
    }


def _normalize_provider_id(pid: Any) -> str:
    """Keep registered provider IDs intact, including hyphenated IDs."""
    identifier = str(pid or "").strip().lower().replace(" ", "_")
    return resolve_provider_name(identifier)


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


def _discovery_url_key(base_url: str, *, ollama: bool = False) -> str:
    """Compare only authorized model endpoints; reject URL credential tricks."""
    parsed = urlparse(str(base_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid model discovery endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=400, detail="Invalid model discovery endpoint")
    path = parsed.path.rstrip("/")
    if ollama and path.endswith(("/v1", "/api")):
        path = path.rsplit("/", 1)[0]
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


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
        health_url = _discovery_url_key(base_url, ollama=True) + "/api/tags"
        
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
