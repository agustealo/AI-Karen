"""
Provider Model Compatibility Service

This service manages model compatibility checks and recommendations for different LLM providers.
It integrates with the Model Library to provide provider-specific model suggestions and
compatibility validation.
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("kari.provider_model_compatibility")

@dataclass
class ModelCompatibility:
    """Model compatibility information for a provider."""
    model_id: str
    provider: str
    compatible: bool
    compatibility_score: float  # 0.0 to 1.0
    reasons: List[str]
    requirements: Dict[str, Any]
    recommendations: List[str]

@dataclass
class ProviderCapabilities:
    """Provider capabilities and requirements."""
    name: str
    supported_formats: List[str]
    required_capabilities: List[str]
    optional_capabilities: List[str]
    memory_requirements: Dict[str, int]  # min, recommended, max
    performance_characteristics: Dict[str, str]
    model_size_limits: Dict[str, int]  # min_size, max_size in bytes

class ProviderModelCompatibilityService:
    """Service for managing provider-model compatibility and recommendations."""
    
    def __init__(self):
        self.provider_capabilities = self._initialize_provider_capabilities()
        self.compatibility_cache: Dict[str, ModelCompatibility] = {}
    
    def _initialize_provider_capabilities(self) -> Dict[str, ProviderCapabilities]:
        """Initialize provider capabilities and requirements."""
        return {
            "local_gguf": ProviderCapabilities(
                name="local_gguf",
                supported_formats=["gguf", "ggml"],
                required_capabilities=["text-generation"],
                optional_capabilities=["chat", "instruction-following", "embeddings"],
                memory_requirements={
                    "min": 512 * 1024 * 1024,  # 512MB
                    "recommended": 2 * 1024 * 1024 * 1024,  # 2GB
                    "max": 32 * 1024 * 1024 * 1024  # 32GB
                },
                performance_characteristics={
                    "inference_type": "local",
                    "optimization": "cpu_gpu_hybrid",
                    "quantization_support": "excellent"
                },
                model_size_limits={
                    "min_size": 100 * 1024 * 1024,  # 100MB
                    "max_size": 50 * 1024 * 1024 * 1024  # 50GB
                }
            ),
            "openai": ProviderCapabilities(
                name="openai",
                supported_formats=["api"],
                required_capabilities=["text-generation", "chat"],
                optional_capabilities=["function-calling", "embeddings", "vision"],
                memory_requirements={
                    "min": 0,  # API-based, no local memory requirements
                    "recommended": 0,
                    "max": 0
                },
                performance_characteristics={
                    "inference_type": "cloud",
                    "optimization": "api_optimized",
                    "quantization_support": "none"
                },
                model_size_limits={
                    "min_size": 0,
                    "max_size": 0  # No size limits for API models
                }
            ),
            "huggingface": ProviderCapabilities(
                name="huggingface",
                supported_formats=["transformers", "safetensors", "pytorch"],
                required_capabilities=["text-generation"],
                optional_capabilities=["chat", "instruction-following", "embeddings", "classification"],
                memory_requirements={
                    "min": 1 * 1024 * 1024 * 1024,  # 1GB
                    "recommended": 8 * 1024 * 1024 * 1024,  # 8GB
                    "max": 80 * 1024 * 1024 * 1024  # 80GB
                },
                performance_characteristics={
                    "inference_type": "local",
                    "optimization": "gpu_preferred",
                    "quantization_support": "good"
                },
                model_size_limits={
                    "min_size": 50 * 1024 * 1024,  # 50MB
                    "max_size": 100 * 1024 * 1024 * 1024  # 100GB
                }
            ),
            "gemini": ProviderCapabilities(
                name="gemini",
                supported_formats=["api"],
                required_capabilities=["text-generation", "chat"],
                optional_capabilities=["vision", "function-calling", "embeddings"],
                memory_requirements={
                    "min": 0,
                    "recommended": 0,
                    "max": 0
                },
                performance_characteristics={
                    "inference_type": "cloud",
                    "optimization": "api_optimized",
                    "quantization_support": "none"
                },
                model_size_limits={
                    "min_size": 0,
                    "max_size": 0
                }
            )
        }
    
    def check_model_compatibility(self, model_id: str, provider_name: str) -> ModelCompatibility:
        """Check if a model is compatible with a specific provider."""
        cache_key = f"{model_id}:{provider_name}"
        
        if cache_key in self.compatibility_cache:
            return self.compatibility_cache[cache_key]
        
        try:
            from ai_karen_engine.core.services.service_registry import (
                get_model_library_service,
            )

            model_library = get_model_library_service()
            model_info = model_library.get_model_info(model_id)
            
            if not model_info:
                compatibility = ModelCompatibility(
                    model_id=model_id,
                    provider=provider_name,
                    compatible=False,
                    compatibility_score=0.0,
                    reasons=["Model not found in Model Library"],
                    requirements={},
                    recommendations=["Ensure model is available in Model Library"]
                )
                self.compatibility_cache[cache_key] = compatibility
                return compatibility
            
            provider_caps = self.provider_capabilities.get(provider_name)
            if not provider_caps:
                compatibility = ModelCompatibility(
                    model_id=model_id,
                    provider=provider_name,
                    compatible=False,
                    compatibility_score=0.0,
                    reasons=["Unknown provider"],
                    requirements={},
                    recommendations=["Use a supported provider"]
                )
                self.compatibility_cache[cache_key] = compatibility
                return compatibility
            
            # Perform compatibility checks
            compatibility = self._evaluate_compatibility(model_info, provider_caps)
            self.compatibility_cache[cache_key] = compatibility
            return compatibility
            
        except Exception as e:
            logger.error(f"Failed to check compatibility for {model_id} with {provider_name}: {e}")
            compatibility = ModelCompatibility(
                model_id=model_id,
                provider=provider_name,
                compatible=False,
                compatibility_score=0.0,
                reasons=[f"Compatibility check failed: {e}"],
                requirements={},
                recommendations=["Check model and provider configuration"]
            )
            self.compatibility_cache[cache_key] = compatibility
            return compatibility
    
    def _evaluate_compatibility(self, model_info, provider_caps: ProviderCapabilities) -> ModelCompatibility:
        """Evaluate model compatibility with provider capabilities."""
        reasons = []
        recommendations = []
        score = 1.0
        compatible = True
        
        # Check provider match
        if model_info.provider != provider_caps.name:
            if provider_caps.name == "local_gguf" and model_info.provider in ["gguf", "llama"]:
                # Allow GGUF models for the local GGUF runtime
                reasons.append("Model format compatible with provider")
            elif provider_caps.name == "huggingface" and model_info.provider in ["transformers", "hf"]:
                # Allow transformers models for huggingface
                reasons.append("Model format compatible with provider")
            else:
                compatible = False
                score = 0.0
                reasons.append(f"Model provider '{model_info.provider}' not compatible with '{provider_caps.name}'")
                recommendations.append(f"Use a model designed for {provider_caps.name}")
                
                return ModelCompatibility(
                    model_id=model_info.id,
                    provider=provider_caps.name,
                    compatible=compatible,
                    compatibility_score=score,
                    reasons=reasons,
                    requirements={
                        "provider_match": False,
                        "required_provider": provider_caps.name,
                        "actual_provider": model_info.provider
                    },
                    recommendations=recommendations
                )
        
        # Check model size limits
        if model_info.size:
            if (provider_caps.model_size_limits["min_size"] > 0 and 
                model_info.size < provider_caps.model_size_limits["min_size"]):
                compatible = False
                score *= 0.5
                reasons.append(f"Model too small ({model_info.size} bytes)")
                recommendations.append("Use a larger model")
            
            if (provider_caps.model_size_limits["max_size"] > 0 and 
                model_info.size > provider_caps.model_size_limits["max_size"]):
                score *= 0.7
                reasons.append(f"Model very large ({model_info.size} bytes), may have performance issues")
                recommendations.append("Consider using a smaller or quantized model")
        
        # Check capabilities
        model_capabilities = set(model_info.capabilities or [])
        required_capabilities = set(provider_caps.required_capabilities)
        
        missing_capabilities = required_capabilities - model_capabilities
        if missing_capabilities:
            score *= 0.6
            reasons.append(f"Missing required capabilities: {', '.join(missing_capabilities)}")
            recommendations.append("Ensure model supports required capabilities")
        
        # Check optional capabilities (bonus points)
        optional_capabilities = set(provider_caps.optional_capabilities)
        supported_optional = model_capabilities & optional_capabilities
        if supported_optional:
            bonus = len(supported_optional) / len(optional_capabilities) * 0.2
            score = min(1.0, score + bonus)
            reasons.append(f"Supports optional capabilities: {', '.join(supported_optional)}")
        
        # Check memory requirements for local providers
        if provider_caps.memory_requirements["min"] > 0 and model_info.metadata:
            memory_req = model_info.metadata.get("memory_requirement", "")
            if memory_req:
                # Parse memory requirement (e.g., "~1GB", "2-4GB")
                try:
                    # Simple parsing for common formats
                    if "GB" in memory_req:
                        mem_gb = float(memory_req.replace("~", "").replace("GB", "").split("-")[0])
                        mem_bytes = mem_gb * 1024 * 1024 * 1024
                        
                        if mem_bytes > provider_caps.memory_requirements["recommended"]:
                            score *= 0.8
                            reasons.append(f"High memory requirement: {memory_req}")
                            recommendations.append("Ensure sufficient system memory")
                        elif mem_bytes < provider_caps.memory_requirements["min"]:
                            score *= 0.9
                            reasons.append(f"Low memory model: {memory_req}")
                except:
                    pass  # Ignore parsing errors
        
        # Check quantization compatibility
        if model_info.metadata and "quantization" in model_info.metadata:
            quantization = model_info.metadata["quantization"]
            if quantization != "none" and provider_caps.performance_characteristics.get("quantization_support") == "excellent":
                score = min(1.0, score + 0.1)
                reasons.append(f"Optimized with {quantization} quantization")
            elif quantization != "none" and provider_caps.performance_characteristics.get("quantization_support") == "none":
                score *= 0.9
                reasons.append("Quantized model may not be fully supported")
        
        # Final compatibility determination
        if score < 0.3:
            compatible = False
        
        requirements = {
            "provider_match": model_info.provider == provider_caps.name,
            "size_compatible": True,  # Detailed in reasons if not
            "capabilities_met": len(missing_capabilities) == 0,
            "memory_suitable": True  # Detailed in reasons if not
        }
        
        return ModelCompatibility(
            model_id=model_info.id,
            provider=provider_caps.name,
            compatible=compatible,
            compatibility_score=score,
            reasons=reasons,
            requirements=requirements,
            recommendations=recommendations
        )
    
    def get_recommended_models_for_provider(self, provider_name: str, 
                                          limit: int = 10) -> List[ModelCompatibility]:
        """Get recommended models for a specific provider."""
        try:
            from ai_karen_engine.core.services.service_registry import (
                get_model_library_service,
            )

            model_library = get_model_library_service()
            available_models = model_library.get_available_models()
            
            recommendations = []
            
            for model_info in available_models:
                compatibility = self.check_model_compatibility(model_info.id, provider_name)
                if compatibility.compatible and compatibility.compatibility_score > 0.5:
                    recommendations.append(compatibility)
            
            # Sort by compatibility score (descending)
            recommendations.sort(key=lambda x: x.compatibility_score, reverse=True)
            
            return recommendations[:limit]
            
        except Exception as e:
            logger.error(f"Failed to get recommendations for {provider_name}: {e}")
            return []
    
    def get_provider_model_suggestions(self, provider_name: str) -> Dict[str, Any]:
        """Get comprehensive model suggestions for a provider."""
        try:
            provider_caps = self.provider_capabilities.get(provider_name)
            if not provider_caps:
                return {"error": "Unknown provider"}
            
            recommendations = self.get_recommended_models_for_provider(provider_name)
            
            # Categorize recommendations
            excellent_models = [r for r in recommendations if r.compatibility_score >= 0.9]
            good_models = [r for r in recommendations if 0.7 <= r.compatibility_score < 0.9]
            acceptable_models = [r for r in recommendations if 0.5 <= r.compatibility_score < 0.7]
            
            return {
                "provider": provider_name,
                "provider_capabilities": {
                    "supported_formats": provider_caps.supported_formats,
                    "required_capabilities": provider_caps.required_capabilities,
                    "optional_capabilities": provider_caps.optional_capabilities,
                    "performance_type": provider_caps.performance_characteristics.get("inference_type"),
                    "quantization_support": provider_caps.performance_characteristics.get("quantization_support")
                },
                "recommendations": {
                    "excellent": [r.model_id for r in excellent_models],
                    "good": [r.model_id for r in good_models],
                    "acceptable": [r.model_id for r in acceptable_models]
                },
                "total_compatible_models": len(recommendations),
                "compatibility_details": {
                    r.model_id: {
                        "score": r.compatibility_score,
                        "reasons": r.reasons,
                        "recommendations": r.recommendations
                    } for r in recommendations[:5]  # Top 5 details
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get provider suggestions for {provider_name}: {e}")
            return {"error": str(e)}
    
    def validate_provider_model_setup(self, provider_name: str) -> Dict[str, Any]:
        """Validate that a provider has compatible models available."""
        try:
            recommendations = self.get_recommended_models_for_provider(provider_name)
            
            # Check for local models
            local_models = []
            available_models = []
            
            for rec in recommendations:
                try:
                    from ai_karen_engine.core.services.service_registry import (
                        get_model_library_service,
                    )

                    model_library = get_model_library_service()
                    model_info = model_library.get_model_info(rec.model_id)
                    
                    if model_info:
                        if model_info.status == "local":
                            local_models.append(rec)
                        elif model_info.status == "available":
                            available_models.append(rec)
                except:
                    continue
            
            validation_result = {
                "provider": provider_name,
                "has_compatible_models": len(recommendations) > 0,
                "has_local_models": len(local_models) > 0,
                "local_models_count": len(local_models),
                "available_for_download": len(available_models),
                "total_compatible": len(recommendations),
                "status": "healthy" if len(local_models) > 0 else "needs_models",
                "recommendations": []
            }
            
            if len(local_models) == 0:
                if len(available_models) > 0:
                    validation_result["recommendations"].append(
                        f"Download a compatible model. {len(available_models)} models available for download."
                    )
                    validation_result["suggested_downloads"] = [r.model_id for r in available_models[:3]]
                else:
                    validation_result["recommendations"].append(
                        "No compatible models found. Check Model Library for available models."
                    )
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Failed to validate provider setup for {provider_name}: {e}")
            return {
                "provider": provider_name,
                "has_compatible_models": False,
                "status": "error",
                "error": str(e)
            }
    
    def clear_compatibility_cache(self):
        """Clear the compatibility cache."""
        self.compatibility_cache.clear()
        logger.info("Compatibility cache cleared")
    
    def get_compatibility_statistics(self) -> Dict[str, Any]:
        """Get statistics about model compatibility across providers."""
        try:
            from ai_karen_engine.core.services.service_registry import (
                get_model_library_service,
            )

            model_library = get_model_library_service()
            available_models = model_library.get_available_models()
            
            stats = {
                "total_models": len(available_models),
                "providers": {},
                "compatibility_matrix": {}
            }
            
            for provider_name in self.provider_capabilities.keys():
                compatible_models = self.get_recommended_models_for_provider(provider_name)
                
                stats["providers"][provider_name] = {
                    "compatible_models": len(compatible_models),
                    "excellent_models": len([m for m in compatible_models if m.compatibility_score >= 0.9]),
                    "good_models": len([m for m in compatible_models if 0.7 <= m.compatibility_score < 0.9]),
                    "acceptable_models": len([m for m in compatible_models if 0.5 <= m.compatibility_score < 0.7])
                }
                
                stats["compatibility_matrix"][provider_name] = [m.model_id for m in compatible_models]
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get compatibility statistics: {e}")
            return {"error": str(e)}
