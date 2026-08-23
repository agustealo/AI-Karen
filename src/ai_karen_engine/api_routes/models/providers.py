"""
Provider Management API Routes

Provides REST API endpoints for dynamic provider discovery, API key validation,
and provider health monitoring.
"""

import asyncio
import logging
import time
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.errors.handlers import handle_api_exception
from ai_karen_engine.integrations.registry import get_registry
from ai_karen_engine.core.model_runtime.provider_registry_service import (
    ProviderCapability,
    get_provider_registry_service,
)
from ai_karen_engine.config.config_asset_loaders import load_model_runtime_discovery_config
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, Depends, HTTPException = import_fastapi(
    "APIRouter", "Depends", "HTTPException"
)
BaseModel, Field = import_pydantic("BaseModel", "Field")

logger = logging.getLogger("kari.provider_routes")

router = APIRouter(tags=["providers"])
# Public router (no auth dependencies). Exposed under /api/public/providers
public_router = APIRouter(tags=["public-providers"])


FRIENDLY_PROVIDER_NAMES = {
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "deepseek": "DeepSeek",
    "huggingface": "Hugging Face",
    "anthropic": "Anthropic Claude",
    # NOTE: "local_gguf" and "local" are removed providers - kept only for backward compatibility with old configs
    "local_gguf": "[DEPRECATED] Third-Party GGUF Endpoint",
    "third_party_gguf": "Third-Party GGUF Endpoint",
    "local": "[DEPRECATED] Local Fallback",
}

DOC_URLS = {
    "openai": "https://platform.openai.com/docs",
    "gemini": "https://ai.google.dev/docs",
    "deepseek": "https://platform.deepseek.com/docs",
    "huggingface": "https://huggingface.co/docs",
    "anthropic": "https://docs.anthropic.com",
}


# Request/Response Models
class ApiKeyValidationRequest(BaseModel):
    """API key validation request model."""
    provider: str
    api_key: str


class ApiKeyValidationResult(BaseModel):
    """API key validation result model."""
    valid: bool
    message: str
    provider: str
    models_discovered: Optional[int] = None
    capabilities_detected: Optional[List[str]] = None


class ProviderHealthResult(BaseModel):
    """Provider health check result model."""
    status: str  # healthy, unhealthy, unknown
    message: Optional[str] = None
    error_message: Optional[str] = None
    last_check: Optional[float] = None
    response_time: Optional[float] = None
    capabilities: Dict[str, Any] = Field(default_factory=dict)


class ProviderInfo(BaseModel):
    """Provider information model."""
    name: str
    display_name: Optional[str] = None
    description: str
    category: str
    requires_api_key: bool
    capabilities: List[str]
    is_llm_provider: bool
    provider_type: str  # remote, local, hybrid
    health_status: str
    error_message: Optional[str] = None
    last_health_check: Optional[float] = None
    cached_models_count: int = 0
    last_discovery: Optional[float] = None
    api_base_url: Optional[str] = None
    documentation_url: Optional[str] = None
    pricing_info: Optional[Dict[str, Any]] = None


class ProviderStats(BaseModel):
    """Provider statistics model."""
    total_models: int
    healthy_providers: int
    total_providers: int
    last_sync: float
    degraded_mode: bool


class ModelInfo(BaseModel):
    """Model information model."""
    id: str
    name: str
    provider: str
    family: str = ""
    format: str = ""
    size: Optional[int] = None
    parameters: Optional[str] = None
    quantization: Optional[str] = None
    context_length: Optional[int] = None
    capabilities: List[str] = Field(default_factory=list)
    local_path: Optional[str] = None
    download_url: Optional[str] = None
    license: Optional[str] = None
    description: str = ""


# ------------------------------------------------------------
# Contract shapes to support unified frontend
# ------------------------------------------------------------

class ContractProviderItem(BaseModel):
    id: str
    title: str
    group: str  # "local" | "cloud"
    canListModels: bool
    canInfer: bool
    available: bool


class ContractModelInfo(BaseModel):
    id: str
    provider: str
    displayName: str
    family: str
    installed: bool = True
    remote: bool = False
    size: Optional[str] = None
    quant: Optional[str] = None
    contextWindow: Optional[int] = None
    tags: List[str] = []


def _split_env_csv(name: str) -> List[str]:
    val = os.getenv(name, "").strip()
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]


def _has_gguf(dir_path: Path) -> bool:
    try:
        return any(p.suffix.lower() == ".gguf" for p in dir_path.glob("**/*"))
    except Exception:
        return False


def _transformers_policy_values(key: str) -> set[str]:
    policy = (load_model_runtime_discovery_config().get("discovery_policy") or {})
    values = policy.get(key) or []
    return {str(item).strip() for item in values if str(item).strip()}


def _has_transformers_weights(model_dir: Path) -> bool:
    try:
        return any(
            item.is_file() and item.name.endswith((".bin", ".safetensors", ".gguf"))
            for item in model_dir.rglob("*")
        )
    except Exception:
        return False


def _list_gguf(dir_path: Path) -> List[ContractModelInfo]:
    """List GGUF model files for third-party endpoint usage.

    IMPORTANT: GGUF files are NOT an internal provider. They are model files
    that must be served through a third-party OpenAI-compatible endpoint like:
    - llama.cpp server
    - LM Studio
    - vLLM with GGUF support

    This function lists available GGUF files but assigns them to a special
    provider ID to indicate they require external endpoint configuration.
    """
    models: List[ContractModelInfo] = []
    for p in dir_path.glob("**/*.gguf"):
        name = p.stem
        display = name
        quant = None
        size = None
        lowered = name.lower()
        for token in ("3b", "4b", "7b", "8b", "13b", "34b", "70b"):
            if token in lowered:
                size = token.upper()
                break
        for part in name.split("-"):
            if part.upper().startswith("Q"):
                quant = part.upper()
                break
        models.append(
            ContractModelInfo(
                id=f"third_party_gguf:/{p.name}",
                provider="third_party_gguf",
                displayName=display,
                family="llama",
                installed=True,
                remote=False,
                size=size,
                quant=quant,
                contextWindow=8192,
                tags=["gguf", "third-party-endpoint"],
            )
        )
    return models


def _list_transformers(dir_path: Path) -> List[ContractModelInfo]:
    models: List[ContractModelInfo] = []
    allowed = _transformers_policy_values("runtime_visible_transformers")
    excluded = _transformers_policy_values("exclude_from_runtime_discovery")
    try:
        for child in dir_path.iterdir():
            if not child.is_dir():
                continue
            if child.name in excluded:
                continue
            if allowed and child.name not in allowed:
                continue
            if not _has_transformers_weights(child):
                logger.info(
                    "Skipping incomplete transformers model %s: no local weights found",
                    child.name,
                )
                continue
            models.append(
                ContractModelInfo(
                    id=f"transformers:/{child.name}",
                    provider="transformers-local",
                    displayName=child.name,
                    family="transformers",
                    installed=True,
                    remote=False,
                    tags=["hf", "local"],
                )
            )
    except Exception:
        pass
    return models


