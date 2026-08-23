"""
Intelligent Model Router API Routes

Provides REST API endpoints for the intelligent model router and wiring system.
Exposes model discovery, routing, and performance tracking capabilities.

Requirements implemented: 7.3, 7.4, 7.5, 8.4
"""

import asyncio
import logging
from enum import Enum
from typing import Any, Dict, List, Optional
from pathlib import Path

from ai_karen_engine.core.errors.handlers import handle_api_exception
from ai_karen_engine.services.intelligent_model_router import (
    get_model_router, initialize_model_router, RoutingStrategy
)
from ai_karen_engine.core.model_runtime.management.model_connection_manager import get_connection_manager
from ai_karen_engine.core.model_runtime.recommendation.model_recommendation_engine import (
    get_recommendation_engine, RecommendationRequest, FilterRequest,
    RecommendationStrategy, FilterCriteria
)
from ai_karen_engine.services.orchestration.reasoning_preservation_layer import (
    get_reasoning_preservation_layer, ReasoningComponent
)
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, Depends, HTTPException = import_fastapi(
    "APIRouter", "Depends", "HTTPException"
)
BaseModel, Field = import_pydantic("BaseModel", "Field")

logger = logging.getLogger("kari.intelligent_model_routes")

router = APIRouter(tags=["intelligent-models"])


class ModalityType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    MULTIMODAL = "multimodal"

# Request/Response Models
class ModelConnectionRequest(BaseModel):
    """Request to connect to a model."""
    model_id: str
    session_id: Optional[str] = None
    preserve_reasoning: bool = True

class ModelConnectionResponse(BaseModel):
    """Response for model connection."""
    success: bool
    model_id: str
    provider: str
    status: str
    connection_time: Optional[float] = None
    error_message: Optional[str] = None

class ModelRoutingRequest(BaseModel):
    """Request for model routing."""
    message: str
    task_type: str = "chat"
    modalities: List[str] = Field(default_factory=list)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    preferred_model: Optional[str] = None
    session_id: Optional[str] = None

class ModelRoutingResponse(BaseModel):
    """Response for model routing."""
    success: bool
    model_id: str
    provider: str
    routing_strategy: str
    confidence: float
    reasoning: str
    fallback_options: List[str] = Field(default_factory=list)
    estimated_performance: Optional[Dict[str, Any]] = None

class ModelRecommendationRequest(BaseModel):
    """Request for model recommendations."""
    task_description: str
    modalities: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    providers: List[str] = Field(default_factory=list)
    max_recommendations: int = 5
    strategy: str = "hybrid"
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)

class ModelRecommendationResponse(BaseModel):
    """Response for model recommendations."""
    recommendations: List[Dict[str, Any]]
    total_models_evaluated: int
    strategy_used: str

class ModelFilterRequest(BaseModel):
    """Request for model filtering."""
    modalities: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    providers: List[str] = Field(default_factory=list)
    min_performance_score: float = 0.0
    max_model_size: Optional[int] = None
    require_availability: bool = True
    exclude_models: List[str] = Field(default_factory=list)

class ModelFilterResponse(BaseModel):
    """Response for model filtering."""
    filtered_models: List[str]
    total_available: int
    filter_criteria_applied: Dict[str, Any]

class ModelSwitchRequest(BaseModel):
    """Request for model switching."""
    from_model_id: str
    to_model_id: str
    session_id: Optional[str] = None
    preserve_reasoning: bool = True

class ModelSwitchResponse(BaseModel):
    """Response for model switching."""
    success: bool
    from_model_id: str
    to_model_id: str
    switch_time: float
    reasoning_preserved: bool
    error_message: Optional[str] = None

# Dependency functions
async def get_router():
    """Get the model router instance."""
    return get_model_router()

async def get_connection_mgr():
    """Get the connection manager instance."""
    return get_connection_manager()

async def get_recommendation_eng():
    """Get the recommendation engine instance."""
    return get_recommendation_engine()

# API Routes

@router.post("/initialize", response_model=Dict[str, Any])
async def initialize_intelligent_routing():
    """
    Initialize the intelligent model routing system.
    
    This endpoint initializes model discovery, connection management,
    and recommendation systems.
    """
    try:
        logger.info("Initializing intelligent model routing system")
        
        # Initialize model router
        model_router = await initialize_model_router()
        
        # Get statistics
        stats = await model_router.get_routing_statistics()
        
        return {
            "success": True,
            "message": "Intelligent model routing system initialized",
            "statistics": stats
        }
        
    except Exception as ex:
        logger.error(f"Failed to initialize intelligent routing: {ex}")
        raise handle_api_exception(ex, "Failed to initialize intelligent routing system")

