"""
Integrated Model Management System

Integrates the model discovery engine with the current model management system
while maintaining profile-based routing and existing functionality.

Requirements addressed:
- 7.1: Discover and display all models from models/* directory
- 7.2: Properly wire and route requests to selected models
- 8.4: Maintain existing profile-based routing for different task types
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from pathlib import Path

from ai_karen_engine.core.model_runtime.model_discovery_service import (
    ModelDiscoveryService,
    get_model_discovery_service,
)
from ..routing.intelligent_model_router import (
    ModelRouter,
    get_model_router,
)
from ai_karen_engine.core.memory.profile_synthesis.profile_manager import (
    ProfileManager, get_profile_manager, LLMProfile
)
from .model_connection_manager import (
    ModelConnectionManager,
    get_connection_manager,
)

logger = logging.getLogger("kari.integrated_model_management")

@dataclass
class ModelIntegrationStatus:
    """Status of model integration with existing systems."""
    model_id: str
    discovered: bool = False
    profile_compatible: bool = False
    connection_verified: bool = False
    routing_enabled: bool = False
    last_updated: float = field(default_factory=time.time)
    error_message: Optional[str] = None

class IntegratedModelManager:
    """
    Integrated model management that combines discovery, routing, and profiles
    while preserving existing functionality.
    """
    
    def __init__(self):
        self.logger = logging.getLogger("kari.integrated_model_manager")
        
        # Core services
        self.discovery_engine = get_model_discovery_service()
        self.model_router = get_model_router()
        self.profile_manager = get_profile_manager()
        self.connection_manager = get_connection_manager(self.model_router)
        
        # Integration state
        self.integration_status: Dict[str, ModelIntegrationStatus] = {}
        self.profile_model_mappings: Dict[str, Set[str]] = {}  # profile -> model_ids
        self.model_profile_mappings: Dict[str, Set[str]] = {}  # model_id -> profiles
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Background refresh
        self._refresh_interval = 300  # 5 minutes
        self._last_refresh = 0.0
        
        self.logger.info("Integrated Model Manager initialized")
    
    async def initialize(self):
        """Initialize the integrated model management system."""
        try:
            # Discover all available models
            await self.refresh_model_discovery()
            
            # Integrate with existing profiles
            await self.integrate_with_profiles()
            
            # Verify connections
            await self.verify_model_connections()
            
            self.logger.info("Integrated model management system initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize integrated model management: {e}")
            raise
    
    async def refresh_model_discovery(self) -> Dict[str, Any]:
        """Refresh model discovery and update integration status."""
        try:
            # Discover all models
            discovered_models = await self.discovery_engine.discover_all_models()
            
            # Update integration status
            with self._lock:
                # Mark existing models as potentially stale
                for status in self.integration_status.values():
                    status.discovered = False
                
                # Update with discovered models
                for model_info in discovered_models:
                    if model_info.id not in self.integration_status:
                        self.integration_status[model_info.id] = ModelIntegrationStatus(
                            model_id=model_info.id
                        )
                    
                    status = self.integration_status[model_info.id]
                    status.discovered = True
                    status.last_updated = time.time()
                    status.error_message = None
                
                # Remove models that are no longer discovered
                stale_models = [
                    model_id for model_id, status in self.integration_status.items()
                    if not status.discovered
                ]
                
                for model_id in stale_models:
                    del self.integration_status[model_id]
                    # Clean up mappings
                    if model_id in self.model_profile_mappings:
                        del self.model_profile_mappings[model_id]
            
            self._last_refresh = time.time()
            
            return {
                "discovered_models": len(discovered_models),
                "integrated_models": len(self.integration_status),
                "stale_models_removed": len(stale_models),
                "timestamp": time.time()
            }
            
        except Exception as e:
            self.logger.error(f"Model discovery refresh failed: {e}")
            return {"error": str(e), "timestamp": time.time()}
    
    async def integrate_with_profiles(self) -> Dict[str, Any]:
        """Integrate discovered models with existing profiles."""
        try:
            profiles = self.profile_manager.list_profiles()
            discovered_models = await self.discovery_engine.get_all_models()
            
            integration_results = {
                "profiles_updated": 0,
                "models_mapped": 0,
                "compatibility_issues": []
            }
            
            with self._lock:
                # Clear existing mappings
                self.profile_model_mappings.clear()
                self.model_profile_mappings.clear()
                
                for profile in profiles:
                    profile_models = set()
                    
                    # Map models to profile based on capabilities and preferences
                    for model_info in discovered_models:
                        if await self._is_model_compatible_with_profile(model_info, profile):
                            profile_models.add(model_info.id)
                            
                            # Update model -> profile mapping
                            if model_info.id not in self.model_profile_mappings:
                                self.model_profile_mappings[model_info.id] = set()
                            self.model_profile_mappings[model_info.id].add(profile.name)
                            
                            # Update integration status
                            if model_info.id in self.integration_status:
                                self.integration_status[model_info.id].profile_compatible = True
                    
                    self.profile_model_mappings[profile.name] = profile_models
                    integration_results["models_mapped"] += len(profile_models)
                
                integration_results["profiles_updated"] = len(profiles)
            
            self.logger.info(f"Integrated {integration_results['models_mapped']} models with {integration_results['profiles_updated']} profiles")
            return integration_results
            
        except Exception as e:
            self.logger.error(f"Profile integration failed: {e}")
            return {"error": str(e)}
    
    async def _is_model_compatible_with_profile(self, model_info: Any, profile: LLMProfile) -> bool:
        """Check if a model is compatible with a profile."""
        try:
            # Check modality compatibility
            required_modalities = set()
            if "text" in profile.guardrails.allowed_capabilities:
                required_modalities.add("TEXT")
            if "vision" in profile.guardrails.allowed_capabilities:
                required_modalities.add("IMAGE")
            
            model_modalities = {mod.type.value for mod in model_info.modalities}
            if required_modalities and not required_modalities.intersection(model_modalities):
                return False
            
            # Check resource requirements
            if (hasattr(model_info, 'requirements') and 
                model_info.requirements and 
                hasattr(model_info.requirements, 'memory_mb')):
                if model_info.requirements.memory_mb > profile.memory_budget.memory_limit_mb:
                    return False
            
            # Check context length compatibility
            if (hasattr(model_info, 'metadata') and 
                model_info.metadata and 
                hasattr(model_info.metadata, 'context_length')):
                if model_info.metadata.context_length > profile.memory_budget.max_context_length:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Compatibility check failed for {model_info.id}: {e}")
            return False
    
    async def verify_model_connections(self) -> Dict[str, Any]:
        """Verify connections to integrated models."""
        try:
            verification_results = {
                "verified_models": 0,
                "failed_models": 0,
                "connection_errors": []
            }
            
            with self._lock:
                model_ids = list(self.integration_status.keys())
            
            for model_id in model_ids:
                try:
                    # Verify connection through connection manager
                    connection_verified = await self.connection_manager.verify_model_connection(model_id)
                    
                    with self._lock:
                        if model_id in self.integration_status:
                            self.integration_status[model_id].connection_verified = connection_verified
                            if connection_verified:
                                self.integration_status[model_id].routing_enabled = True
                                verification_results["verified_models"] += 1
                            else:
                                verification_results["failed_models"] += 1
                                self.integration_status[model_id].error_message = "Connection verification failed"
                
                except Exception as e:
                    verification_results["failed_models"] += 1
                    verification_results["connection_errors"].append({
                        "model_id": model_id,
                        "error": str(e)
                    })
                    
                    with self._lock:
                        if model_id in self.integration_status:
                            self.integration_status[model_id].connection_verified = False
                            self.integration_status[model_id].error_message = str(e)
            
            self.logger.info(f"Verified connections for {verification_results['verified_models']} models")
            return verification_results
            
        except Exception as e:
            self.logger.error(f"Connection verification failed: {e}")
            return {"error": str(e)}
    
    async def get_models_for_profile(self, profile_name: str) -> List[Dict[str, Any]]:
        """Get all models compatible with a specific profile."""
        try:
            # Refresh if needed
            if time.time() - self._last_refresh > self._refresh_interval:
                await self.refresh_model_discovery()
            
            with self._lock:
                model_ids = self.profile_model_mappings.get(profile_name, set())
            
            models = []
            for model_id in model_ids:
                try:
                    model_info = await self.discovery_engine.get_model_info(model_id)
                    if model_info:
                        status = self.integration_status.get(model_id)
                        models.append({
                            "model_info": model_info,
                            "integration_status": status,
                            "connection_verified": status.connection_verified if status else False,
                            "routing_enabled": status.routing_enabled if status else False
                        })
                except Exception as e:
                    self.logger.error(f"Failed to get model info for {model_id}: {e}")
            
            return models
            
        except Exception as e:
            self.logger.error(f"Failed to get models for profile {profile_name}: {e}")
            return []
    
    async def get_enhanced_routing_decision(
        self, 
        task_type: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get enhanced routing decision that combines profile-based routing
        with discovered model capabilities.
        """
        try:
            # Get original profile-based routing decision
            profile_decision = self.profile_manager.get_routing_decision(task_type, context)
            
            # Get active profile
            active_profile = self.profile_manager.get_active_profile()
            if not active_profile:
                return profile_decision
            
            # Get models compatible with active profile
            compatible_models = await self.get_models_for_profile(active_profile.name)
            
            # Filter models that are actually available and verified
            available_models = [
                model for model in compatible_models
                if model["connection_verified"] and model["routing_enabled"]
            ]
            
            # Enhance decision with discovered models
            enhanced_decision = profile_decision.copy()
            enhanced_decision.update({
                "discovered_models_count": len(compatible_models),
                "available_models_count": len(available_models),
                "available_models": [
                    {
                        "model_id": model["model_info"].id,
                        "model_name": model["model_info"].name,
                        "model_type": model["model_info"].type.value,
                        "capabilities": [cap.value for cap in model["model_info"].capabilities],
                        "modalities": [mod.type.value for mod in model["model_info"].modalities]
                    }
                    for model in available_models[:5]  # Limit to top 5
                ],
                "integration_enhanced": True
            })
            
            # If original provider is not available, suggest alternatives
            if (profile_decision["provider"] not in [m["model_info"].name for m in available_models] and
                available_models):
                
                # Find best alternative based on task type
                best_alternative = None
                for model in available_models:
                    model_info = model["model_info"]
                    if task_type.upper() in [cap.value for cap in model_info.capabilities]:
                        best_alternative = model_info
                        break
                
                if best_alternative:
                    enhanced_decision["alternative_provider"] = best_alternative.name
                    enhanced_decision["alternative_reason"] = f"Discovered model with {task_type} capability"
            
            return enhanced_decision
            
        except Exception as e:
            self.logger.error(f"Enhanced routing decision failed: {e}")
            # Return original decision on error
            return self.profile_manager.get_routing_decision(task_type, context)
    
    def get_integration_status(self) -> Dict[str, Any]:
        """Get comprehensive integration status."""
        with self._lock:
            total_models = len(self.integration_status)
            discovered_models = sum(1 for s in self.integration_status.values() if s.discovered)
            verified_models = sum(1 for s in self.integration_status.values() if s.connection_verified)
            routing_enabled_models = sum(1 for s in self.integration_status.values() if s.routing_enabled)
            
            return {
                "total_models": total_models,
                "discovered_models": discovered_models,
                "verified_models": verified_models,
                "routing_enabled_models": routing_enabled_models,
                "profile_mappings": {
                    profile: len(models) for profile, models in self.profile_model_mappings.items()
                },
                "last_refresh": self._last_refresh,
                "refresh_interval": self._refresh_interval,
                "integration_health": {
                    "discovery_rate": discovered_models / total_models if total_models > 0 else 0,
                    "verification_rate": verified_models / total_models if total_models > 0 else 0,
                    "routing_rate": routing_enabled_models / total_models if total_models > 0 else 0
                }
            }
    
    async def enable_model_routing(self, model_id: str) -> bool:
        """Enable routing for a specific model."""
        try:
            # Verify connection first
            connection_verified = await self.connection_manager.verify_model_connection(model_id)
            
            if connection_verified:
                with self._lock:
                    if model_id in self.integration_status:
                        self.integration_status[model_id].routing_enabled = True
                        self.integration_status[model_id].connection_verified = True
                        self.integration_status[model_id].error_message = None
                
                self.logger.info(f"Enabled routing for model: {model_id}")
                return True
            else:
                with self._lock:
                    if model_id in self.integration_status:
                        self.integration_status[model_id].error_message = "Connection verification failed"
                
                self.logger.warning(f"Cannot enable routing for model {model_id}: connection verification failed")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to enable routing for model {model_id}: {e}")
            with self._lock:
                if model_id in self.integration_status:
                    self.integration_status[model_id].error_message = str(e)
            return False
    
    async def disable_model_routing(self, model_id: str) -> bool:
        """Disable routing for a specific model."""
        try:
            with self._lock:
                if model_id in self.integration_status:
                    self.integration_status[model_id].routing_enabled = False
            
            self.logger.info(f"Disabled routing for model: {model_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to disable routing for model {model_id}: {e}")
            return False

# Global instance
_integrated_model_manager: Optional[IntegratedModelManager] = None
_manager_lock = threading.RLock()

def get_integrated_model_manager() -> IntegratedModelManager:
    """Get the global integrated model manager instance."""
    global _integrated_model_manager
    if _integrated_model_manager is None:
        with _manager_lock:
            if _integrated_model_manager is None:
                _integrated_model_manager = IntegratedModelManager()
    return _integrated_model_manager

async def initialize_integrated_model_management():
    """Initialize the integrated model management system."""
    manager = get_integrated_model_manager()
    await manager.initialize()
    return manager