# Dependency to get registry
def get_llm_registry():
    """Get the global LLM registry instance."""
    return get_registry()


def _determine_provider_type(spec, status) -> str:
    if spec and getattr(spec, "requires_api_key", False):
        if "local_execution" in getattr(spec, "capabilities", []) or getattr(spec, "supports_local_models", False):
            return "hybrid"
        return "remote"
    return "local"


def _normalize_capabilities(spec, status) -> List[str]:
    caps = set()
    spec_caps = getattr(spec, "capabilities", None) or []
    for cap in spec_caps:
        caps.add(cap)
    if status and getattr(status, "capabilities", None):
        caps.update(cap.value if isinstance(cap, ProviderCapability) else str(cap) for cap in status.capabilities)
    return sorted(caps)


def _build_provider_entry(
    name: str,
    registry,
    registry_service,
    *,
    healthy_only: bool,
    category_filter: Optional[str],
    llm_only: bool,
) -> Optional[ProviderInfo]:
    spec = registry.get_provider_spec(name)
    status = registry_service.get_provider_status(name)

    if spec is None and status is None:
        return None

    category = getattr(spec, "category", category_filter or "LLM")
    if llm_only and category != "LLM":
        return None
    if category_filter and category != category_filter:
        return None

    resolved_status = "unknown"
    if status:
        if status.is_available:
            resolved_status = "healthy"
        elif spec and getattr(spec, "requires_api_key", False) and not status.has_api_key:
            resolved_status = "degraded"
        elif status.health_status.value:
            resolved_status = status.health_status.value
        else:
            resolved_status = "unknown"
    if healthy_only and resolved_status != "healthy":
        return None

    friendly_name = FRIENDLY_PROVIDER_NAMES.get(
        name,
        getattr(spec, "display_name", None) or getattr(spec, "description", None) or name.title(),
    )
    description = getattr(spec, "description", None) or friendly_name

    model_library_info: Dict[str, Any] = {}
    try:
        from ai_karen_engine.core.model_runtime.compatibility.provider_model_compatibility import ProviderModelCompatibilityService

        compatibility_service = ProviderModelCompatibilityService()
        validation = compatibility_service.validate_provider_model_setup(name)
        model_library_info = {
            "has_compatible_models": validation.get("has_compatible_models", False),
            "local_models_count": validation.get("local_models_count", 0),
            "available_for_download": validation.get("available_for_download", 0),
            "total_compatible": validation.get("total_compatible", 0),
        }
    except Exception as exc:  # pragma: no cover - best effort enrichment
        logger.debug("Model library info unavailable for %s: %s", name, exc)

    provider_info = ProviderInfo(
        name=getattr(spec, "name", name),
        display_name=friendly_name,
        description=description,
        category=category,
        requires_api_key=bool(getattr(spec, "requires_api_key", False)),
        capabilities=_normalize_capabilities(spec, status),
        is_llm_provider=(category == "LLM"),
        provider_type=_determine_provider_type(spec, status),
        health_status=resolved_status,
        error_message=getattr(status, "error_message", None),
        last_health_check=(
            status.last_check.timestamp() if status and getattr(status, "last_check", None) else None
        ),
        cached_models_count=model_library_info.get(
            "local_models_count", len(getattr(spec, "fallback_models", []) or [])
        ),
        last_discovery=None,
        api_base_url=getattr(spec, "api_base_url", None),
        documentation_url=DOC_URLS.get(name),
        pricing_info=getattr(spec, "pricing_info", None),
    )

    if status:
        provider_info.health_status = resolved_status
    return provider_info


@router.get("/", response_model=List[ProviderInfo])
async def list_providers(
    category: Optional[str] = None,
    healthy_only: bool = False,
    llm_only: bool = False,
    registry=Depends(get_llm_registry)
):
    """
    Get list of all registered providers with their information.
    
    Args:
        category: Filter by provider category (LLM, UI_FRAMEWORK, etc.)
        healthy_only: Only return healthy providers
        
    Returns:
        List of provider information
    """
    try:
        registry_service = get_provider_registry_service()
        provider_names: List[str] = []

        # Start with providers known to the registry service for accurate availability
        system_status = registry_service.get_system_status()
        provider_names.extend(system_status.get("provider_details", {}).keys())

        # Ensure we include any additional providers registered with the LLM registry
        extra_names = registry.list_providers(category=category, healthy_only=False)
        for name in extra_names:
            if name not in provider_names:
                provider_names.append(name)

        providers: List[ProviderInfo] = []
        for name in provider_names:
            provider_info = _build_provider_entry(
                name,
                registry,
                registry_service,
                healthy_only=healthy_only,
                category_filter=category,
                llm_only=llm_only,
            )
            if provider_info:
                providers.append(provider_info)

        # Stable sort by display name for UI friendliness
        providers.sort(key=lambda p: (p.display_name or p.name).lower())

        return providers
        
    except Exception as ex:
        logger.error(f"Failed to list providers: {ex}")
        raise handle_api_exception(ex, "Failed to retrieve provider list")


@router.get("/llm", response_model=List[ProviderInfo])
async def list_llm_providers(
    healthy_only: bool = False,
    registry=Depends(get_llm_registry)
):
    """
    Get list of LLM providers only (excludes UI frameworks like CopilotKit).
    
    Args:
        healthy_only: Only return healthy providers
        
    Returns:
        List of LLM provider information
    """
    try:
        registry_service = get_provider_registry_service()
        provider_names: List[str] = registry.list_llm_providers(healthy_only=False)

        providers: List[ProviderInfo] = []
        for name in provider_names:
            provider_info = _build_provider_entry(
                name,
                registry,
                registry_service,
                healthy_only=healthy_only,
                category_filter="LLM",
                llm_only=True,
            )
            if provider_info:
                providers.append(provider_info)

        providers.sort(key=lambda p: (p.display_name or p.name).lower())
        return providers
        
    except Exception as ex:
        logger.error(f"Failed to list LLM providers: {ex}")
        raise handle_api_exception(ex, "Failed to retrieve LLM provider list")


