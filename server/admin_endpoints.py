# mypy: ignore-errors
"""
Admin endpoints for Kari FastAPI Server.
Handles /api/admin/* routes for system administration and configuration.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any
from fastapi import FastAPI
from .config import Settings
from .validation import initialize_validation_framework

logger = logging.getLogger("kari")


def register_admin_endpoints(app: FastAPI, settings: Settings) -> None:
    """Register all admin endpoints"""
    
    @app.get("/api/admin/performance/status", tags=["admin"])
    async def get_performance_status():
        """Get current performance optimization status"""
        try:
            from ai_karen_engine.server.optimized_startup import (
                get_lifecycle_manager, get_resource_monitor, get_performance_metrics
            )
            
            lifecycle_manager = get_lifecycle_manager()
            resource_monitor = get_resource_monitor()
            performance_metrics = get_performance_metrics()
            
            status = {
                "optimization_enabled": settings.enable_performance_optimization,
                "deployment_mode": settings.deployment_mode,
                "components": {
                    "lifecycle_manager": lifecycle_manager is not None,
                    "resource_monitor": resource_monitor is not None,
                    "performance_metrics": performance_metrics is not None
                }
            }
            
            if resource_monitor:
                status["resource_usage"] = await resource_monitor.get_current_metrics()
            
            if performance_metrics:
                status["performance_summary"] = await performance_metrics.get_summary()
            
            return status
            
        except Exception as e:
            return {"error": str(e), "optimization_enabled": False}
    
    @app.post("/api/admin/performance/audit", tags=["admin"])
    async def run_performance_audit():
        """Run a performance audit"""
        try:
            from tools.performance_auditor import PerformanceAuditor
            
            auditor = PerformanceAuditor()
            await auditor.initialize()
            
            audit_report = await auditor.audit_runtime_performance()
            recommendations = await auditor.generate_optimization_recommendations()
            
            return {
                "success": True,
                "audit_report": audit_report,
                "recommendations": recommendations
            }
            
        except Exception as e:
            logger.error(f"Performance audit failed: {e}")
            return {"success": False, "error": str(e)}
    
    @app.post("/api/admin/performance/optimize", tags=["admin"])
    async def trigger_optimization():
        """Trigger performance optimization"""
        try:
            from ai_karen_engine.server.optimized_startup import get_lifecycle_manager
            
            lifecycle_manager = get_lifecycle_manager()
            if not lifecycle_manager:
                return {"success": False, "error": "Optimization not enabled"}
            
            # Trigger service consolidation and optimization
            optimization_report = await lifecycle_manager.optimize_services()
            
            return {
                "success": True,
                "message": "Performance optimization completed",
                "report": optimization_report
            }
            
        except Exception as e:
            logger.error(f"Performance optimization failed: {e}")
            return {"success": False, "error": str(e)}
    
    @app.get("/api/admin/validation/config", tags=["admin"])
    async def get_validation_config():
        """Get current validation configuration"""
        try:
            import ai_karen_engine.server.middleware as middleware_module
            validation_config = getattr(middleware_module, '_validation_config', None)
            
            if validation_config is None:
                return {"error": "Validation configuration not initialized"}
            
            return {
                "max_content_length": validation_config.max_content_length,
                "max_headers_count": validation_config.max_headers_count,
                "max_header_size": validation_config.max_header_size,
                "rate_limit_requests_per_minute": validation_config.rate_limit_requests_per_minute,
                "enable_security_analysis": validation_config.enable_security_analysis,
                "log_invalid_requests": validation_config.log_invalid_requests,
                "blocked_user_agents": list(validation_config.blocked_user_agents),
                "suspicious_headers": list(validation_config.suspicious_headers),
                "environment": settings.environment
            }
        except Exception as e:
            return {"error": str(e)}
    
    @app.post("/api/admin/validation/reload", tags=["admin"])
    async def reload_validation_config():
        """Reload validation configuration from environment variables (Requirement 4.4)"""
        try:
            # Reload settings from environment
            new_settings = Settings()
            
            # Reinitialize validation framework with new settings
            initialize_validation_framework(new_settings)
            
            return {
                "success": True,
                "message": "Validation configuration reloaded successfully",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": new_settings.environment,
                "max_request_size_mb": new_settings.max_request_size / (1024*1024),
                "security_analysis_enabled": new_settings.enable_security_analysis
            }
        except Exception as e:
            logger.error(f"Failed to reload validation configuration: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    @app.post("/api/admin/validation/update-patterns", tags=["admin"])
    async def update_validation_patterns(request: dict):
        """Update validation patterns without code changes (Requirement 4.4)"""
        try:
            import ai_karen_engine.server.middleware as middleware_module
            validation_config = getattr(middleware_module, '_validation_config', None)
            
            if validation_config is None:
                return {"error": "Validation configuration not initialized"}
            
            # Update blocked user agents if provided
            if "blocked_user_agents" in request:
                new_agents = set(agent.strip().lower() for agent in request["blocked_user_agents"] if agent.strip())
                validation_config.blocked_user_agents = new_agents
                logger.info(f"Updated blocked user agents: {len(new_agents)} patterns")
            
            # Update suspicious headers if provided
            if "suspicious_headers" in request:
                new_headers = set(header.strip().lower() for header in request["suspicious_headers"] if header.strip())
                validation_config.suspicious_headers = new_headers
                logger.info(f"Updated suspicious headers: {len(new_headers)} patterns")
            
            # Update rate limiting if provided
            if "rate_limit_requests_per_minute" in request:
                new_rate_limit = int(request["rate_limit_requests_per_minute"])
                if 1 <= new_rate_limit <= 10000:
                    validation_config.rate_limit_requests_per_minute = new_rate_limit
                    logger.info(f"Updated rate limit: {new_rate_limit} requests/minute")
                else:
                    return {"error": "Rate limit must be between 1 and 10000"}
            
            # Update security analysis toggle if provided
            if "enable_security_analysis" in request:
                validation_config.enable_security_analysis = bool(request["enable_security_analysis"])
                logger.info(f"Security analysis: {'enabled' if validation_config.enable_security_analysis else 'disabled'}")
            
            return {
                "success": True,
                "message": "Validation patterns updated successfully",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "updated_config": {
                    "blocked_user_agents": len(validation_config.blocked_user_agents),
                    "suspicious_headers": len(validation_config.suspicious_headers),
                    "rate_limit_requests_per_minute": validation_config.rate_limit_requests_per_minute,
                    "enable_security_analysis": validation_config.enable_security_analysis
                }
            }
        except Exception as e:
            logger.error(f"Failed to update validation patterns: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    @app.get("/api/admin/validation/status", tags=["admin"])
    async def get_validation_status():
        """Get validation system status and metrics"""
        try:
            import ai_karen_engine.server.middleware as middleware_module
            validation_config = getattr(middleware_module, '_validation_config', None)
            enhanced_logger = getattr(middleware_module, '_enhanced_logger', None)
            
            status = {
                "validation_framework_initialized": validation_config is not None,
                "enhanced_logging_initialized": enhanced_logger is not None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": settings.environment
            }
            
            if validation_config:
                status["configuration"] = {
                    "max_content_length_mb": validation_config.max_content_length / (1024*1024),
                    "max_headers_count": validation_config.max_headers_count,
                    "max_header_size": validation_config.max_header_size,
                    "rate_limit_per_minute": validation_config.rate_limit_requests_per_minute,
                    "security_analysis_enabled": validation_config.enable_security_analysis,
                    "logging_enabled": validation_config.log_invalid_requests,
                    "blocked_agents_count": len(validation_config.blocked_user_agents),
                    "suspicious_headers_count": len(validation_config.suspicious_headers)
                }
            
            # Try to get validation metrics if available
            try:
                from ai_karen_engine.core.observability.metrics import get_metrics_manager
                metrics_manager = get_metrics_manager()
                
                # Get validation-related metrics
                validation_metrics = {}
                with metrics_manager.safe_metrics_context():
                    # These metrics would be populated by the middleware
                    validation_metrics = {
                        "total_requests_validated": "available",
                        "invalid_requests_blocked": "available", 
                        "security_threats_detected": "available",
                        "rate_limited_requests": "available"
                    }
                
                status["metrics"] = validation_metrics
            except Exception:
                status["metrics"] = {"error": "Metrics not available"}
            
            return status
            
        except Exception as e:
            return {
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }