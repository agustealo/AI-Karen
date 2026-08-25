"""
Health monitoring and management for NLP services.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.memory.signals.distilbert_service import (
    DistilBertHealthStatus,
    DistilBertService,
)
from ai_karen_engine.core.memory.signals.nlp_config import NLPConfig
from ai_karen_engine.core.memory.signals.spacy_service import (
    SpacyHealthStatus,
    SpacyService,
)

logger = get_logger(__name__)


@dataclass
class NLPSystemHealth:
    """Overall health status of NLP system."""
    
    is_healthy: bool
    spacy_status: SpacyHealthStatus
    distilbert_status: DistilBertHealthStatus
    system_uptime: float
    last_check: datetime
    alerts: list[str]


class NLPHealthMonitor:
    """Health monitoring service for NLP components."""
    
    def __init__(
        self, 
        spacy_service: SpacyService,
        distilbert_service: DistilBertService,
        config: NLPConfig | None = None
    ):
        self.spacy_service = spacy_service
        self.distilbert_service = distilbert_service
        self.config = config or NLPConfig()
        
        self.start_time = time.time()
        self.monitoring_task = None
        self.is_monitoring = False
        
        # Health history for trend analysis
        self.health_history = []
        self.max_history_size = 1000
        
        # Alert thresholds
        self.alert_thresholds = {
            'max_error_count': 10,
            'min_cache_hit_rate': 0.5,
            'max_avg_processing_time': 5.0,  # seconds
            'max_consecutive_failures': 3
        }
        
        self.consecutive_failures = 0
    
    async def start_monitoring(self):
        """Start continuous health monitoring."""
        if self.is_monitoring:
            logger.warning("Health monitoring already running")
            return
        
        self.is_monitoring = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("NLP health monitoring started")
    
    async def stop_monitoring(self):
        """Stop health monitoring."""
        if not self.is_monitoring:
            return
        
        self.is_monitoring = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("NLP health monitoring stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.is_monitoring:
            try:
                health_status = await self.check_health()
                self._record_health_status(health_status)
                
                if not health_status.is_healthy:
                    self.consecutive_failures += 1
                    logger.warning(f"NLP system unhealthy (failure #{self.consecutive_failures})")
                    
                    # Attempt recovery if too many failures
                    if self.consecutive_failures >= self.alert_thresholds['max_consecutive_failures']:
                        await self._attempt_recovery()
                else:
                    self.consecutive_failures = 0
                
                await asyncio.sleep(self.config.health_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(self.config.health_check_interval)
    
    async def check_health(self) -> NLPSystemHealth:
        """Perform comprehensive health check."""
        spacy_status = self.spacy_service.get_health_status()
        distilbert_status = self.distilbert_service.get_health_status()
        
        # Determine overall health
        is_healthy = spacy_status.is_healthy and distilbert_status.is_healthy
        
        # Generate alerts
        alerts = []
        alerts.extend(self._check_spacy_alerts(spacy_status))
        alerts.extend(self._check_distilbert_alerts(distilbert_status))
        
        return NLPSystemHealth(
            is_healthy=is_healthy,
            spacy_status=spacy_status,
            distilbert_status=distilbert_status,
            system_uptime=time.time() - self.start_time,
            last_check=datetime.now(),
            alerts=alerts
        )
    
    def _check_spacy_alerts(self, status: SpacyHealthStatus) -> list[str]:
        """Check for spaCy-specific alerts."""
        alerts = []
        
        if status.error_count > self.alert_thresholds['max_error_count']:
            alerts.append(f"spaCy error count high: {status.error_count}")
        
        if status.cache_hit_rate < self.alert_thresholds['min_cache_hit_rate']:
            alerts.append(f"spaCy cache hit rate low: {status.cache_hit_rate:.2f}")
        
        if status.avg_processing_time > self.alert_thresholds['max_avg_processing_time']:
            alerts.append(f"spaCy processing time high: {status.avg_processing_time:.2f}s")
        
        if status.fallback_mode:
            alerts.append("spaCy running in fallback mode")
        
        if not status.model_loaded:
            alerts.append("spaCy model not loaded")
        
        return alerts
    
    def _check_distilbert_alerts(self, status: DistilBertHealthStatus) -> list[str]:
        """Check for DistilBERT-specific alerts."""
        alerts = []
        
        if status.error_count > self.alert_thresholds['max_error_count']:
            alerts.append(f"DistilBERT error count high: {status.error_count}")
        
        if status.cache_hit_rate < self.alert_thresholds['min_cache_hit_rate']:
            alerts.append(f"DistilBERT cache hit rate low: {status.cache_hit_rate:.2f}")
        
        if status.avg_processing_time > self.alert_thresholds['max_avg_processing_time']:
            alerts.append(f"DistilBERT processing time high: {status.avg_processing_time:.2f}s")
        
        if status.fallback_mode:
            alerts.append("DistilBERT running in fallback mode")
        
        if not status.model_loaded:
            alerts.append("DistilBERT model not loaded")
        
        return alerts
    
    def _record_health_status(self, health_status: NLPSystemHealth):
        """Record health status in history."""
        self.health_history.append(health_status)
        
        # Trim history if too large
        if len(self.health_history) > self.max_history_size:
            self.health_history = self.health_history[-self.max_history_size:]
    
    async def _attempt_recovery(self):
        """Attempt to recover from failures."""
        logger.info("Attempting NLP system recovery...")
        
        try:
            # Try to reload models
            if not self.spacy_service.get_health_status().model_loaded:
                await self.spacy_service.reload_model()
            
            if not self.distilbert_service.get_health_status().model_loaded:
                await self.distilbert_service.reload_model()
            
            # Clear caches to free memory
            self.spacy_service.clear_cache()
            self.distilbert_service.clear_cache()
            
            # Reset metrics
            self.spacy_service.reset_metrics()
            self.distilbert_service.reset_metrics()
            
            logger.info("NLP system recovery completed")
            
        except Exception as e:
            logger.error(f"NLP system recovery failed: {e}")
    
    def get_health_summary(self) -> dict[str, Any]:
        """Get a summary of current health status."""
        if not self.health_history:
            return {"status": "no_data", "message": "No health data available"}
        
        latest_health = self.health_history[-1]
        
        return {
            "status": "healthy" if latest_health.is_healthy else "unhealthy",
            "uptime": latest_health.system_uptime,
            "last_check": latest_health.last_check.isoformat(),
            "alerts": latest_health.alerts,
            "spacy": {
                "model_loaded": latest_health.spacy_status.model_loaded,
                "fallback_mode": latest_health.spacy_status.fallback_mode,
                "cache_hit_rate": latest_health.spacy_status.cache_hit_rate,
                "avg_processing_time": latest_health.spacy_status.avg_processing_time,
                "error_count": latest_health.spacy_status.error_count
            },
            "distilbert": {
                "model_loaded": latest_health.distilbert_status.model_loaded,
                "fallback_mode": latest_health.distilbert_status.fallback_mode,
                "device": latest_health.distilbert_status.device,
                "cache_hit_rate": latest_health.distilbert_status.cache_hit_rate,
                "avg_processing_time": latest_health.distilbert_status.avg_processing_time,
                "error_count": latest_health.distilbert_status.error_count
            },
            "consecutive_failures": self.consecutive_failures
        }
    
    def get_health_trends(self, hours: int = 24) -> dict[str, Any]:
        """Get health trends over specified time period."""
        if not self.health_history:
            return {"error": "No health data available"}
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_history = [
            h for h in self.health_history 
            if h.last_check >= cutoff_time
        ]
        
        if not recent_history:
            return {"error": f"No health data in last {hours} hours"}
        
        # Calculate trends
        total_checks = len(recent_history)
        healthy_checks = sum(1 for h in recent_history if h.is_healthy)
        health_percentage = (healthy_checks / total_checks) * 100
        
        spacy_fallback_count = sum(1 for h in recent_history if h.spacy_status.fallback_mode)
        distilbert_fallback_count = sum(1 for h in recent_history if h.distilbert_status.fallback_mode)
        
        avg_spacy_processing = sum(h.spacy_status.avg_processing_time for h in recent_history) / total_checks
        avg_distilbert_processing = sum(h.distilbert_status.avg_processing_time for h in recent_history) / total_checks
        
        return {
            "period_hours": hours,
            "total_checks": total_checks,
            "health_percentage": health_percentage,
            "spacy_fallback_percentage": (spacy_fallback_count / total_checks) * 100,
            "distilbert_fallback_percentage": (distilbert_fallback_count / total_checks) * 100,
            "avg_spacy_processing_time": avg_spacy_processing,
            "avg_distilbert_processing_time": avg_distilbert_processing,
            "recent_alerts": list(set(alert for h in recent_history for alert in h.alerts))
        }
    
    async def run_diagnostic(self) -> dict[str, Any]:
        """Run comprehensive diagnostic tests."""
        logger.info("Running NLP system diagnostics...")
        
        diagnostic_results = {
            "timestamp": datetime.now().isoformat(),
            "tests": {}
        }
        
        # Test spaCy parsing
        try:
            test_text = "Hello, my name is John Doe and I work at OpenAI in San Francisco."
            start_time = time.time()
            parsed = await self.spacy_service.parse_message(test_text)
            processing_time = time.time() - start_time
            
            diagnostic_results["tests"]["spacy_parsing"] = {
                "status": "pass",
                "processing_time": processing_time,
                "tokens_found": len(parsed.tokens),
                "entities_found": len(parsed.entities),
                "used_fallback": parsed.used_fallback
            }
        except Exception as e:
            diagnostic_results["tests"]["spacy_parsing"] = {
                "status": "fail",
                "error": str(e)
            }
        
        # Test DistilBERT embeddings
        try:
            test_text = "This is a test sentence for embedding generation."
            start_time = time.time()
            embeddings = await self.distilbert_service.get_embeddings(test_text)
            processing_time = time.time() - start_time
            
            diagnostic_results["tests"]["distilbert_embeddings"] = {
                "status": "pass",
                "processing_time": processing_time,
                "embedding_dimension": len(embeddings),
                "embedding_norm": sum(x*x for x in embeddings) ** 0.5
            }
        except Exception as e:
            diagnostic_results["tests"]["distilbert_embeddings"] = {
                "status": "fail",
                "error": str(e)
            }
        
        # Test batch processing
        try:
            test_texts = ["First sentence.", "Second sentence.", "Third sentence."]
            start_time = time.time()
            batch_embeddings = await self.distilbert_service.batch_embeddings(test_texts)
            processing_time = time.time() - start_time
            
            diagnostic_results["tests"]["batch_processing"] = {
                "status": "pass",
                "processing_time": processing_time,
                "batch_size": len(test_texts),
                "embeddings_generated": len(batch_embeddings)
            }
        except Exception as e:
            diagnostic_results["tests"]["batch_processing"] = {
                "status": "fail",
                "error": str(e)
            }
        
        # Overall diagnostic status
        passed_tests = sum(1 for test in diagnostic_results["tests"].values() if test["status"] == "pass")
        total_tests = len(diagnostic_results["tests"])
        diagnostic_results["overall_status"] = "pass" if passed_tests == total_tests else "partial_fail"
        diagnostic_results["passed_tests"] = passed_tests
        diagnostic_results["total_tests"] = total_tests
        
        logger.info(f"Diagnostics completed: {passed_tests}/{total_tests} tests passed")
        return diagnostic_results