@router.post("/validate-api-key", response_model=ApiKeyValidationResult)
async def validate_api_key(
    request: ApiKeyValidationRequest,
    registry=Depends(get_llm_registry)
):
    """
    Validate API key for a provider and discover available models.
    
    Args:
        request: API key validation request
        
    Returns:
        Validation result with model discovery information
    """
    try:
        provider_name = request.provider
        api_key = request.api_key
        
        # Get provider spec
        spec = registry.get_provider_spec(provider_name)
        if not spec:
            return ApiKeyValidationResult(
                valid=False,
                message=f"Provider '{provider_name}' not found",
                provider=provider_name
            )
        
        if not spec.requires_api_key:
            return ApiKeyValidationResult(
                valid=True,
                message=f"Provider '{provider_name}' does not require API key",
                provider=provider_name,
                models_discovered=len(spec.fallback_models)
            )
        
        # Validate API key using provider's validation function
        if spec.validate:
            try:
                is_valid = spec.validate({"api_key": api_key})
                
                if is_valid:
                    # Try to discover models if provider supports it
                    models_discovered = 0
                    capabilities_detected = list(spec.capabilities)
                    
                    if spec.discover:
                        try:
                            models = spec.discover()
                            models_discovered = len(models) if models else 0
                        except Exception as e:
                            logger.warning(f"Model discovery failed for {provider_name}: {e}")
                            # Use fallback models count
                            models_discovered = len(spec.fallback_models)
                    else:
                        models_discovered = len(spec.fallback_models)
                    
                    return ApiKeyValidationResult(
                        valid=True,
                        message=f"API key valid for {provider_name}",
                        provider=provider_name,
                        models_discovered=models_discovered,
                        capabilities_detected=capabilities_detected
                    )
                else:
                    return ApiKeyValidationResult(
                        valid=False,
                        message=f"Invalid API key for {provider_name}",
                        provider=provider_name
                    )
                    
            except Exception as e:
                logger.error(f"API key validation failed for {provider_name}: {e}")
                return ApiKeyValidationResult(
                    valid=False,
                    message=f"Validation error: {str(e)}",
                    provider=provider_name
                )
        else:
            # No validation function available, assume valid if key is provided
            return ApiKeyValidationResult(
                valid=bool(api_key.strip()),
                message="No validation available, assuming valid" if api_key.strip() else "API key required",
                provider=provider_name,
                models_discovered=len(spec.fallback_models)
            )
            
    except Exception as ex:
        logger.error(f"Failed to validate API key: {ex}")
        return ApiKeyValidationResult(
            valid=False,
            message=f"Validation failed: {str(ex)}",
            provider=request.provider
        )


@router.get("/{provider_name}/models", response_model=List[ModelInfo])
async def get_provider_models(
    provider_name: str,
    force_refresh: bool = False,
    registry=Depends(get_llm_registry)
):
    """
    Get available models for a provider.
    
    Args:
        provider_name: Name of the provider
        force_refresh: Force refresh from provider API
        
    Returns:
        List of available models
    """
    try:
        spec = registry.get_provider_spec(provider_name)
        if not spec:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_name}' not found"
            )
        
        models = []
        
        # Try to discover models from provider API
        if spec.discover and force_refresh:
            try:
                discovered_models = spec.discover()
                if discovered_models:
                    for model_data in discovered_models:
                        model_info = ModelInfo(
                            id=model_data.get("id", ""),
                            name=model_data.get("name", model_data.get("id", "")),
                            provider=provider_name,
                            family=model_data.get("family", ""),
                            format=model_data.get("format", ""),
                            size=model_data.get("size"),
                            parameters=model_data.get("parameters"),
                            quantization=model_data.get("quantization"),
                            context_length=model_data.get("context_length"),
                            capabilities=model_data.get("capabilities", []),
                            download_url=model_data.get("download_url"),
                            license=model_data.get("license"),
                            description=model_data.get("description", "")
                        )
                        models.append(model_info)
                else:
                    # Fall back to fallback models
                    for model_data in spec.fallback_models:
                        model_info = ModelInfo(
                            id=model_data.get("id", ""),
                            name=model_data.get("name", model_data.get("id", "")),
                            provider=provider_name,
                            family=model_data.get("family", ""),
                            capabilities=model_data.get("capabilities", [])
                        )
                        models.append(model_info)
            except Exception as e:
                logger.warning(f"Model discovery failed for {provider_name}: {e}")
                # Fall back to fallback models
                for model_data in spec.fallback_models:
                    model_info = ModelInfo(
                        id=model_data.get("id", ""),
                        name=model_data.get("name", model_data.get("id", "")),
                        provider=provider_name,
                        family=model_data.get("family", ""),
                        capabilities=model_data.get("capabilities", [])
                    )
                    models.append(model_info)
        else:
            # Use fallback models
            for model_data in spec.fallback_models:
                model_info = ModelInfo(
                    id=model_data.get("id", ""),
                    name=model_data.get("name", model_data.get("id", "")),
                    provider=provider_name,
                    family=model_data.get("family", ""),
                    capabilities=model_data.get("capabilities", [])
                )
                models.append(model_info)
        
        return models
        
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to get models for provider {provider_name}: {ex}")
        raise handle_api_exception(ex, f"Failed to get models for provider {provider_name}")


@router.post("/health-check-all", response_model=Dict[str, ProviderHealthResult])
async def health_check_all_providers(registry=Depends(get_llm_registry)):
    """
    Perform health check on all registered providers.
    
    Returns:
        Dict containing health check results for each provider
    """
    try:
        results = {}
        provider_names = registry.list_providers()
        
        # Run health checks concurrently
        async def check_provider(name: str):
            try:
                health = registry.health_check(f"provider:{name}")
                return name, ProviderHealthResult(
                    status=health.status,
                    message=f"Provider {name} health check",
                    error_message=health.error_message,
                    last_check=health.last_check,
                    response_time=health.response_time,
                    capabilities=health.capabilities
                )
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                return name, ProviderHealthResult(
                    status="unhealthy",
                    error_message=str(e),
                    last_check=time.time()
                )
        
        # Execute health checks concurrently
        tasks = [check_provider(name) for name in provider_names]
        health_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in health_results:
            if isinstance(result, tuple):
                name, health_result = result
                results[name] = health_result
            else:
                logger.error(f"Health check task failed: {result}")
        
        return results
        
    except Exception as ex:
        logger.error(f"Failed to perform health check on all providers: {ex}")
        raise handle_api_exception(ex, "Failed to perform provider health checks")


@router.get("/health/{provider_name}", response_model=ProviderHealthResult)
async def health_check_provider(
    provider_name: str,
    registry=Depends(get_llm_registry)
):
    """
    Perform health check on a specific provider.
    
    Args:
        provider_name: Name of the provider to check
        
    Returns:
        Health check result for the provider
    """
    try:
        spec = registry.get_provider_spec(provider_name)
        if not spec:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_name}' not found"
            )
        
        health = registry.health_check(f"provider:{provider_name}")
        
        return ProviderHealthResult(
            status=health.status,
            message=f"Provider {provider_name} health check",
            error_message=health.error_message,
            last_check=health.last_check,
            response_time=health.response_time,
            capabilities=health.capabilities
        )
        
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to health check provider {provider_name}: {ex}")
        raise handle_api_exception(ex, f"Failed to health check provider {provider_name}")


@router.get("/stats", response_model=ProviderStats)
async def get_provider_stats(registry=Depends(get_llm_registry)):
    """
    Get provider statistics and system status.
    
    Returns:
        Provider statistics including health status and model counts
    """
    try:
        provider_names = registry.list_providers()
        healthy_providers = registry.get_healthy_providers()
        
        # Count total models across all providers
        total_models = 0
        for name in provider_names:
            spec = registry.get_provider_spec(name)
            if spec:
                total_models += len(spec.fallback_models)
        
        # Check if system is in degraded mode
        unhealthy_components = registry.get_unhealthy_components()
        degraded_mode = len(unhealthy_components) > len(provider_names) // 2
        
        return ProviderStats(
            total_models=total_models,
            healthy_providers=len(healthy_providers),
            total_providers=len(provider_names),
            last_sync=time.time(),
            degraded_mode=degraded_mode
        )
        
    except Exception as ex:
            logger.error(f"Failed to get provider stats: {ex}")
            raise handle_api_exception(ex, "Failed to get provider statistics")


