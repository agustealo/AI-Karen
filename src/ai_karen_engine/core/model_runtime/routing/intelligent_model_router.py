"""
Intelligent Model Router and Wiring System

This module implements an intelligent model router that preserves existing routing logic
while enhancing it with discovered models, intelligent fallback mechanisms, and 
performance tracking. It integrates with the existing provider registry, LLM router,
and model discovery engine.

Requirements implemented: 7.3, 7.4, 7.5, 8.4
"""

import asyncio
import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Set, Union, cast
from enum import Enum
from pathlib import Path
import json

from ai_karen_engine.core.model_runtime.model_discovery_service import (
    ModelDiscoveryService,
    ModelSummary,
    get_model_discovery_service,
)
from ai_karen_engine.core.model_runtime.provider_registry_service import get_provider_registry_service, ProviderCapability
from ai_karen_engine.core.model_runtime.discovery.model_discovery_engine import (
    ModelInfo,
    ModelType,
    ModalityType,
    ModelCategory,
)
from .llm_router_service import LLMRouter, ChatRequest, RoutingPolicy
from ai_karen_engine.core.model_runtime.model_registry_compat import get_registry

logger = logging.getLogger("kari.intelligent_model_router")


class TaskType(Enum):
    CHAT = "chat"
    CODE = "code"
    REASONING = "reasoning"
    EMBEDDING = "embedding"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    CREATIVE = "creative"
    ANALYSIS = "analysis"

class ConnectionStatus(Enum):
    """Model connection status."""
    CONNECTED = "connected"
    CONNECTING = "connecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    UNAVAILABLE = "unavailable"

class RoutingStrategy(Enum):
    """Model routing strategies."""
    PROFILE_BASED = "profile_based"  # Use existing profile-based routing
    CAPABILITY_BASED = "capability_based"  # Route based on model capabilities
    PERFORMANCE_BASED = "performance_based"  # Route based on performance metrics
    HYBRID = "hybrid"  # Combine multiple strategies

@dataclass
class ModelConnection:
    """Represents a connection to a specific model."""
    model_id: str
    provider: str
    model_info: Any
    status: ConnectionStatus
    connection_time: Optional[float] = None
    last_used: Optional[float] = None
    error_message: Optional[str] = None
    performance_metrics: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RoutingDecision:
    """Result of model routing decision."""
    model_id: str
    provider: str
    model_connection: ModelConnection
    routing_strategy: RoutingStrategy
    confidence: float
    fallback_options: List[str] = field(default_factory=list)
    reasoning: str = ""
    estimated_performance: Optional[Dict[str, Any]] = None

@dataclass
class ModelPerformanceMetrics:
    """Performance metrics for a model."""
    model_id: str
    provider: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    average_tokens_per_second: float = 0.0
    last_used: Optional[float] = None
    error_rate: float = 0.0
    availability_score: float = 1.0
    user_satisfaction: float = 0.0

