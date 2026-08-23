"""
Model Filtering and Recommendation Engine

Provides intelligent model filtering and recommendations that work alongside
existing ProfileManager capabilities. Enhances model selection with discovered
models while preserving existing routing logic.

Requirements implemented: 7.3, 7.4, 7.5
"""

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple
from enum import Enum
import json
from pathlib import Path

from ..discovery.model_discovery_engine import (
    ModelInfo,
    ModelType,
    ModalityType,
    ModelCategory,
    ModelSpecialization,
)
from ..routing.intelligent_model_router import (
    ModelRouter,
    RoutingDecision,
    ModelPerformanceMetrics,
)

logger = logging.getLogger("kari.model_recommendation_engine")

class RecommendationStrategy(Enum):
    """Model recommendation strategies."""
    PERFORMANCE_BASED = "performance_based"
    CAPABILITY_BASED = "capability_based"
    COMPATIBILITY_BASED = "compatibility_based"
    HYBRID = "hybrid"
    USER_PREFERENCE = "user_preference"

class FilterCriteria(Enum):
    """Model filtering criteria."""
    MODALITY = "modality"
    CAPABILITY = "capability"
    PERFORMANCE = "performance"
    PROVIDER = "provider"
    SIZE = "size"
    SPECIALIZATION = "specialization"
    AVAILABILITY = "availability"

@dataclass
class ModelRecommendation:
    """Model recommendation with scoring and reasoning."""
    model_id: str
    model_info: ModelInfo
    score: float
    confidence: float
    reasoning: List[str]
    strategy: RecommendationStrategy
    performance_metrics: Optional[ModelPerformanceMetrics] = None
    compatibility_score: float = 1.0
    user_preference_score: float = 0.0

@dataclass
class FilterRequest:
    """Request for model filtering."""
    modalities: List[ModalityType] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    providers: List[str] = field(default_factory=list)
    specializations: List[ModelSpecialization] = field(default_factory=list)
    min_performance_score: float = 0.0
    max_model_size: Optional[int] = None
    require_availability: bool = True
    exclude_models: List[str] = field(default_factory=list)

@dataclass
class RecommendationRequest:
    """Request for model recommendations."""
    task_description: str
    filter_criteria: FilterRequest = field(default_factory=FilterRequest)
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    max_recommendations: int = 5
    strategy: RecommendationStrategy = RecommendationStrategy.HYBRID
    include_reasoning: bool = True