# ----------------- Contract endpoints under /api/providers -----------------


@router.get("/discovery", response_model=List[ContractProviderItem])
async def provider_discovery() -> List[ContractProviderItem]:
    items: List[ContractProviderItem] = []

    gguf_dir = Path(
        os.getenv("KARI_LOCAL_GGUF_MODELS_DIR")
        or os.getenv("KARI_MODEL_DIR")
        or "./models/gguf"
    ).resolve()
    gguf_available = gguf_dir.exists() and _has_gguf(gguf_dir)

    tf_dir = Path(os.getenv("TRANSFORMERS_MODELS_DIR", "./models/transformers")).resolve()
    transformers_available = tf_dir.exists() and any(tf_dir.iterdir())

    spacy_pipelines = _split_env_csv("SPACY_PIPELINES")
    spacy_available = len(spacy_pipelines) > 0

    cloud_envs = {
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "mistral": bool(os.getenv("MISTRAL_API_KEY")),
        "groq": bool(os.getenv("GROQ_API_KEY")),
    }

    items.extend(
        [
            ContractProviderItem(
                id="third_party_gguf",
                title="[DEPRECATED] Third-Party GGUF Endpoint",
                group="third-party",
                canListModels=True,
                canInfer=False,
                available=gguf_available,
                description="GGUF models are served through third-party OpenAI-compatible endpoints (llama.cpp, LM Studio, etc.), not as an internal provider",
            ),
            ContractProviderItem(
                id="transformers-local",
                title="Transformers (Local)",
                group="local",
                canListModels=True,
                canInfer=False,
                available=transformers_available,
            ),
            ContractProviderItem(
                id="spacy",
                title="spaCy (Pipelines)",
                group="local",
                canListModels=True,
                canInfer=False,
                available=spacy_available,
            ),
            ContractProviderItem(
                id="openai",
                title="OpenAI",
                group="cloud",
                canListModels=True,
                canInfer=False,
                available=cloud_envs["openai"],
            ),
        ]
    )

    for pid, ok in cloud_envs.items():
        if pid == "openai":
            continue
        title = pid.title() if pid != "groq" else "Groq"
        items.append(
            ContractProviderItem(
                id=pid,
                title=title,
                group="cloud",
                canListModels=True,
                canInfer=False,
                available=ok,
            )
        )

    return items

# Public mirrors
@public_router.get("/discovery", response_model=List[ContractProviderItem])
async def public_provider_discovery() -> List[ContractProviderItem]:
    return await provider_discovery()


@router.get("/local/gguf/models", response_model=List[ContractModelInfo])
async def contract_gguf_models() -> List[ContractModelInfo]:
    """List GGUF model files for third-party endpoint usage.

    DEPRECATED: This endpoint lists GGUF files that must be served through
    third-party OpenAI-compatible endpoints (llama.cpp, LM Studio, etc.).
    These are NOT internal providers - they require external endpoint configuration.

    Use /api/providers/third-party/gguf/models instead.
    """
    base = Path(
        os.getenv("KARI_LOCAL_GGUF_MODELS_DIR")
        or os.getenv("KARI_MODEL_DIR")
        or "./models/gguf"
    ).resolve()
    if not base.exists():
        return []
    return _list_gguf(base)

@public_router.get("/local/gguf/models", response_model=List[ContractModelInfo])
async def public_gguf_models() -> List[ContractModelInfo]:
    """Public endpoint for GGUF model listing. See contract_gguf_models() for details."""
    return await contract_gguf_models()


@router.get("/local/transformers/models", response_model=List[ContractModelInfo])
async def contract_transformers_models() -> List[ContractModelInfo]:
    base = Path(os.getenv("TRANSFORMERS_MODELS_DIR", "./models/transformers")).resolve()
    if not base.exists():
        return []
    return _list_transformers(base)

@public_router.get("/local/transformers/models", response_model=List[ContractModelInfo])
async def public_transformers_models() -> List[ContractModelInfo]:
    return await contract_transformers_models()


@router.get("/local/spacy/pipelines", response_model=List[str])
async def contract_spacy_pipelines() -> List[str]:
    return _split_env_csv("SPACY_PIPELINES")

@public_router.get("/local/spacy/pipelines", response_model=List[str])
async def public_spacy_pipelines() -> List[str]:
    return await contract_spacy_pipelines()


@router.get("/cloud/openai/ping")
async def contract_openai_ping():
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")
    return {"ok": True}


@router.get("/cloud/openai/models", response_model=List[ContractModelInfo])
async def contract_openai_models() -> List[ContractModelInfo]:
    key = os.getenv("OPENAI_API_KEY")
    allowlist = _split_env_csv("OPENAI_MODELS_ALLOWLIST")
    models: List[ContractModelInfo] = []

    if allowlist:
        for mid in allowlist:
            models.append(
                ContractModelInfo(
                    id=mid,
                    provider="openai",
                    displayName=mid,
                    family="gpt" if mid.startswith("gpt") else "openai",
                    installed=False,
                    remote=True,
                    tags=["cloud"],
                )
            )
        return models

    if key:
        try:
            import requests  # type: ignore

            base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            resp = requests.get(
                f"{base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                for item in data.get("data", []):
                    mid = item.get("id", "")
                    if not mid:
                        continue
                    if not (mid.startswith("gpt") or mid.startswith("o")):
                        continue
                    models.append(
                        ContractModelInfo(
                            id=mid,
                            provider="openai",
                            displayName=mid,
                            family="gpt" if mid.startswith("gpt") else "openai",
                            installed=False,
                            remote=True,
                            tags=["cloud"],
                        )
                    )
                return models
        except Exception:
            pass

    for mid in ["gpt-4o", "gpt-4.1", "gpt-4.1-mini", "o4-mini"]:
        models.append(
            ContractModelInfo(
                id=mid,
                provider="openai",
                displayName=mid,
                family="gpt" if mid.startswith("gpt") else "openai",
                installed=False,
                remote=True,
                tags=["cloud"],
            )
        )
    return models


@router.get("/{provider_name}/suggestions")
async def get_provider_model_suggestions(
    provider_name: str,
    registry=Depends(get_llm_registry)
):
    """
    Get comprehensive model suggestions for a specific provider from Model Library.
    
    Args:
        provider_name: Name of the provider
        
    Returns:
        Provider-specific model suggestions with compatibility information
    """
    try:
        spec = registry.get_provider_spec(provider_name)
        if not spec:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_name}' not found"
            )
        
        # Use the compatibility service to get suggestions
        try:
            from ai_karen_engine.core.model_runtime.compatibility.provider_model_compatibility import ProviderModelCompatibilityService
            compatibility_service = ProviderModelCompatibilityService()
            suggestions = compatibility_service.get_provider_model_suggestions(provider_name)
            
            if "error" in suggestions:
                raise HTTPException(status_code=500, detail=suggestions["error"])
            
            return suggestions
            
        except ImportError:
            # Fallback if compatibility service is not available
            return {
                "provider": provider_name,
                "provider_capabilities": {
                    "supported_formats": ["unknown"],
                    "required_capabilities": list(spec.capabilities),
                    "optional_capabilities": [],
                    "performance_type": "unknown",
                    "quantization_support": "unknown"
                },
                "recommendations": {
                    "excellent": [],
                    "good": [model.get("id", "") for model in spec.fallback_models[:3]],
                    "acceptable": []
                },
                "total_compatible_models": len(spec.fallback_models),
                "compatibility_details": {}
            }
            
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to get model suggestions for provider {provider_name}: {ex}")
        raise handle_api_exception(ex, f"Failed to get model suggestions for provider {provider_name}")


