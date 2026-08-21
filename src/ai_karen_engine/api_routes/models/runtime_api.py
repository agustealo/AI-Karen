"""
Unified Runtime API Routes

Provides a single source of truth for LLM providers, models, and execution status.
Consumed by both settings and chat interfaces to ensure architectural alignment.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.api_routes.models.settings import build_model_settings_payload
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, Depends = import_fastapi("APIRouter", "Depends")
BaseModel, Field = import_pydantic("BaseModel", "Field")

logger = logging.getLogger("kari.runtime_api")

router = APIRouter(prefix="/runtime", tags=["runtime"])


class ProviderHealthInfo(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    last_checked_at: Optional[datetime] = None


class RuntimeModel(BaseModel):
    id: str
    label: str
    available: bool = True
    default: bool = False
    capabilities: List[str] = Field(default_factory=list)


class RuntimeProvider(BaseModel):
    id: str
    label: str
    provider_label: Optional[str] = None
    category: str  # builtin, local, external, custom
    enabled: bool
    configured: bool
    healthy: bool
    runtime_engine: str
    transport: str
    compatibility_profile: Optional[str] = None
    default_model: Optional[str] = None
    selected_model: Optional[str] = None
    api_key_env_var: Optional[str] = None
    api_key_header: Optional[str] = None
    api_key_prefix: Optional[str] = None
    default_base_url: Optional[str] = None
    base_url: Optional[str] = None
    docs_url: Optional[str] = None
    required_config_fields: List[str] = Field(default_factory=list)
    safe_diagnostic_metadata: Dict[str, Any] = Field(default_factory=dict)
    models: List[RuntimeModel]
    health: ProviderHealthInfo
    degradation_reason: Optional[str] = None
    allowed_for_current_user: bool = True
    requires_api_key: bool = False
    requires_base_url: bool = False
    runtime_config_hash: Optional[str] = None
    errors: List[Dict[str, str]] = Field(default_factory=list)


class RuntimeProviderCatalog(BaseModel):
    providers: List[RuntimeProvider]
    default_provider: str
    default_model: str
    fallback_order: List[str]
    catalog_version: str = "1.0.0"
    runtime_config_hash: Optional[str] = None
    errors: List[Dict[str, str]] = Field(default_factory=list)




def _build_bootstrap_runtime_catalog(error: Optional[Exception] = None) -> RuntimeProviderCatalog:
    error_message = str(error) if error else "Provider catalog booted from fallback because settings payload failed."
    providers = [
        RuntimeProvider(
            id="builtin_transformers",
            label="Transformers",
            provider_label="Transformers",
            category="builtin",
            enabled=True,
            configured=True,
            healthy=False,
            runtime_engine="transformers",
            transport="process",
            default_model="auto",
            selected_model="auto",
            models=[RuntimeModel(id="auto", label="Auto", available=True, default=True, capabilities=["chat"])],
            health=ProviderHealthInfo(status="degraded", last_checked_at=datetime.now(timezone.utc)),
            degradation_reason="Provider catalog booted from fallback because settings payload failed.",
            requires_api_key=False,
            requires_base_url=False,
        ),
        RuntimeProvider(
            id="builtin_vllm",
            label="vLLM",
            provider_label="vLLM",
            category="builtin",
            enabled=True,
            configured=True,
            healthy=False,
            runtime_engine="vllm",
            transport="process_or_http",
            models=[],
            health=ProviderHealthInfo(status="degraded", last_checked_at=datetime.now(timezone.utc)),
            degradation_reason="vLLM health/model discovery unavailable during catalog boot.",
            requires_api_key=False,
            requires_base_url=False,
        ),
    ]
    return RuntimeProviderCatalog(
        providers=providers,
        default_provider="builtin_transformers",
        default_model="auto",
        fallback_order=["builtin_transformers", "builtin_vllm"],
        catalog_version="bootstrap",
        errors=[{"error_type": "settings_payload_failed", "message": error_message}],
    )

@router.get("/providers", response_model=RuntimeProviderCatalog)
async def get_runtime_provider_catalog(
    current_user: Any = Depends(get_current_user),
):
    """
    Get the canonical provider and model catalog for the entire runtime.
    This is the ONE TRUE SOURCE for provider/model selection UI.
    """
    try:
        settings_response = await build_model_settings_payload()
        runtime_config_hash = None

        catalog_providers = []
        for provider_obj in settings_response.get("providers", []):
            # Ensure we are working with a dictionary even if it's a Pydantic model
            provider = provider_obj.model_dump() if hasattr(provider_obj, "model_dump") else (provider_obj.dict() if hasattr(provider_obj, "dict") else provider_obj)

            provider_type = str(provider.get("provider_type") or provider.get("type") or "external").lower()
            provider_id = str(provider.get("id") or "")
            if provider_id == "ollama" or provider_type == "local":
                category = "local"
            elif provider_type == "builtin":
                category = "builtin"
            elif provider_type == "custom":
                category = "custom"
            else:
                category = "external"

            safe_metadata = provider.get("safe_diagnostic_metadata") or {}
            # Use resolver's runtime_engine metadata instead of loose heuristics
            runtime_engine = str(
                safe_metadata.get("runtime_engine")
                or provider.get("runtime_engine")
                or provider_id
            )
            # Only strip "builtin_" prefix if it's still there for backward compatibility
            if runtime_engine.startswith("builtin_"):
                runtime_engine = runtime_engine.replace("builtin_", "")
            transport = "process" if category == "builtin" else "http"
            raw_models = provider.get("models") or []
            models = []
            for model_obj in raw_models:
                model = model_obj.model_dump() if hasattr(model_obj, "model_dump") else (model_obj.dict() if hasattr(model_obj, "dict") else model_obj)
                if model.get("id"):
                    models.append(RuntimeModel(
                        id=str(model.get("id") or ""),
                        label=str(model.get("name") or model.get("label") or model.get("id") or ""),
                        available=bool(model.get("is_installed", model.get("available", True))),
                        default=str(model.get("id") or "") == str(provider.get("selected_model") or ""),
                        capabilities=list(model.get("capabilities") or []),
                    ))

            if not models and provider.get("selected_model"):
                models = [
                    RuntimeModel(
                        id=str(provider["selected_model"]),
                        label=str(provider["selected_model"]),
                        available=True,
                        default=True,
                        capabilities=list(safe_metadata.get("capabilities") or ["chat"]),
                    )
                ]

            catalog_providers.append(RuntimeProvider(
                id=provider_id,
                label=str(provider.get("display_name") or provider_id),
                provider_label=str(provider.get("display_name") or provider_id),
                category=category,
                enabled=bool(provider.get("enabled", True)),
                configured=bool(provider.get("is_configured", False)),
                healthy=bool(provider.get("healthy", True)),
                runtime_engine=runtime_engine,
                transport=transport,
                compatibility_profile=safe_metadata.get("compatibility_profile"),
                default_model=provider.get("selected_model") or provider.get("default_model"),
                selected_model=provider.get("selected_model"),
                api_key_env_var=provider.get("api_key_env_var"),
                api_key_header=provider.get("api_key_header"),
                api_key_prefix=provider.get("api_key_prefix"),
                default_base_url=provider.get("default_base_url"),
                base_url=provider.get("base_url"),
                docs_url=provider.get("doc_url"),
                required_config_fields=list(provider.get("required_config_fields") or []),
                safe_diagnostic_metadata=safe_metadata,
                models=models,
                health=ProviderHealthInfo(
                    status="healthy" if provider.get("healthy", True) else "degraded",
                    latency_ms=None,
                    last_checked_at=datetime.now(timezone.utc),
                ),
                degradation_reason=provider.get("degraded_reason"),
                allowed_for_current_user=bool(provider.get("user_selectable", True) and provider.get("policy_allowed", True)),
                requires_api_key=bool(provider.get("api_key_env_var") or provider.get("requires_api_key")),
                requires_base_url=bool(provider.get("supports_base_url_override")),
                runtime_config_hash=runtime_config_hash,
            ))

        default_provider = settings_response.get("default_provider") or settings_response.get("selected_provider") or "builtin_transformers"
        default_model = settings_response.get("default_model") or settings_response.get("selected_model") or "auto"
        fallback_order = settings_response.get("fallback_hierarchy") or ["builtin_transformers", "builtin_vllm", "openai", "gemini"]

        if not catalog_providers:
            return _build_bootstrap_runtime_catalog()

        return RuntimeProviderCatalog(
            providers=catalog_providers,
            default_provider=default_provider,
            default_model=default_model,
            fallback_order=fallback_order,
            runtime_config_hash=runtime_config_hash,
        )
    except Exception as e:
        logger.error(f"Error building runtime provider catalog: {e}")
        return _build_bootstrap_runtime_catalog(e)