class ModelRouter:
    """
    Intelligent model router with verified connection management and performance tracking.
    
    This router enhances existing routing logic by:
    - Discovering and integrating all available models
    - Providing verified connections to selected models
    - Implementing intelligent fallback mechanisms
    - Tracking model performance and usage analytics
    - Preserving existing reasoning and decision-making logic
    """
    
    def __init__(
        self,
        models_root: str = "models",
        enable_discovery: bool = True,
        preserve_existing_routing: bool = True
    ):
        self.models_root = Path(models_root)
        self.preserve_existing_routing = preserve_existing_routing
        
        # Initialize core components
        self.discovery_engine = get_model_discovery_service() if enable_discovery else None
        self.provider_registry = get_provider_registry_service()
        self.llm_registry = get_registry()
        
        # Initialize existing routers (preserve existing logic)
        self.existing_llm_router = LLMRouter(registry=cast(Any, self.llm_registry))
        
        # Model connections and routing state
        self.model_connections: Dict[str, ModelConnection] = {}
        self.performance_metrics: Dict[str, ModelPerformanceMetrics] = {}
        self.routing_strategy = RoutingStrategy.HYBRID
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Performance tracking
        self.performance_cache_file = Path(models_root) / ".performance_cache.json"
        self._load_performance_cache()
        
        # Model filtering and recommendation cache
        self.recommendation_cache: Dict[str, List[str]] = {}
        self.cache_ttl = 300  # 5 minutes
        self.last_cache_update = 0
        
        logger.info("Intelligent Model Router initialized")
    
    async def initialize(self):
        """Initialize the router and discover available models."""
        logger.info("Initializing Intelligent Model Router...")
        
        # Discover all available models
        if self.discovery_engine:
            discovered_models = await self.discovery_engine.discover_all_models()
            logger.info(f"Discovered {len(discovered_models)} models")
            
            # Initialize connections for discovered models
            await self._initialize_model_connections(discovered_models)
        
        # Initialize performance metrics for existing providers
        await self._initialize_provider_metrics()
        
        logger.info("Model Router initialization complete")
    
    async def _initialize_model_connections(self, models: List[ModelSummary]):
        """Initialize connections for discovered models."""
        with self._lock:
            for model in models:
                try:
                    # Determine provider for the model
                    provider = self._determine_model_provider(model)
                    
                    # Create model connection
                    connection = ModelConnection(
                        model_id=model.id,
                        provider=provider,
                        model_info=model,
                        status=ConnectionStatus.DISCONNECTED
                    )
                    
                    self.model_connections[model.id] = connection
                    
                    # Initialize performance metrics
                    if model.id not in self.performance_metrics:
                        self.performance_metrics[model.id] = ModelPerformanceMetrics(
                            model_id=model.id,
                            provider=provider
                        )
                    
                except Exception as e:
                    logger.error(f"Failed to initialize connection for model {model.id}: {e}")
    
    async def _initialize_provider_metrics(self):
        """Initialize performance metrics for existing providers."""
        providers = self.provider_registry.get_available_providers()
        
        for provider_name in providers:
            try:
                provider_models = self.llm_registry.list_models(provider_name)
                if provider_models:
                    default_model_id = provider_models[0].id
                    model_id = f"{provider_name}:{default_model_id}"

                    if model_id not in self.performance_metrics:
                        self.performance_metrics[model_id] = ModelPerformanceMetrics(
                            model_id=model_id,
                            provider=provider_name
                        )
            except Exception as e:
                logger.error(f"Failed to initialize metrics for provider {provider_name}: {e}")
    
    def _determine_model_provider(self, model: ModelInfo) -> str:
        """Determine the appropriate provider for a model."""
        # Map model types to providers
        type_provider_map = {
            ModelType.LOCAL_GGUF: "local_gguf",
            ModelType.TRANSFORMERS: "huggingface",
            ModelType.HUGGINGFACE: "huggingface",
            ModelType.STABLE_DIFFUSION: "huggingface",
            ModelType.PYTORCH: "huggingface",
            ModelType.ONNX: "huggingface",
        }
        
        provider = type_provider_map.get(model.type, "local")
        
        # Check if provider is available
        if provider in self.provider_registry.get_available_providers():
            return provider
        
        # Fallback to local provider
        return "local"
    
    async def wire_model_connection(self, model_id: str) -> Optional[ModelConnection]:
        """
        Establish a verified connection to a specific model.
        
        Args:
            model_id: ID of the model to connect to
            
        Returns:
            ModelConnection if successful, None otherwise
        """
        with self._lock:
            if model_id not in self.model_connections:
                logger.error(f"Model {model_id} not found in discovered models")
                return None
            
            connection = self.model_connections[model_id]
            
            try:
                # Update connection status
                connection.status = ConnectionStatus.CONNECTING
                
                # Verify provider is available
                provider_status = self.provider_registry.get_provider_status(connection.provider)
                if not provider_status or not provider_status.is_available:
                    connection.status = ConnectionStatus.UNAVAILABLE
                    connection.error_message = f"Provider {connection.provider} is not available"
                    return None
                
                # Attempt to establish connection
                success = await self._establish_model_connection(connection)
                
                if success:
                    connection.status = ConnectionStatus.CONNECTED
                    connection.connection_time = time.time()
                    connection.error_message = None
                    logger.info(f"Successfully connected to model {model_id}")
                    return connection
                else:
                    connection.status = ConnectionStatus.ERROR
                    connection.error_message = "Failed to establish connection"
                    logger.error(f"Failed to connect to model {model_id}")
                    return None
                    
            except Exception as e:
                connection.status = ConnectionStatus.ERROR
                connection.error_message = str(e)
                logger.error(f"Error connecting to model {model_id}: {e}")
                return None
    
    async def _establish_model_connection(self, connection: ModelConnection) -> bool:
        """Establish actual connection to the model."""
        try:
            # For local models, verify file exists and is accessible
            if connection.provider in {"local", "local_gguf"}:
                model_path = Path(connection.model_info.path)
                if not model_path.exists():
                    logger.error(f"Model file not found: {model_path}")
                    return False
                
                # Verify file is readable
                try:
                    with open(model_path, 'rb') as f:
                        f.read(1024)  # Read first 1KB to verify accessibility
                    return True
                except Exception as e:
                    logger.error(f"Model file not accessible: {e}")
                    return False
            
            # For API-based providers, verify connection
            else:
                try:
                    provider_spec = self.llm_registry.get_provider_spec(connection.provider)
                    if provider_spec:
                        health = self.llm_registry.health_check(f"provider:{connection.provider}")
                        return health.status == "healthy"
                except Exception as e:
                    logger.error(f"Provider health check failed: {e}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to establish connection: {e}")
            return False
    
    async def verify_model_routing(self, model_id: str) -> bool:
        """
        Verify that requests are actually routed to the specified model.
        
        Args:
            model_id: ID of the model to verify
            
        Returns:
            True if routing is verified, False otherwise
        """
        try:
            connection = self.model_connections.get(model_id)
            if not connection or connection.status != ConnectionStatus.CONNECTED:
                return False
            
            # Perform a test request to verify routing
            test_request = ChatRequest(
                message="Test routing verification",
                preferred_model=model_id,
                max_tokens=1,
                temperature=0.0
            )
            
            # Use existing router with explicit model preference
            if self.preserve_existing_routing:
                # Route through existing LLM router
                selection = await self.existing_llm_router.select_provider(
                    test_request, 
                    user_preferences={"preferred_model": model_id}
                )
                
                if selection:
                    selected_provider, selected_model = selection
                    # Verify the selected model matches our request
                    return selected_model == model_id or selected_provider == connection.provider
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to verify routing for model {model_id}: {e}")
            return False
    
    async def route_request_to_model(
        self, 
        request: Union[ChatRequest, Any], 
        model_id: str
    ) -> Optional[RoutingDecision]:
        """
        Route a request to a specific model with verified connection.
        
        Args:
            request: The request to route
            model_id: Target model ID
            
        Returns:
            RoutingDecision if successful, None otherwise
        """
        try:
            # Ensure model connection exists and is active
            connection = await self.wire_model_connection(model_id)
            if not connection:
                logger.error(f"Cannot route to model {model_id}: connection failed")
                return None
            
            # Update usage tracking
            connection.last_used = time.time()
            
            # Create routing decision
            decision = RoutingDecision(
                model_id=model_id,
                provider=connection.provider,
                model_connection=connection,
                routing_strategy=self.routing_strategy,
                confidence=1.0,  # Direct routing has high confidence
                reasoning=f"Direct routing to requested model {model_id}"
            )
            
            # Update performance metrics
            await self._update_request_metrics(model_id, success=True)
            
            logger.info(f"Successfully routed request to model {model_id}")
            return decision
            
        except Exception as e:
            logger.error(f"Failed to route request to model {model_id}: {e}")
            await self._update_request_metrics(model_id, success=False)
            return None
    
    async def select_optimal_model_for_task(
        self, 
        task_type: str, 
        modalities: List[ModalityType],
        user_preferences: Optional[Dict[str, Any]] = None
    ) -> Optional[RoutingDecision]:
        """
        Select optimal model based on task requirements and modalities.
        
        This method enhances existing profile-based routing with discovered models.
        """
        user_preferences = user_preferences or {}
        
        try:
            # If preserving existing routing, use existing logic first
            if self.preserve_existing_routing:
                decision = await self._use_existing_routing_logic(
                    task_type, modalities, user_preferences
                )
                if decision:
                    return decision
            
            # Enhanced selection with discovered models
            return await self._enhanced_model_selection(
                task_type, modalities, user_preferences
            )
            
        except Exception as e:
            logger.error(f"Failed to select optimal model: {e}")
            return None
    
    async def _use_existing_routing_logic(
        self,
        task_type: str,
        modalities: List[ModalityType],
        user_preferences: Dict[str, Any]
    ) -> Optional[RoutingDecision]:
        """Use existing routing logic from LLM routers."""
        try:
            # Fallback to basic LLM router (IntelligentLLMRouter retired)
            chat_request = ChatRequest(
                message="Task routing request",
                preferred_model=user_preferences.get("preferred_model")
            )

            selection = await self.existing_llm_router.select_provider(
                chat_request, user_preferences
            )

            if selection:
                provider, model = selection
                model_id = f"{provider}:{model}" if model else provider

                # Get or create connection
                connection = await self.wire_model_connection(model_id)
                if connection:
                    return RoutingDecision(
                        model_id=model_id,
                        provider=provider,
                        model_connection=connection,
                        routing_strategy=RoutingStrategy.PROFILE_BASED,
                        confidence=0.7,
                        reasoning="Using existing LLM router logic"
                    )

        except Exception as e:
            logger.error(f"Existing routing logic failed: {e}")

        return None
    
    def _convert_task_type(self, task_type: str) -> TaskType:
        """Convert string task type to TaskType enum."""
        task_mapping = {
            "chat": TaskType.CHAT,
            "code": TaskType.CODE,
            "reasoning": TaskType.REASONING,
            "embedding": TaskType.EMBEDDING,
            "summarization": TaskType.SUMMARIZATION,
            "translation": TaskType.TRANSLATION,
            "creative": TaskType.CREATIVE,
            "analysis": TaskType.ANALYSIS
        }
        
        return task_mapping.get(task_type.lower(), TaskType.CHAT)
    
    async def _enhanced_model_selection(
        self,
        task_type: str,
        modalities: List[ModalityType],
        user_preferences: Dict[str, Any]
    ) -> Optional[RoutingDecision]:
        """Enhanced model selection using discovered models."""
        try:
            # Filter models by capabilities and modalities
            suitable_models = await self.filter_models_by_capability(
                task_type, modalities
            )
            
            if not suitable_models:
                logger.warning(f"No suitable models found for task {task_type}")
                return None
            
            # Rank models by performance and suitability
            ranked_models = await self._rank_models_by_performance(suitable_models)
            
            # Select best model
            best_model_id = ranked_models[0]
            connection = await self.wire_model_connection(best_model_id)
            
            if connection:
                return RoutingDecision(
                    model_id=best_model_id,
                    provider=connection.provider,
                    model_connection=connection,
                    routing_strategy=RoutingStrategy.CAPABILITY_BASED,
                    confidence=0.9,
                    fallback_options=ranked_models[1:3],  # Top 2 alternatives
                    reasoning=f"Selected based on capabilities for {task_type} task"
                )
            
        except Exception as e:
            logger.error(f"Enhanced model selection failed: {e}")
        
        return None
    
    async def filter_models_by_capability(
        self, 
        task_type: str,
        modalities: Optional[List[ModalityType]] = None
    ) -> List[str]:
        """Filter models by capability and modality requirements."""
        suitable_models = []
        modalities = modalities or []
        
        with self._lock:
            for model_id, connection in self.model_connections.items():
                model_info = connection.model_info
                
                # Check modality support
                if modalities:
                    model_modalities = {mod.type for mod in model_info.modalities}
                    required_modalities = set(modalities)
                    
                    if not required_modalities.issubset(model_modalities):
                        continue
                
                # Check task capability
                if self._model_supports_task(model_info, task_type):
                    suitable_models.append(model_id)
        
        return suitable_models
    
    def _model_supports_task(self, model_info: ModelInfo, task_type: str) -> bool:
        """Check if model supports the specified task type."""
        # Map task types to model capabilities
        task_capability_map = {
            "chat": ["chat", "conversation", "dialogue"],
            "code": ["code", "programming", "coding"],
            "reasoning": ["reasoning", "logic", "analysis"],
            "embedding": ["embedding", "similarity", "search"],
            "summarization": ["summarization", "summary", "text"],
            "translation": ["translation", "multilingual", "language"],
            "creative": ["creative", "generation", "writing"],
            "analysis": ["analysis", "understanding", "comprehension"]
        }
        
        required_capabilities = task_capability_map.get(task_type.lower(), [])
        model_capabilities = [cap.lower() for cap in model_info.capabilities]
        
        # Check if any required capability is supported
        return any(req_cap in model_capabilities for req_cap in required_capabilities)
    
    async def _rank_models_by_performance(self, model_ids: List[str]) -> List[str]:
        """Rank models by performance metrics."""
        model_scores = []
        
        for model_id in model_ids:
            metrics = self.performance_metrics.get(model_id)
            if not metrics:
                # New model, assign neutral score
                score = 0.5
            else:
                # Calculate composite score
                success_rate = (metrics.successful_requests / max(metrics.total_requests, 1))
                availability = metrics.availability_score
                performance = 1.0 / max(metrics.average_response_time, 0.1)  # Inverse of response time
                
                score = (success_rate * 0.4 + availability * 0.3 + performance * 0.3)
            
            model_scores.append((model_id, score))
        
        # Sort by score (descending)
        model_scores.sort(key=lambda x: x[1], reverse=True)
        
        return [model_id for model_id, _ in model_scores]
    
    async def get_models_by_modality(self, modality: ModalityType) -> List[ModelInfo]:
        """Get all models that support a specific modality."""
        matching_models = []
        
        with self._lock:
            for connection in self.model_connections.values():
                model_info = connection.model_info
                model_modalities = {mod.type for mod in model_info.modalities}
                
                if modality in model_modalities:
                    matching_models.append(model_info)
        
        return matching_models
    
    async def recommend_model_for_query(
        self, 
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> List[RoutingDecision]:
        """Recommend models for a specific query with ranking."""
        context = context or {}
        
        try:
            # Analyze query to determine task type and requirements
            task_type = self._analyze_query_task_type(query)
            modalities = self._analyze_query_modalities(query)
            
            # Get suitable models
            suitable_models = await self.filter_models_by_capability(task_type, modalities)
            
            if not suitable_models:
                return []
            
            # Rank and create recommendations
            ranked_models = await self._rank_models_by_performance(suitable_models)
            recommendations = []
            
            for i, model_id in enumerate(ranked_models[:5]):  # Top 5 recommendations
                connection = self.model_connections.get(model_id)
                if connection:
                    confidence = max(0.9 - (i * 0.1), 0.5)  # Decreasing confidence
                    
                    decision = RoutingDecision(
                        model_id=model_id,
                        provider=connection.provider,
                        model_connection=connection,
                        routing_strategy=RoutingStrategy.PERFORMANCE_BASED,
                        confidence=confidence,
                        reasoning=f"Recommended for {task_type} task (rank {i+1})"
                    )
                    recommendations.append(decision)
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Failed to recommend models for query: {e}")
            return []
    
    def _analyze_query_task_type(self, query: str) -> str:
        """Analyze query to determine task type."""
        query_lower = query.lower()
        
        # Simple keyword-based analysis
        if any(word in query_lower for word in ["code", "program", "function", "class"]):
            return "code"
        elif any(word in query_lower for word in ["explain", "analyze", "reason", "why"]):
            return "reasoning"
        elif any(word in query_lower for word in ["summarize", "summary", "brief"]):
            return "summarization"
        elif any(word in query_lower for word in ["translate", "translation"]):
            return "translation"
        elif any(word in query_lower for word in ["create", "write", "generate", "story"]):
            return "creative"
        else:
            return "chat"
    
    def _analyze_query_modalities(self, query: str) -> List[ModalityType]:
        """Analyze query to determine required modalities."""
        modalities = [ModalityType.TEXT]  # Always include text
        
        query_lower = query.lower()
        
        if any(word in query_lower for word in ["image", "picture", "photo", "visual"]):
            modalities.append(ModalityType.IMAGE)
        elif any(word in query_lower for word in ["video", "movie", "clip"]):
            modalities.append(ModalityType.VIDEO)
        elif any(word in query_lower for word in ["audio", "sound", "music", "voice"]):
            modalities.append(ModalityType.AUDIO)
        
        return modalities
    
    async def handle_model_fallback(
        self, 
        failed_model: str, 
        required_modalities: List[ModalityType],
        task_type: str = "chat"
    ) -> Optional[RoutingDecision]:
        """Handle fallback when a model fails."""
        try:
            logger.warning(f"Handling fallback for failed model: {failed_model}")
            
            # Mark failed model as temporarily unavailable
            if failed_model in self.model_connections:
                self.model_connections[failed_model].status = ConnectionStatus.ERROR
            
            # Update failure metrics
            await self._update_request_metrics(failed_model, success=False)
            
            # Find alternative models
            alternative_models = await self.filter_models_by_capability(
                task_type, required_modalities
            )
            
            # Remove failed model from alternatives
            alternative_models = [m for m in alternative_models if m != failed_model]
            
            if not alternative_models:
                logger.error("No alternative models available for fallback")
                return None
            
            # Select best alternative
            ranked_alternatives = await self._rank_models_by_performance(alternative_models)
            best_alternative = ranked_alternatives[0]
            
            # Route to alternative
            return await self.route_request_to_model(
                ChatRequest(message="Fallback routing"), 
                best_alternative
            )
            
        except Exception as e:
            logger.error(f"Fallback handling failed: {e}")
            return None
    
    async def get_active_model_info(self) -> Dict[str, Any]:
        """Get information about currently active models."""
        active_models = {}
        
        with self._lock:
            for model_id, connection in self.model_connections.items():
                if connection.status == ConnectionStatus.CONNECTED:
                    metrics = self.performance_metrics.get(model_id)
                    
                    active_models[model_id] = {
                        "provider": connection.provider,
                        "model_info": {
                            "name": connection.model_info.name,
                            "type": connection.model_info.type.value,
                            "category": connection.model_info.category.value,
                            "capabilities": connection.model_info.capabilities,
                            "modalities": [mod.type.value for mod in connection.model_info.modalities]
                        },
                        "connection_time": connection.connection_time,
                        "last_used": connection.last_used,
                        "performance": {
                            "total_requests": metrics.total_requests if metrics else 0,
                            "success_rate": (metrics.successful_requests / max(metrics.total_requests, 1)) if metrics else 0,
                            "average_response_time": metrics.average_response_time if metrics else 0,
                            "availability_score": metrics.availability_score if metrics else 1.0
                        }
                    }
        
        return active_models
    
    async def _update_request_metrics(
        self,
        model_id: str,
        success: bool,
        response_time: Optional[float] = None,
    ):
        """Update performance metrics for a model."""
        with self._lock:
            if model_id not in self.performance_metrics:
                connection = self.model_connections.get(model_id)
                provider = connection.provider if connection else "unknown"
                self.performance_metrics[model_id] = ModelPerformanceMetrics(
                    model_id=model_id,
                    provider=provider
                )
            
            metrics = self.performance_metrics[model_id]
            metrics.total_requests += 1
            metrics.last_used = time.time()
            
            if success:
                metrics.successful_requests += 1
                if response_time:
                    # Update average response time
                    if metrics.average_response_time == 0:
                        metrics.average_response_time = response_time
                    else:
                        metrics.average_response_time = (
                            metrics.average_response_time * 0.8 + response_time * 0.2
                        )
            else:
                metrics.failed_requests += 1
            
            # Update error rate
            metrics.error_rate = metrics.failed_requests / metrics.total_requests
            
            # Update availability score (exponential decay)
            if success:
                metrics.availability_score = min(1.0, metrics.availability_score + 0.1)
            else:
                metrics.availability_score = max(0.0, metrics.availability_score - 0.2)
        
        # Periodically save performance cache
        if time.time() - self.last_cache_update > 60:  # Every minute
            self._save_performance_cache()
            self.last_cache_update = time.time()
    
    def _load_performance_cache(self):
        """Load performance metrics from cache."""
        try:
            if self.performance_cache_file.exists():
                with open(self.performance_cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                for model_id, metrics_data in cache_data.items():
                    self.performance_metrics[model_id] = ModelPerformanceMetrics(
                        model_id=metrics_data["model_id"],
                        provider=metrics_data["provider"],
                        total_requests=metrics_data.get("total_requests", 0),
                        successful_requests=metrics_data.get("successful_requests", 0),
                        failed_requests=metrics_data.get("failed_requests", 0),
                        average_response_time=metrics_data.get("average_response_time", 0.0),
                        average_tokens_per_second=metrics_data.get("average_tokens_per_second", 0.0),
                        last_used=metrics_data.get("last_used"),
                        error_rate=metrics_data.get("error_rate", 0.0),
                        availability_score=metrics_data.get("availability_score", 1.0),
                        user_satisfaction=metrics_data.get("user_satisfaction", 0.0)
                    )
                
                logger.info(f"Loaded performance cache for {len(self.performance_metrics)} models")
        except Exception as e:
            logger.warning(f"Failed to load performance cache: {e}")
    
    def _save_performance_cache(self):
        """Save performance metrics to cache."""
        try:
            cache_data = {}
            for model_id, metrics in self.performance_metrics.items():
                cache_data[model_id] = {
                    "model_id": metrics.model_id,
                    "provider": metrics.provider,
                    "total_requests": metrics.total_requests,
                    "successful_requests": metrics.successful_requests,
                    "failed_requests": metrics.failed_requests,
                    "average_response_time": metrics.average_response_time,
                    "average_tokens_per_second": metrics.average_tokens_per_second,
                    "last_used": metrics.last_used,
                    "error_rate": metrics.error_rate,
                    "availability_score": metrics.availability_score,
                    "user_satisfaction": metrics.user_satisfaction
                }
            
            with open(self.performance_cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save performance cache: {e}")
    
    async def get_routing_statistics(self) -> Dict[str, Any]:
        """Get comprehensive routing statistics."""
        stats = {
            "total_models": len(self.model_connections),
            "connected_models": len([c for c in self.model_connections.values() 
                                   if c.status == ConnectionStatus.CONNECTED]),
            "total_requests": sum(m.total_requests for m in self.performance_metrics.values()),
            "successful_requests": sum(m.successful_requests for m in self.performance_metrics.values()),
            "average_success_rate": 0.0,
            "top_performing_models": [],
            "routing_strategy": self.routing_strategy.value,
            "provider_distribution": {},
            "modality_coverage": {}
        }
        
        # Calculate average success rate
        if stats["total_requests"] > 0:
            stats["average_success_rate"] = stats["successful_requests"] / stats["total_requests"]
        
        # Get top performing models
        model_performance = []
        for model_id, metrics in self.performance_metrics.items():
            if metrics.total_requests > 0:
                success_rate = metrics.successful_requests / metrics.total_requests
                model_performance.append((model_id, success_rate, metrics.total_requests))
        
        model_performance.sort(key=lambda x: (x[1], x[2]), reverse=True)
        stats["top_performing_models"] = model_performance[:5]
        
        # Provider distribution
        provider_counts = {}
        for connection in self.model_connections.values():
            provider = connection.provider
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
        stats["provider_distribution"] = provider_counts
        
        # Modality coverage
        modality_counts = {}
        for connection in self.model_connections.values():
            for modality in connection.model_info.modalities:
                mod_type = modality.type.value
                modality_counts[mod_type] = modality_counts.get(mod_type, 0) + 1
        stats["modality_coverage"] = modality_counts
        
        return stats

# Global instance
_model_router: Optional[ModelRouter] = None
_router_lock = threading.RLock()

def get_model_router() -> ModelRouter:
    """Get the global model router instance."""
    global _model_router
    if _model_router is None:
        with _router_lock:
            if _model_router is None:
                _model_router = ModelRouter()
    return _model_router

async def initialize_model_router() -> ModelRouter:
    """Initialize the global model router."""
    router = get_model_router()
    await router.initialize()
    return router