@router.get("/integration/status")
async def get_integration_status(registry=Depends(get_llm_registry)):
    """
    Get integration status between providers and Model Library.
    
    Returns:
        Integration status information including model availability and compatibility
    """
    try:
        provider_names = registry.list_llm_providers()
        integration_status = {
            "providers": {},
            "overall_status": "healthy",
            "total_providers": len(provider_names),
            "healthy_providers": 0,
            "providers_with_models": 0,
            "total_compatible_models": 0,
            "recommendations": []
        }
        
        for provider_name in provider_names:
            try:
                # Get provider health
                health = registry.get_health_status(f"provider:{provider_name}")
                is_healthy = health and health.status == "healthy"
                
                # Get model compatibility info
                try:
                    from ai_karen_engine.core.model_runtime.compatibility.provider_model_compatibility import ProviderModelCompatibilityService
                    compatibility_service = ProviderModelCompatibilityService()
                    validation = compatibility_service.validate_provider_model_setup(provider_name)
                    
                    provider_status = {
                        "name": provider_name,
                        "healthy": is_healthy,
                        "has_compatible_models": validation.get("has_compatible_models", False),
                        "has_local_models": validation.get("has_local_models", False),
                        "local_models_count": validation.get("local_models_count", 0),
                        "available_for_download": validation.get("available_for_download", 0),
                        "total_compatible": validation.get("total_compatible", 0),
                        "status": validation.get("status", "unknown"),
                        "recommendations": validation.get("recommendations", [])
                    }
                    
                    if is_healthy:
                        integration_status["healthy_providers"] += 1
                    
                    if validation.get("has_compatible_models", False):
                        integration_status["providers_with_models"] += 1
                    
                    integration_status["total_compatible_models"] += validation.get("total_compatible", 0)
                    
                except ImportError:
                    # Fallback without compatibility service
                    spec = registry.get_provider_spec(provider_name)
                    provider_status = {
                        "name": provider_name,
                        "healthy": is_healthy,
                        "has_compatible_models": len(spec.fallback_models) > 0 if spec else False,
                        "has_local_models": False,  # Can't determine without compatibility service
                        "local_models_count": 0,
                        "available_for_download": len(spec.fallback_models) if spec else 0,
                        "total_compatible": len(spec.fallback_models) if spec else 0,
                        "status": "unknown",
                        "recommendations": ["Install Model Library compatibility service for full integration"]
                    }
                    
                    if is_healthy:
                        integration_status["healthy_providers"] += 1
                
                integration_status["providers"][provider_name] = provider_status
                
            except Exception as e:
                logger.warning(f"Failed to get integration status for {provider_name}: {e}")
                integration_status["providers"][provider_name] = {
                    "name": provider_name,
                    "healthy": False,
                    "has_compatible_models": False,
                    "has_local_models": False,
                    "local_models_count": 0,
                    "available_for_download": 0,
                    "total_compatible": 0,
                    "status": "error",
                    "recommendations": [f"Error checking integration: {e}"]
                }
        
        # Determine overall status
        if integration_status["healthy_providers"] == 0:
            integration_status["overall_status"] = "unhealthy"
        elif integration_status["providers_with_models"] == 0:
            integration_status["overall_status"] = "needs_models"
        elif integration_status["healthy_providers"] < integration_status["total_providers"] // 2:
            integration_status["overall_status"] = "degraded"
        
        # Add overall recommendations
        if integration_status["providers_with_models"] == 0:
            integration_status["recommendations"].append("No providers have compatible models. Visit Model Library to download models.")
        elif integration_status["providers_with_models"] < integration_status["total_providers"]:
            integration_status["recommendations"].append("Some providers need compatible models. Check Model Library for recommendations.")
        
        return integration_status
        
    except Exception as ex:
        logger.error(f"Failed to get integration status: {ex}")
        raise handle_api_exception(ex, "Failed to get integration status")


@router.get("/{provider_name}/model-recommendations")
async def get_provider_model_recommendations(
    provider_name: str,
    limit: int = 10,
    registry=Depends(get_llm_registry)
):
    """
    Get model recommendations for a specific provider from Model Library.
    
    Args:
        provider_name: Name of the provider
        limit: Maximum number of recommendations to return
        
    Returns:
        Provider-specific model recommendations with compatibility information
    """
    try:
        spec = registry.get_provider_spec(provider_name)
        if not spec:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_name}' not found"
            )
        
        # Get recommendations from Model Library compatibility service
        try:
            from ai_karen_engine.core.model_runtime.compatibility.provider_model_compatibility import ProviderModelCompatibilityService
            compatibility_service = ProviderModelCompatibilityService()
            
            # Get comprehensive suggestions
            suggestions = compatibility_service.get_provider_model_suggestions(provider_name)
            
            if "error" in suggestions:
                return {
                    "provider": provider_name,
                    "recommendations": [],
                    "error": suggestions["error"],
                    "fallback_models": spec.fallback_models
                }
            
            return {
                "provider": provider_name,
                "provider_capabilities": suggestions.get("provider_capabilities", {}),
                "recommendations": suggestions.get("recommendations", {}),
                "total_compatible_models": suggestions.get("total_compatible_models", 0),
                "compatibility_details": suggestions.get("compatibility_details", {}),
                "validation": compatibility_service.validate_provider_model_setup(provider_name)
            }
            
        except Exception as e:
            logger.warning(f"Failed to get Model Library recommendations for {provider_name}: {e}")
            
            # Fallback to provider's own models
            return {
                "provider": provider_name,
                "recommendations": {
                    "fallback": [model.get("id", model.get("name", "")) for model in spec.fallback_models]
                },
                "total_compatible_models": len(spec.fallback_models),
                "error": f"Model Library unavailable: {str(e)}",
                "fallback_models": spec.fallback_models
            }
        
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to get model recommendations for {provider_name}: {ex}")
        raise handle_api_exception(ex, f"Failed to get recommendations for provider {provider_name}")


# Export the router
__all__ = ["router"]
@router.get("/{provider_name}/health")
async def check_provider_health(provider_name: str, registry=Depends(get_llm_registry)):
    """Check health of a single provider."""
    try:
        status = registry.health_check(f"provider:{provider_name}")
        return {
            "name": provider_name,
            "status": status.status,
            "last_check": status.last_check,
            "error_message": status.error_message,
            "response_time": status.response_time,
            "capabilities": status.capabilities,
        }
    except Exception as ex:
        logger.error(f"Health check failed for {provider_name}: {ex}")
        return handle_api_exception(ex, f"Failed to check health for {provider_name}")