class ModelRecommendationEngine:
    """
    Intelligent model filtering and recommendation engine.
    
    This engine works alongside existing ProfileManager capabilities to provide
    enhanced model selection with discovered models while preserving existing
    routing logic and user preferences.
    """
    
    def __init__(self, model_router: ModelRouter):
        self.model_router = model_router
        
        # Caching
        self.recommendation_cache: Dict[str, List[ModelRecommendation]] = {}
        self.filter_cache: Dict[str, List[str]] = {}
        self.cache_ttl = 300  # 5 minutes
        self.last_cache_cleanup = time.time()
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Scoring weights for hybrid strategy
        self.scoring_weights = {
            "performance": 0.3,
            "capability": 0.25,
            "compatibility": 0.2,
            "user_preference": 0.15,
            "availability": 0.1
        }
        
        # Model capability mappings
        self.capability_keywords = {
            "chat": ["chat", "conversation", "dialogue", "assistant"],
            "code": ["code", "programming", "coding", "development"],
            "reasoning": ["reasoning", "logic", "analysis", "thinking"],
            "creative": ["creative", "generation", "writing", "story"],
            "summarization": ["summarization", "summary", "abstract"],
            "translation": ["translation", "multilingual", "language"],
            "embedding": ["embedding", "similarity", "search", "retrieval"],
            "vision": ["vision", "image", "visual", "sight"],
            "audio": ["audio", "speech", "sound", "voice"]
        }
        
        logger.info("Model Recommendation Engine initialized")
    
    async def filter_models(self, filter_request: FilterRequest) -> List[str]:
        """
        Filter models based on specified criteria.
        
        Args:
            filter_request: Filtering criteria
            
        Returns:
            List of model IDs that match the criteria
        """
        # Generate cache key
        cache_key = self._generate_filter_cache_key(filter_request)
        
        with self._lock:
            # Check cache
            if cache_key in self.filter_cache:
                cached_result = self.filter_cache[cache_key]
                if cached_result:
                    logger.debug(f"Returning cached filter result with {len(cached_result)} models")
                    return cached_result
            
            try:
                # Get all available models
                all_models = await self._get_available_models()
                filtered_models = []
                
                for model_id, model_info in all_models.items():
                    if await self._model_matches_filter(model_info, filter_request):
                        filtered_models.append(model_id)
                
                # Cache result
                self.filter_cache[cache_key] = filtered_models
                
                logger.info(f"Filtered {len(filtered_models)} models from {len(all_models)} total")
                return filtered_models
                
            except Exception as e:
                logger.error(f"Model filtering failed: {e}")
                return []
    
    async def recommend_models(self, request: RecommendationRequest) -> List[ModelRecommendation]:
        """
        Recommend models based on task requirements and user preferences.
        
        Args:
            request: Recommendation request
            
        Returns:
            List of model recommendations sorted by score
        """
        # Generate cache key
        cache_key = self._generate_recommendation_cache_key(request)
        
        with self._lock:
            # Check cache
            if cache_key in self.recommendation_cache:
                cached_result = self.recommendation_cache[cache_key]
                if cached_result:
                    logger.debug(f"Returning cached recommendations: {len(cached_result)} models")
                    return cached_result
            
            try:
                # Filter models first
                filtered_model_ids = await self.filter_models(request.filter_criteria)
                
                if not filtered_model_ids:
                    logger.warning("No models match the filter criteria")
                    return []
                
                # Generate recommendations
                recommendations = await self._generate_recommendations(
                    filtered_model_ids, request
                )
                
                # Sort by score
                recommendations.sort(key=lambda r: r.score, reverse=True)
                
                # Limit results
                recommendations = recommendations[:request.max_recommendations]
                
                # Cache result
                self.recommendation_cache[cache_key] = recommendations
                
                logger.info(f"Generated {len(recommendations)} model recommendations")
                return recommendations
                
            except Exception as e:
                logger.error(f"Model recommendation failed: {e}")
                return []
    
    async def _get_available_models(self) -> Dict[str, ModelInfo]:
        """Get all available models from the router."""
        available_models = {}
        
        # Get models from router connections
        for model_id, connection in self.model_router.model_connections.items():
            available_models[model_id] = connection.model_info
        
        return available_models
    
    async def _model_matches_filter(
        self, 
        model_info: ModelInfo, 
        filter_request: FilterRequest
    ) -> bool:
        """Check if a model matches the filter criteria."""
        try:
            # Check modalities
            if filter_request.modalities:
                model_modalities = {mod.type for mod in model_info.modalities}
                required_modalities = set(filter_request.modalities)
                if not required_modalities.issubset(model_modalities):
                    return False
            
            # Check capabilities
            if filter_request.capabilities:
                model_capabilities = [cap.lower() for cap in model_info.capabilities]
                for required_cap in filter_request.capabilities:
                    if not self._capability_matches(required_cap.lower(), model_capabilities):
                        return False
            
            # Check providers
            if filter_request.providers:
                # Get provider from router
                connection = self.model_router.model_connections.get(model_info.id)
                if connection and connection.provider not in filter_request.providers:
                    return False
            
            # Check specializations
            if filter_request.specializations:
                model_specializations = set(model_info.specialization)
                required_specializations = set(filter_request.specializations)
                if not required_specializations.intersection(model_specializations):
                    return False
            
            # Check performance score
            if filter_request.min_performance_score > 0:
                performance_score = await self._get_model_performance_score(model_info.id)
                if performance_score < filter_request.min_performance_score:
                    return False
            
            # Check model size
            if filter_request.max_model_size and model_info.size > filter_request.max_model_size:
                return False
            
            # Check availability
            if filter_request.require_availability:
                connection = self.model_router.model_connections.get(model_info.id)
                if not connection or not await self._is_model_available(connection):
                    return False
            
            # Check exclusions
            if model_info.id in filter_request.exclude_models:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Filter matching failed for {model_info.id}: {e}")
            return False
    
    def _capability_matches(self, required_capability: str, model_capabilities: List[str]) -> bool:
        """Check if a required capability matches model capabilities."""
        # Direct match
        if required_capability in model_capabilities:
            return True
        
        # Keyword-based matching
        keywords = self.capability_keywords.get(required_capability, [required_capability])
        
        for keyword in keywords:
            for model_cap in model_capabilities:
                if keyword in model_cap or model_cap in keyword:
                    return True
        
        return False
    
    async def _is_model_available(self, connection) -> bool:
        """Check if a model is currently available."""
        try:
            from ai_karen_engine.services.intelligent_model_router import ConnectionStatus
            return connection.status == ConnectionStatus.CONNECTED
        except Exception:
            return False
    
    async def _get_model_performance_score(self, model_id: str) -> float:
        """Get performance score for a model."""
        try:
            metrics = self.model_router.performance_metrics.get(model_id)
            if not metrics or metrics.total_requests == 0:
                return 0.5  # Neutral score for new models
            
            success_rate = metrics.successful_requests / metrics.total_requests
            availability = metrics.availability_score
            
            # Composite performance score
            return (success_rate * 0.6 + availability * 0.4)
            
        except Exception as e:
            logger.error(f"Failed to get performance score for {model_id}: {e}")
            return 0.0
    
    async def _generate_recommendations(
        self, 
        model_ids: List[str], 
        request: RecommendationRequest
    ) -> List[ModelRecommendation]:
        """Generate recommendations for filtered models."""
        recommendations = []
        
        for model_id in model_ids:
            try:
                connection = self.model_router.model_connections.get(model_id)
                if not connection:
                    continue
                
                model_info = connection.model_info
                
                # Calculate scores based on strategy
                recommendation = await self._score_model(model_info, request)
                
                if recommendation:
                    recommendations.append(recommendation)
                    
            except Exception as e:
                logger.error(f"Failed to generate recommendation for {model_id}: {e}")
        
        return recommendations
    
    async def _score_model(
        self, 
        model_info: ModelInfo, 
        request: RecommendationRequest
    ) -> Optional[ModelRecommendation]:
        """Score a model for recommendation."""
        try:
            reasoning = []
            
            # Calculate component scores
            performance_score = await self._calculate_performance_score(model_info, reasoning)
            capability_score = await self._calculate_capability_score(
                model_info, request.task_description, reasoning
            )
            compatibility_score = await self._calculate_compatibility_score(
                model_info, request.context, reasoning
            )
            user_preference_score = await self._calculate_user_preference_score(
                model_info, request.user_preferences, reasoning
            )
            availability_score = await self._calculate_availability_score(model_info, reasoning)
            
            # Calculate composite score based on strategy
            if request.strategy == RecommendationStrategy.PERFORMANCE_BASED:
                final_score = performance_score
            elif request.strategy == RecommendationStrategy.CAPABILITY_BASED:
                final_score = capability_score
            elif request.strategy == RecommendationStrategy.COMPATIBILITY_BASED:
                final_score = compatibility_score
            elif request.strategy == RecommendationStrategy.USER_PREFERENCE:
                final_score = user_preference_score
            else:  # HYBRID
                final_score = (
                    performance_score * self.scoring_weights["performance"] +
                    capability_score * self.scoring_weights["capability"] +
                    compatibility_score * self.scoring_weights["compatibility"] +
                    user_preference_score * self.scoring_weights["user_preference"] +
                    availability_score * self.scoring_weights["availability"]
                )
            
            # Calculate confidence based on available data
            confidence = self._calculate_confidence(model_info)
            
            # Get performance metrics
            performance_metrics = self.model_router.performance_metrics.get(model_info.id)
            
            return ModelRecommendation(
                model_id=model_info.id,
                model_info=model_info,
                score=final_score,
                confidence=confidence,
                reasoning=reasoning if request.include_reasoning else [],
                strategy=request.strategy,
                performance_metrics=performance_metrics,
                compatibility_score=compatibility_score,
                user_preference_score=user_preference_score
            )
            
        except Exception as e:
            logger.error(f"Failed to score model {model_info.id}: {e}")
            return None
    
    async def _calculate_performance_score(
        self, 
        model_info: ModelInfo, 
        reasoning: List[str]
    ) -> float:
        """Calculate performance-based score."""
        try:
            performance_score = await self._get_model_performance_score(model_info.id)
            
            if performance_score > 0.8:
                reasoning.append(f"High performance score: {performance_score:.2f}")
            elif performance_score > 0.6:
                reasoning.append(f"Good performance score: {performance_score:.2f}")
            elif performance_score > 0:
                reasoning.append(f"Limited performance data: {performance_score:.2f}")
            else:
                reasoning.append("No performance data available")
            
            return performance_score
            
        except Exception as e:
            logger.error(f"Performance score calculation failed: {e}")
            return 0.0
    
    async def _calculate_capability_score(
        self, 
        model_info: ModelInfo, 
        task_description: str, 
        reasoning: List[str]
    ) -> float:
        """Calculate capability-based score."""
        try:
            task_lower = task_description.lower()
            model_capabilities = [cap.lower() for cap in model_info.capabilities]
            
            # Analyze task for required capabilities
            required_capabilities = []
            for capability, keywords in self.capability_keywords.items():
                if any(keyword in task_lower for keyword in keywords):
                    required_capabilities.append(capability)
            
            if not required_capabilities:
                # Generic task, check for general capabilities
                required_capabilities = ["chat"]
            
            # Calculate match score
            matches = 0
            for req_cap in required_capabilities:
                if self._capability_matches(req_cap, model_capabilities):
                    matches += 1
                    reasoning.append(f"Supports {req_cap} capability")
            
            capability_score = matches / len(required_capabilities) if required_capabilities else 0.5
            
            # Bonus for specialized models
            if model_info.specialization:
                for spec in model_info.specialization:
                    if spec.value.lower() in task_lower:
                        capability_score = min(1.0, capability_score + 0.2)
                        reasoning.append(f"Specialized for {spec.value}")
            
            return capability_score
            
        except Exception as e:
            logger.error(f"Capability score calculation failed: {e}")
            return 0.0
    
    async def _calculate_compatibility_score(
        self, 
        model_info: ModelInfo, 
        context: Dict[str, Any], 
        reasoning: List[str]
    ) -> float:
        """Calculate compatibility-based score."""
        try:
            compatibility_score = 1.0
            
            # Check resource requirements
            if context.get("available_memory"):
                available_memory = context["available_memory"]
                required_memory = model_info.requirements.recommended_ram_gb
                
                if required_memory > available_memory:
                    compatibility_score *= 0.5
                    reasoning.append(f"High memory requirement: {required_memory}GB")
                else:
                    reasoning.append(f"Compatible memory requirement: {required_memory}GB")
            
            # Check GPU requirements
            if model_info.requirements.gpu_required and not context.get("gpu_available", True):
                compatibility_score *= 0.3
                reasoning.append("Requires GPU but none available")
            
            # Check platform compatibility
            current_platform = context.get("platform", "linux")
            if (model_info.requirements.supported_platforms and 
                current_platform not in model_info.requirements.supported_platforms):
                compatibility_score *= 0.7
                reasoning.append(f"Limited platform support for {current_platform}")
            
            return compatibility_score
            
        except Exception as e:
            logger.error(f"Compatibility score calculation failed: {e}")
            return 1.0
    
    async def _calculate_user_preference_score(
        self, 
        model_info: ModelInfo, 
        user_preferences: Dict[str, Any], 
        reasoning: List[str]
    ) -> float:
        """Calculate user preference-based score."""
        try:
            preference_score = 0.0
            
            # Check preferred providers
            preferred_providers = user_preferences.get("preferred_providers", [])
            if preferred_providers:
                connection = self.model_router.model_connections.get(model_info.id)
                if connection and connection.provider in preferred_providers:
                    preference_score += 0.3
                    reasoning.append(f"Matches preferred provider: {connection.provider}")
            
            # Check preferred model types
            preferred_types = user_preferences.get("preferred_model_types", [])
            if preferred_types and model_info.type.value in preferred_types:
                preference_score += 0.2
                reasoning.append(f"Matches preferred type: {model_info.type.value}")
            
            # Check preferred specializations
            preferred_specializations = user_preferences.get("preferred_specializations", [])
            if preferred_specializations:
                for spec in model_info.specialization:
                    if spec.value in preferred_specializations:
                        preference_score += 0.2
                        reasoning.append(f"Matches preferred specialization: {spec.value}")
                        break
            
            # Check size preferences
            max_preferred_size = user_preferences.get("max_model_size")
            if max_preferred_size and model_info.size <= max_preferred_size:
                preference_score += 0.1
                reasoning.append("Within preferred size limit")
            
            # Check performance preferences
            min_performance = user_preferences.get("min_performance_score", 0.0)
            if min_performance > 0:
                actual_performance = await self._get_model_performance_score(model_info.id)
                if actual_performance >= min_performance:
                    preference_score += 0.2
                    reasoning.append("Meets performance requirements")
            
            return min(1.0, preference_score)
            
        except Exception as e:
            logger.error(f"User preference score calculation failed: {e}")
            return 0.0
    
    async def _calculate_availability_score(
        self, 
        model_info: ModelInfo, 
        reasoning: List[str]
    ) -> float:
        """Calculate availability-based score."""
        try:
            connection = self.model_router.model_connections.get(model_info.id)
            if not connection:
                reasoning.append("Model not connected")
                return 0.0
            
            if await self._is_model_available(connection):
                reasoning.append("Model is available")
                return 1.0
            else:
                reasoning.append("Model is not currently available")
                return 0.2
                
        except Exception as e:
            logger.error(f"Availability score calculation failed: {e}")
            return 0.0
    
    def _calculate_confidence(self, model_info: ModelInfo) -> float:
        """Calculate confidence in the recommendation."""
        confidence = 0.5  # Base confidence
        
        # Increase confidence based on available data
        if model_info.metadata.description:
            confidence += 0.1
        
        if model_info.capabilities:
            confidence += 0.1
        
        if model_info.specialization:
            confidence += 0.1
        
        # Check if we have performance data
        metrics = self.model_router.performance_metrics.get(model_info.id)
        if metrics and metrics.total_requests > 10:
            confidence += 0.2
        elif metrics and metrics.total_requests > 0:
            confidence += 0.1
        
        return min(1.0, confidence)
    
    def _generate_filter_cache_key(self, filter_request: FilterRequest) -> str:
        """Generate cache key for filter request."""
        key_parts = [
            f"mod:{','.join(m.value for m in filter_request.modalities)}",
            f"cap:{','.join(filter_request.capabilities)}",
            f"prov:{','.join(filter_request.providers)}",
            f"spec:{','.join(s.value for s in filter_request.specializations)}",
            f"perf:{filter_request.min_performance_score}",
            f"size:{filter_request.max_model_size}",
            f"avail:{filter_request.require_availability}",
            f"excl:{','.join(filter_request.exclude_models)}"
        ]
        return "|".join(key_parts)
    
    def _generate_recommendation_cache_key(self, request: RecommendationRequest) -> str:
        """Generate cache key for recommendation request."""
        filter_key = self._generate_filter_cache_key(request.filter_criteria)
        
        key_parts = [
            f"task:{hash(request.task_description)}",
            f"filter:{hash(filter_key)}",
            f"prefs:{hash(str(sorted(request.user_preferences.items())))}",
            f"ctx:{hash(str(sorted(request.context.items())))}",
            f"max:{request.max_recommendations}",
            f"strat:{request.strategy.value}"
        ]
        return "|".join(key_parts)
    
    async def get_model_compatibility_matrix(self) -> Dict[str, Dict[str, float]]:
        """Get compatibility matrix between models and capabilities."""
        compatibility_matrix = {}
        
        available_models = await self._get_available_models()
        
        for model_id, model_info in available_models.items():
            compatibility_matrix[model_id] = {}
            
            for capability in self.capability_keywords.keys():
                score = 0.0
                model_capabilities = [cap.lower() for cap in model_info.capabilities]
                
                if self._capability_matches(capability, model_capabilities):
                    score = 1.0
                    
                    # Bonus for specialization
                    for spec in model_info.specialization:
                        if spec.value.lower() == capability:
                            score = min(1.0, score + 0.2)
                
                compatibility_matrix[model_id][capability] = score
        
        return compatibility_matrix
    
    async def cleanup_cache(self):
        """Clean up expired cache entries."""
        current_time = time.time()
        
        if current_time - self.last_cache_cleanup < self.cache_ttl:
            return
        
        with self._lock:
            # Clear all caches (simple approach)
            self.recommendation_cache.clear()
            self.filter_cache.clear()
            self.last_cache_cleanup = current_time
            
            logger.debug("Cleaned up recommendation cache")
    
    async def get_recommendation_statistics(self) -> Dict[str, Any]:
        """Get recommendation engine statistics."""
        stats = {
            "cache_size": {
                "recommendations": len(self.recommendation_cache),
                "filters": len(self.filter_cache)
            },
            "scoring_weights": self.scoring_weights,
            "capability_mappings": len(self.capability_keywords),
            "last_cache_cleanup": self.last_cache_cleanup
        }
        
        return stats

# Global instance
_recommendation_engine: Optional[ModelRecommendationEngine] = None
_engine_lock = threading.RLock()

def get_recommendation_engine(model_router: Optional[ModelRouter] = None) -> ModelRecommendationEngine:
    """Get the global recommendation engine instance."""
    global _recommendation_engine
    if _recommendation_engine is None:
        with _engine_lock:
            if _recommendation_engine is None:
                if model_router is None:
                    from ai_karen_engine.services.intelligent_model_router import get_model_router
                    model_router = get_model_router()
                _recommendation_engine = ModelRecommendationEngine(model_router)
    return _recommendation_engine