@router.post("/connect", response_model=ModelConnectionResponse)
async def connect_to_model(
    request: ModelConnectionRequest,
    router_instance=Depends(get_router),
    connection_manager=Depends(get_connection_mgr)
):
    """
    Establish a verified connection to a specific model.
    
    This endpoint wires a connection to the specified model and verifies
    that routing works correctly.
    """
    try:
        logger.info(f"Connecting to model: {request.model_id}")
        
        # Get connection through connection manager
        lease = await connection_manager.get_connection(
            model_id=request.model_id,
            session_id=request.session_id,
            preserve_reasoning=request.preserve_reasoning
        )
        
        if not lease:
            return ModelConnectionResponse(
                success=False,
                model_id=request.model_id,
                provider="unknown",
                status="failed",
                error_message="Failed to establish connection"
            )
        
        connection = lease.connection
        
        # Verify routing
        routing_verified = await router_instance.verify_model_routing(request.model_id)
        
        # Return connection (will be managed by connection manager)
        await connection_manager.return_connection(lease)
        
        return ModelConnectionResponse(
            success=True,
            model_id=connection.model_id,
            provider=connection.provider,
            status=connection.status.value,
            connection_time=connection.connection_time,
            error_message=None if routing_verified else "Routing verification failed"
        )
        
    except Exception as ex:
        logger.error(f"Failed to connect to model {request.model_id}: {ex}")
        raise handle_api_exception(ex, f"Failed to connect to model {request.model_id}")

@router.post("/route", response_model=ModelRoutingResponse)
async def route_request(
    request: ModelRoutingRequest,
    router_instance=Depends(get_router)
):
    """
    Route a request to the optimal model based on task requirements.
    
    This endpoint uses intelligent routing to select the best available
    model for the given task while preserving existing routing logic.
    """
    try:
        logger.info(f"Routing request for task: {request.task_type}")
        
        # Convert modalities
        modalities = []
        for mod_str in request.modalities:
            try:
                modalities.append(ModalityType(mod_str.lower()))
            except ValueError:
                logger.warning(f"Unknown modality: {mod_str}")
        
        # Select optimal model
        decision = await router_instance.select_optimal_model_for_task(
            task_type=request.task_type,
            modalities=modalities,
            user_preferences=request.user_preferences
        )
        
        if not decision:
            raise HTTPException(
                status_code=404,
                detail="No suitable model found for the request"
            )
        
        return ModelRoutingResponse(
            success=True,
            model_id=decision.model_id,
            provider=decision.provider,
            routing_strategy=decision.routing_strategy.value,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            fallback_options=decision.fallback_options,
            estimated_performance=decision.estimated_performance
        )
        
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Failed to route request: {ex}")
        raise handle_api_exception(ex, "Failed to route request")

@router.post("/recommend", response_model=ModelRecommendationResponse)
async def recommend_models(
    request: ModelRecommendationRequest,
    recommendation_engine=Depends(get_recommendation_eng)
):
    """
    Get model recommendations based on task requirements and preferences.
    
    This endpoint provides intelligent model recommendations with scoring
    and reasoning for each suggestion.
    """
    try:
        logger.info(f"Getting model recommendations for: {request.task_description[:50]}...")
        
        # Convert strategy
        try:
            strategy = RecommendationStrategy(request.strategy.lower())
        except ValueError:
            strategy = RecommendationStrategy.HYBRID
        
        # Convert modalities
        modalities = []
        for mod_str in request.modalities:
            try:
                modalities.append(ModalityType(mod_str.lower()))
            except ValueError:
                continue
        
        # Create recommendation request
        rec_request = RecommendationRequest(
            task_description=request.task_description,
            filter_criteria=FilterRequest(
                modalities=modalities,
                capabilities=request.capabilities,
                providers=request.providers
            ),
            user_preferences=request.user_preferences,
            context=request.context,
            max_recommendations=request.max_recommendations,
            strategy=strategy
        )
        
        # Get recommendations
        recommendations = await recommendation_engine.recommend_models(rec_request)
        
        # Format response
        formatted_recommendations = []
        for rec in recommendations:
            formatted_recommendations.append({
                "model_id": rec.model_id,
                "model_name": rec.model_info.display_name,
                "provider": rec.model_info.type.value,
                "score": rec.score,
                "confidence": rec.confidence,
                "reasoning": rec.reasoning,
                "strategy": rec.strategy.value,
                "capabilities": rec.model_info.capabilities,
                "modalities": [mod.type.value for mod in rec.model_info.modalities],
                "performance_metrics": {
                    "total_requests": rec.performance_metrics.total_requests if rec.performance_metrics else 0,
                    "success_rate": (rec.performance_metrics.successful_requests / max(rec.performance_metrics.total_requests, 1)) if rec.performance_metrics else 0,
                    "average_response_time": rec.performance_metrics.average_response_time if rec.performance_metrics else 0
                }
            })
        
        return ModelRecommendationResponse(
            recommendations=formatted_recommendations,
            total_models_evaluated=len(recommendations),
            strategy_used=strategy.value
        )
        
    except Exception as ex:
        logger.error(f"Failed to get model recommendations: {ex}")
        raise handle_api_exception(ex, "Failed to get model recommendations")