@router.post("/{provider_name}/disable")
async def disable_provider(provider_name: str, registry=Depends(get_llm_registry)):
    """Disable a provider without unregistering it."""
    try:
        ok = registry.disable_provider(provider_name)
        if not ok:
            raise HTTPException(status_code=404, detail="Provider not found")
        return {"success": True, "provider": provider_name, "disabled": True}
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Disable provider failed for {provider_name}: {ex}")
        return handle_api_exception(ex, f"Failed to disable provider {provider_name}")


@router.post("/{provider_name}/enable")
async def enable_provider(provider_name: str, registry=Depends(get_llm_registry)):
    """Enable a previously disabled provider."""
    try:
        ok = registry.enable_provider(provider_name)
        if not ok:
            raise HTTPException(status_code=404, detail="Provider not found")
        return {"success": True, "provider": provider_name, "disabled": False}
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Enable provider failed for {provider_name}: {ex}")
        return handle_api_exception(ex, f"Failed to enable provider {provider_name}")

# -----------------------------
# Extended Provider Management API Endpoints (Task 6.2)
# -----------------------------

class ProviderValidationRequest(BaseModel):
    """Enhanced provider validation request."""
    provider_id: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    test_model_discovery: bool = True
    timeout: int = 10


class ProviderValidationResponse(BaseModel):
    """Enhanced provider validation response."""
    provider_id: str
    valid: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    models_discovered: Optional[int] = None
    capabilities_detected: List[str] = Field(default_factory=list)
    response_time: Optional[float] = None
    error_code: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)


class ProviderHealthResponse(BaseModel):
    """Enhanced provider health response."""
    provider_id: str
    status: str  # healthy, degraded, unhealthy, unknown
    message: str
    last_check: float
    response_time: Optional[float] = None
    error_details: Optional[Dict[str, Any]] = None
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    model_availability: Dict[str, Any] = Field(default_factory=dict)
    rate_limit_status: Optional[Dict[str, Any]] = None


class LLMHealthSummary(BaseModel):
    """LLM system health summary."""
    overall_status: str  # healthy, degraded, critical
    healthy_providers: List[str]
    degraded_providers: List[str]
    unhealthy_providers: List[str]
    total_models_available: int
    local_models_count: int
    remote_models_count: int
    degraded_mode_active: bool
    last_health_check: float
    recommendations: List[str] = Field(default_factory=list)


@router.post("/validate", response_model=ProviderValidationResponse)
async def validate_provider_enhanced(
    request: ProviderValidationRequest,
    registry=Depends(get_llm_registry)
):
    """
    Enhanced API key validation with detailed feedback and model discovery.
    
    This endpoint provides real-time validation with comprehensive feedback,
    model discovery testing, and actionable suggestions for configuration issues.
    """
    start_time = time.time()
    
    try:
        provider_id = request.provider_id
        
        # Get provider spec
        spec = registry.get_provider_spec(provider_id)
        if not spec:
            return ProviderValidationResponse(
                provider_id=provider_id,
                valid=False,
                message=f"Provider '{provider_id}' not found",
                error_code="PROVIDER_NOT_FOUND",
                suggestions=[
                    "Check the provider ID spelling",
                    "Ensure the provider is registered in the system",
                    f"Available providers: {', '.join(registry.list_providers())}"
                ]
            )
        
        # Check if provider requires API key
        if not spec.requires_api_key:
            return ProviderValidationResponse(
                provider_id=provider_id,
                valid=True,
                message=f"Provider '{provider_id}' does not require API key validation",
                details={"provider_type": "local", "requires_setup": False},
                models_discovered=len(spec.fallback_models),
                capabilities_detected=list(spec.capabilities),
                response_time=time.time() - start_time
            )
        
        # Validate API key is provided
        api_key = request.api_key
        if not api_key:
            return ProviderValidationResponse(
                provider_id=provider_id,
                valid=False,
                message="API key is required for this provider",
                error_code="API_KEY_MISSING",
                suggestions=[
                    f"Obtain an API key from {spec.description}",
                    "Check environment variables for existing key",
                    "Ensure the API key is properly formatted"
                ]
            )
        
        # Perform validation using dynamic provider system
        try:
            from ai_karen_engine.integrations.dynamic_provider_system import get_dynamic_provider_manager
            
            provider_manager = get_dynamic_provider_manager()
            
            # Validate API key
            validation_config = {
                "api_key": api_key,
                "base_url": request.base_url,
                **request.config
            }
            
            validation_result = await provider_manager.validate_api_key(provider_id, validation_config)
            
            response = ProviderValidationResponse(
                provider_id=provider_id,
                valid=validation_result["valid"],
                message=validation_result["message"],
                response_time=time.time() - start_time
            )
            
            if validation_result["valid"]:
                # Test model discovery if requested
                if request.test_model_discovery:
                    try:
                        models = await provider_manager.discover_models(provider_id, force_refresh=True)
                        response.models_discovered = len(models)
                        response.details["model_discovery"] = "successful"
                        response.details["sample_models"] = [m.get("id", "unknown") for m in models[:3]]
                    except Exception as e:
                        logger.warning(f"Model discovery failed during validation for {provider_id}: {e}")
                        response.models_discovered = len(spec.fallback_models)
                        response.details["model_discovery"] = "failed"
                        response.details["model_discovery_error"] = str(e)
                        response.suggestions.append("Model discovery failed, but API key is valid")
                
                # Detect capabilities
                response.capabilities_detected = list(spec.capabilities)
                response.details["provider_type"] = "remote"
                response.details["api_base_url"] = getattr(spec, "api_base_url", None)
                
            else:
                # Provide specific error guidance
                error_message = validation_result["message"].lower()
                if "invalid" in error_message or "unauthorized" in error_message:
                    response.error_code = "INVALID_API_KEY"
                    response.suggestions = [
                        "Verify the API key is correct and active",
                        "Check if the API key has the required permissions",
                        "Ensure the API key hasn't expired"
                    ]
                elif "rate limit" in error_message:
                    response.error_code = "RATE_LIMITED"
                    response.suggestions = [
                        "Wait before retrying the validation",
                        "Check your API usage limits",
                        "Consider upgrading your API plan"
                    ]
                elif "timeout" in error_message:
                    response.error_code = "TIMEOUT"
                    response.suggestions = [
                        "Check your internet connection",
                        "Try again in a few moments",
                        "Verify the provider's service status"
                    ]
                else:
                    response.error_code = "VALIDATION_FAILED"
                    response.suggestions = [
                        "Check the provider's documentation",
                        "Verify your account status",
                        "Contact the provider's support if the issue persists"
                    ]
            
            return response
            
        except Exception as e:
            logger.error(f"Enhanced validation failed for {provider_id}: {e}")
            return ProviderValidationResponse(
                provider_id=provider_id,
                valid=False,
                message=f"Validation error: {str(e)}",
                error_code="VALIDATION_ERROR",
                response_time=time.time() - start_time,
                suggestions=[
                    "Check your network connection",
                    "Verify the provider service is available",
                    "Try again in a few moments"
                ]
            )
        
    except Exception as ex:
        logger.error(f"Failed to validate provider {request.provider_id}: {ex}")
        return ProviderValidationResponse(
            provider_id=request.provider_id,
            valid=False,
            message=f"System error during validation: {str(ex)}",
            error_code="SYSTEM_ERROR",
            response_time=time.time() - start_time
        )


@router.get("/{provider_id}/models/dynamic", response_model=List[ModelInfo])
async def get_provider_models_dynamic(
    provider_id: str,
    force_refresh: bool = False,
    include_fallback: bool = True,
    registry=Depends(get_llm_registry)
):
    """
    Get models for a provider with dynamic discovery and intelligent fallbacks.
    
    This endpoint attempts live model discovery from the provider API and falls back
    to curated model lists when the API is unavailable, providing a robust model
    listing experience.
    """
    try:
        spec = registry.get_provider_spec(provider_id)
        if not spec:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found"
            )
        
        models = []
        
        # Try dynamic model discovery first
        try:
            from ai_karen_engine.integrations.dynamic_provider_system import get_dynamic_provider_manager
            
            provider_manager = get_dynamic_provider_manager()
            discovered_models = await provider_manager.discover_models(provider_id, force_refresh=force_refresh)
            
            if discovered_models:
                for model_data in discovered_models:
                    model_info = ModelInfo(
                        id=model_data.get("id", ""),
                        name=model_data.get("name", model_data.get("id", "")),
                        provider=provider_id,
                        family=model_data.get("family", ""),
                        format=model_data.get("format", ""),
                        size=model_data.get("size"),
                        parameters=model_data.get("parameters"),
                        quantization=model_data.get("quantization"),
                        context_length=model_data.get("context_length"),
                        capabilities=model_data.get("capabilities", []),
                        local_path=model_data.get("local_path"),
                        download_url=model_data.get("download_url"),
                        license=model_data.get("license"),
                        description=model_data.get("description", "")
                    )
                    models.append(model_info)
                
                logger.info(f"Successfully discovered {len(models)} models for {provider_id}")
                return models
            
        except Exception as e:
            logger.warning(f"Dynamic model discovery failed for {provider_id}: {e}")
        
        # Fall back to curated models if discovery failed or no models found
        if include_fallback and spec.fallback_models:
            logger.info(f"Using fallback models for {provider_id}")
            for model_data in spec.fallback_models:
                model_info = ModelInfo(
                    id=model_data.get("id", ""),
                    name=model_data.get("name", model_data.get("id", "")),
                    provider=provider_id,
                    family=model_data.get("family", ""),
                    format=model_data.get("format", ""),
                    parameters=model_data.get("parameters"),
                    context_length=model_data.get("context_length"),
                    capabilities=model_data.get("capabilities", []),
                    description=model_data.get("description", "Curated model (API discovery unavailable)")
                )
                models.append(model_info)
        
        return models
        
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to get models for provider {provider_id}: {ex}")
        raise handle_api_exception(ex, f"Failed to get models for provider {provider_id}")


@router.get("/health/llms", response_model=LLMHealthSummary)
async def get_llm_health_summary(registry=Depends(get_llm_registry)):
    """
    Get comprehensive health summary for all LLM providers and runtimes.
    
    This endpoint provides a system-wide health overview including provider status,
    model availability, and recommendations for improving system reliability.
    """
    try:
        start_time = time.time()
        
        # Get all LLM providers
        llm_providers = registry.list_llm_providers()
        
        healthy_providers = []
        degraded_providers = []
        unhealthy_providers = []
        
        total_models = 0
        local_models = 0
        remote_models = 0
        
        # Check health of each provider
        for provider_name in llm_providers:
            try:
                health = registry.health_check(f"provider:{provider_name}")
                spec = registry.get_provider_spec(provider_name)
                
                if health.status == "healthy":
                    healthy_providers.append(provider_name)
                elif health.status == "degraded":
                    degraded_providers.append(provider_name)
                else:
                    unhealthy_providers.append(provider_name)
                
                # Count models
                if spec:
                    model_count = len(spec.fallback_models)
                    total_models += model_count
                    
                    if spec.requires_api_key:
                        remote_models += model_count
                    else:
                        local_models += model_count
                        
            except Exception as e:
                logger.warning(f"Health check failed for {provider_name}: {e}")
                unhealthy_providers.append(provider_name)
        
        # Determine overall system status
        total_providers = len(llm_providers)
        healthy_ratio = len(healthy_providers) / total_providers if total_providers > 0 else 0
        
        if healthy_ratio >= 0.8:
            overall_status = "healthy"
        elif healthy_ratio >= 0.5:
            overall_status = "degraded"
        else:
            overall_status = "critical"
        
        # Check if degraded mode is active
        degraded_mode_active = overall_status in ["degraded", "critical"]
        
        # Generate recommendations
        recommendations = []
        
        if len(unhealthy_providers) > 0:
            recommendations.append(f"Check configuration for unhealthy providers: {', '.join(unhealthy_providers)}")
        
        if len(degraded_providers) > 0:
            recommendations.append(f"Monitor degraded providers: {', '.join(degraded_providers)}")
        
        if local_models == 0:
            recommendations.append("Consider setting up local models for offline capability")
        
        if remote_models == 0 and len(healthy_providers) == 0:
            recommendations.append("Configure at least one cloud provider for enhanced capabilities")
        
        if degraded_mode_active:
            recommendations.append("System is in degraded mode - check provider configurations and network connectivity")
        
        if total_models < 5:
            recommendations.append("Consider adding more model options for better flexibility")
        
        return LLMHealthSummary(
            overall_status=overall_status,
            healthy_providers=healthy_providers,
            degraded_providers=degraded_providers,
            unhealthy_providers=unhealthy_providers,
            total_models_available=total_models,
            local_models_count=local_models,
            remote_models_count=remote_models,
            degraded_mode_active=degraded_mode_active,
            last_health_check=start_time,
            recommendations=recommendations
        )
        
    except Exception as ex:
        logger.error(f"Failed to get LLM health summary: {ex}")
        raise handle_api_exception(ex, "Failed to get LLM health summary")