@router.post("/filter", response_model=ModelFilterResponse)
async def filter_models(
    request: ModelFilterRequest,
    recommendation_engine=Depends(get_recommendation_eng)
):
    """
    Filter models based on specified criteria.
    
    This endpoint filters available models based on modalities, capabilities,
    providers, and other criteria.
    """
    try:
        logger.info("Filtering models based on criteria")
        
        # Convert modalities
        modalities = []
        for mod_str in request.modalities:
            try:
                modalities.append(ModalityType(mod_str.lower()))
            except ValueError:
                continue
        
        # Create filter request
        filter_request = FilterRequest(
            modalities=modalities,
            capabilities=request.capabilities,
            providers=request.providers,
            min_performance_score=request.min_performance_score,
            max_model_size=request.max_model_size,
            require_availability=request.require_availability,
            exclude_models=request.exclude_models
        )
        
        # Filter models
        filtered_models = await recommendation_engine.filter_models(filter_request)
        
        # Get total available models for comparison
        all_models = await recommendation_engine._get_available_models()
        
        return ModelFilterResponse(
            filtered_models=filtered_models,
            total_available=len(all_models),
            filter_criteria_applied={
                "modalities": request.modalities,
                "capabilities": request.capabilities,
                "providers": request.providers,
                "min_performance_score": request.min_performance_score,
                "max_model_size": request.max_model_size,
                "require_availability": request.require_availability,
                "exclude_models": request.exclude_models
            }
        )
        
    except Exception as ex:
        logger.error(f"Failed to filter models: {ex}")
        raise handle_api_exception(ex, "Failed to filter models")

@router.post("/switch", response_model=ModelSwitchResponse)
async def switch_model(
    request: ModelSwitchRequest,
    connection_manager=Depends(get_connection_mgr)
):
    """
    Switch from one model to another while preserving reasoning flows.
    
    This endpoint handles graceful model switching with proper connection
    lifecycle management and reasoning preservation.
    """
    try:
        logger.info(f"Switching from {request.from_model_id} to {request.to_model_id}")
        
        start_time = time.time()
        
        # Perform model switch
        success = await connection_manager.switch_model(
            from_model_id=request.from_model_id,
            to_model_id=request.to_model_id,
            session_id=request.session_id,
            preserve_reasoning=request.preserve_reasoning
        )
        
        switch_time = time.time() - start_time
        
        return ModelSwitchResponse(
            success=success,
            from_model_id=request.from_model_id,
            to_model_id=request.to_model_id,
            switch_time=switch_time,
            reasoning_preserved=request.preserve_reasoning and success,
            error_message=None if success else "Model switch failed"
        )
        
    except Exception as ex:
        logger.error(f"Failed to switch models: {ex}")
        raise handle_api_exception(ex, "Failed to switch models")

@router.get("/active", response_model=Dict[str, Any])
async def get_active_models(router_instance=Depends(get_router)):
    """
    Get information about currently active models.
    
    Returns details about connected models, their performance metrics,
    and current status.
    """
    try:
        active_models = await router_instance.get_active_model_info()
        return {
            "success": True,
            "active_models": active_models,
            "total_active": len(active_models)
        }
        
    except Exception as ex:
        logger.error(f"Failed to get active models: {ex}")
        raise handle_api_exception(ex, "Failed to get active models")

@router.get("/statistics", response_model=Dict[str, Any])
async def get_routing_statistics(
    router_instance=Depends(get_router),
    connection_manager=Depends(get_connection_mgr),
    recommendation_engine=Depends(get_recommendation_eng)
):
    """
    Get comprehensive routing and performance statistics.
    
    Returns statistics about model routing, connections, recommendations,
    and overall system performance.
    """
    try:
        # Get statistics from all components
        routing_stats = await router_instance.get_routing_statistics()
        connection_stats = await connection_manager.get_connection_statistics()
        recommendation_stats = await recommendation_engine.get_recommendation_statistics()
        
        # Get reasoning preservation statistics
        preservation_layer = get_reasoning_preservation_layer()
        reasoning_stats = preservation_layer.get_reasoning_statistics()
        
        return {
            "success": True,
            "routing": routing_stats,
            "connections": connection_stats,
            "recommendations": recommendation_stats,
            "reasoning_preservation": reasoning_stats,
            "timestamp": time.time()
        }
        
    except Exception as ex:
        logger.error(f"Failed to get routing statistics: {ex}")
        raise handle_api_exception(ex, "Failed to get routing statistics")

@router.get("/health", response_model=Dict[str, Any])
async def get_system_health(
    router_instance=Depends(get_router),
    connection_manager=Depends(get_connection_mgr)
):
    """
    Get health status of the intelligent routing system.
    
    Returns health information about all components and their status.
    """
    try:
        # Check router health
        router_stats = await router_instance.get_routing_statistics()
        router_healthy = router_stats["connected_models"] > 0
        
        # Check connection manager health
        connection_stats = await connection_manager.get_connection_statistics()
        connections_healthy = connection_stats["total_pools"] >= 0
        
        # Overall health
        overall_healthy = router_healthy and connections_healthy
        
        return {
            "success": True,
            "overall_health": "healthy" if overall_healthy else "degraded",
            "components": {
                "model_router": {
                    "status": "healthy" if router_healthy else "degraded",
                    "connected_models": router_stats["connected_models"],
                    "total_models": router_stats["total_models"]
                },
                "connection_manager": {
                    "status": "healthy" if connections_healthy else "degraded",
                    "active_pools": connection_stats["total_pools"],
                    "active_leases": connection_stats["active_leases"]
                }
            },
            "timestamp": time.time()
        }
        
    except Exception as ex:
        logger.error(f"Failed to get system health: {ex}")
        raise handle_api_exception(ex, "Failed to get system health")

@router.post("/configure", response_model=Dict[str, Any])
async def configure_routing(
    configuration: Dict[str, Any],
    router_instance=Depends(get_router)
):
    """
    Configure routing strategy and parameters.
    
    Allows runtime configuration of routing behavior, strategies,
    and preservation settings.
    """
    try:
        logger.info(f"Configuring routing with: {configuration}")
        
        # Configure routing strategy
        if "routing_strategy" in configuration:
            try:
                strategy = RoutingStrategy(configuration["routing_strategy"])
                router_instance.routing_strategy = strategy
            except ValueError:
                logger.warning(f"Invalid routing strategy: {configuration['routing_strategy']}")
        
        # Configure preservation settings
        if "preservation" in configuration:
            preservation_layer = get_reasoning_preservation_layer()
            preservation_layer.configure_preservation(**configuration["preservation"])
        
        # Configure scoring weights
        if "scoring_weights" in configuration:
            recommendation_engine = get_recommendation_engine()
            recommendation_engine.scoring_weights.update(configuration["scoring_weights"])
        
        return {
            "success": True,
            "message": "Routing configuration updated",
            "applied_configuration": configuration
        }
        
    except Exception as ex:
        logger.error(f"Failed to configure routing: {ex}")
        raise handle_api_exception(ex, "Failed to configure routing")

@router.get("/compatibility-matrix", response_model=Dict[str, Any])
async def get_compatibility_matrix(recommendation_engine=Depends(get_recommendation_eng)):
    """
    Get model compatibility matrix for different capabilities.
    
    Returns a matrix showing which models support which capabilities
    and their compatibility scores.
    """
    try:
        matrix = await recommendation_engine.get_model_compatibility_matrix()
        
        return {
            "success": True,
            "compatibility_matrix": matrix,
            "total_models": len(matrix),
            "capabilities": list(recommendation_engine.capability_keywords.keys())
        }
        
    except Exception as ex:
        logger.error(f"Failed to get compatibility matrix: {ex}")
        raise handle_api_exception(ex, "Failed to get compatibility matrix")

# Add import for time
import time