@router.get("/{provider_id}/health/detailed", response_model=ProviderHealthResponse)
async def get_provider_health_detailed(
    provider_id: str,
    include_models: bool = True,
    registry=Depends(get_llm_registry)
):
    """
    Get detailed health information for a specific provider.
    
    This endpoint provides comprehensive health diagnostics including model availability,
    rate limiting status, and detailed error information for troubleshooting.
    """
    try:
        spec = registry.get_provider_spec(provider_id)
        if not spec:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found"
            )
        
        start_time = time.time()
        
        # Perform health check
        health = registry.health_check(f"provider:{provider_id}")
        
        response = ProviderHealthResponse(
            provider_id=provider_id,
            status=health.status,
            message=health.message or f"Health check for {provider_id}",
            last_check=health.last_check or start_time,
            response_time=health.response_time,
            capabilities={
                "requires_api_key": spec.requires_api_key,
                "supports_streaming": "streaming" in spec.capabilities,
                "supports_embeddings": "embeddings" in spec.capabilities,
                "supports_function_calling": "function_calling" in spec.capabilities,
                "local_execution": "local_execution" in spec.capabilities,
                "provider_type": getattr(spec, "provider_type", "unknown")
            }
        )
        
        # Add error details if unhealthy
        if health.status != "healthy" and health.error_message:
            response.error_details = {
                "error_message": health.error_message,
                "error_type": "health_check_failed",
                "timestamp": health.last_check
            }
        
        # Check model availability if requested
        if include_models:
            try:
                # Try to get model count
                if spec.discover:
                    try:
                        models = spec.discover()
                        model_count = len(models) if models else 0
                        response.model_availability = {
                            "total_models": model_count,
                            "discovery_successful": True,
                            "last_discovery": time.time()
                        }
                    except Exception as e:
                        response.model_availability = {
                            "total_models": len(spec.fallback_models),
                            "discovery_successful": False,
                            "discovery_error": str(e),
                            "fallback_models_available": len(spec.fallback_models)
                        }
                else:
                    response.model_availability = {
                        "total_models": len(spec.fallback_models),
                        "discovery_supported": False,
                        "fallback_models_available": len(spec.fallback_models)
                    }
                    
            except Exception as e:
                logger.warning(f"Failed to check model availability for {provider_id}: {e}")
                response.model_availability = {
                    "error": str(e),
                    "check_failed": True
                }
        
        # Check rate limiting status for API-based providers
        if spec.requires_api_key:
            try:
                # This would be implemented based on provider-specific rate limiting info
                response.rate_limit_status = {
                    "rate_limited": False,
                    "requests_remaining": "unknown",
                    "reset_time": None,
                    "note": "Rate limit status not implemented for this provider"
                }
            except Exception:
                pass
        
        return response
        
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to get detailed health for provider {provider_id}: {ex}")
        raise handle_api_exception(ex, f"Failed to get detailed health for provider {provider_id}")


@router.post("/{provider_id}/refresh-models")
async def refresh_provider_models(
    provider_id: str,
    registry=Depends(get_llm_registry)
):
    """
    Force refresh of model cache for a specific provider.
    
    This endpoint triggers a fresh model discovery from the provider API,
    bypassing any cached results.
    """
    try:
        spec = registry.get_provider_spec(provider_id)
        if not spec:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found"
            )
        
        start_time = time.time()
        
        # Force refresh using dynamic provider system
        try:
            from ai_karen_engine.integrations.dynamic_provider_system import get_dynamic_provider_manager
            
            provider_manager = get_dynamic_provider_manager()
            models = await provider_manager.discover_models(provider_id, force_refresh=True)
            
            return {
                "provider_id": provider_id,
                "success": True,
                "models_discovered": len(models),
                "refresh_time": time.time() - start_time,
                "message": f"Successfully refreshed {len(models)} models for {provider_id}"
            }
            
        except Exception as e:
            logger.error(f"Model refresh failed for {provider_id}: {e}")
            return {
                "provider_id": provider_id,
                "success": False,
                "error": str(e),
                "refresh_time": time.time() - start_time,
                "message": f"Failed to refresh models for {provider_id}: {str(e)}"
            }
        
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to refresh models for provider {provider_id}: {ex}")


# ----------------- Provider Notification Endpoints -----------------

class NotificationSettings(BaseModel):
    """Provider notification settings model."""
    enabled: bool = True
    email_notifications: bool = False
    push_notifications: bool = True
    model_updates: bool = True
    health_alerts: bool = True
    performance_alerts: bool = False


class ProviderNotification(BaseModel):
    """Provider notification model."""
    id: str
    type: str  # info, warning, error, success
    title: str
    message: str
    provider_id: Optional[str] = None
    timestamp: float
    read: bool = False
    action_url: Optional[str] = None


@router.get("/notifications", response_model=List[ProviderNotification])
async def get_provider_notifications():
    """
    Get provider notifications.
    
    Returns:
        List of provider notifications
    """
    try:
        # For now, return mock notifications
        # In a real implementation, this would fetch from a database or notification service
        notifications = [
            ProviderNotification(
                id="1",
                type="info",
                title="OpenAI Models Updated",
                message="New GPT-4 models are now available",
                provider_id="openai",
                timestamp=time.time() - 3600,  # 1 hour ago
                read=False
            ),
            ProviderNotification(
                id="2",
                type="warning",
                title="Local Model Performance",
                message="Local GGUF models are running slower than expected",
                provider_id="local_gguf",
                timestamp=time.time() - 7200,  # 2 hours ago
                read=False
            )
        ]
        
        return notifications
        
    except Exception as ex:
        logger.error(f"Failed to get provider notifications: {ex}")
        raise handle_api_exception(ex, "Failed to get provider notifications")


@router.get("/notifications/settings", response_model=NotificationSettings)
async def get_notification_settings():
    """
    Get provider notification settings.
    
    Returns:
        Current notification settings
    """
    try:
        # For now, return default settings
        # In a real implementation, this would fetch from user preferences
        return NotificationSettings(
            enabled=True,
            email_notifications=False,
            push_notifications=True,
            model_updates=True,
            health_alerts=True,
            performance_alerts=False
        )
        
    except Exception as ex:
        logger.error(f"Failed to get notification settings: {ex}")
        raise handle_api_exception(ex, "Failed to get notification settings")


@router.put("/notifications/settings", response_model=NotificationSettings)
async def update_notification_settings(settings: NotificationSettings):
    """
    Update provider notification settings.
    
    Args:
        settings: New notification settings
        
    Returns:
        Updated notification settings
    """
    try:
        # For now, just return the provided settings
        # In a real implementation, this would save to user preferences
        logger.info(f"Updated notification settings: {settings}")
        return settings
        
    except Exception as ex:
        logger.error(f"Failed to update notification settings: {ex}")
        raise handle_api_exception(ex, "Failed to update notification settings")


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    """
    Mark a notification as read.
    
    Args:
        notification_id: ID of the notification to mark as read
        
    Returns:
        Success message
    """
    try:
        # For now, just log the action
        # In a real implementation, this would update the notification in the database
        logger.info(f"Marked notification {notification_id} as read")
        return {"success": True, "message": f"Notification {notification_id} marked as read"}
        
    except Exception as ex:
        logger.error(f"Failed to mark notification as read: {ex}")
        raise handle_api_exception(ex, "Failed to mark notification as read")


@router.get("/notifications/stream")
async def get_notification_stream():
    """
    Get real-time notification stream (Server-Sent Events).
    
    This endpoint would typically return an EventSource stream for real-time notifications.
    For now, it returns a 404 to indicate the feature is not implemented.
    """
    raise HTTPException(
        status_code=404, 
        detail="Real-time notification stream not implemented yet"
    )

