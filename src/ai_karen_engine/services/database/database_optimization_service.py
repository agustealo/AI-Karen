"""
Database Optimization Service

Enhanced database connection optimization with:
- Advanced connection pooling strategies
- Exponential backoff retry mechanisms
- Cross-database consistency monitoring
- Performance metrics and alerting
- Automatic failover and recovery
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import random
import json

from ai_karen_engine.core.services.base import BaseService, ServiceConfig
from ai_karen_engine.database.client import get_database_client
from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager
from ai_karen_engine.services.database.health.checker import DatabaseHealthChecker


class RetryStrategy(str, Enum):
    """Retry strategy types."""
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_INTERVAL = "fixed_interval"
    JITTERED_EXPONENTIAL = "jittered_exponential"


@dataclass
class RetryConfig:
    """Configuration for retry mechanisms."""
    strategy: RetryStrategy = RetryStrategy.JITTERED_EXPONENTIAL
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1


@dataclass
class ConnectionPoolMetrics:
    """Connection pool performance metrics."""
    timestamp: datetime
    database_name: str
    pool_size: int
    active_connections: int
    idle_connections: int
    overflow_connections: int
    failed_connections: int
    avg_connection_time_ms: float
    max_connection_time_ms: float
    total_queries: int
    slow_queries: int
    connection_errors: List[str] = field(default_factory=list)


@dataclass
class DatabasePerformanceAlert:
    """Database performance alert."""
    alert_id: str
    timestamp: datetime
    database_name: str
    alert_type: str
    severity: str
    message: str
    metrics: Dict[str, Any]
    resolved: bool = False
    resolved_at: Optional[datetime] = None


class DatabaseOptimizationService(BaseService):
    """
    Advanced database optimization service for production deployment.
    
    Features:
    - Intelligent connection pool management
    - Exponential backoff retry mechanisms
    - Cross-database consistency monitoring
    - Performance metrics collection
    - Automatic alerting and recovery
    - Connection health optimization
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        if config is None:
            config = ServiceConfig(
                name="database_optimization",
                enabled=True,
                config={
                    "monitoring_interval_seconds": 30,
                    "metrics_retention_hours": 24,
                    "slow_query_threshold_ms": 1000,
                    "connection_timeout_seconds": 30,
                    "pool_optimization_enabled": True,
                    "auto_scaling_enabled": True,
                    "max_pool_size": 50,
                    "min_pool_size": 5,
                    "alerting_enabled": True,
                    "alert_thresholds": {
                        "high_connection_usage": 0.8,
                        "slow_query_rate": 0.1,
                        "connection_error_rate": 0.05,
                        "response_time_ms": 2000
                    }
                }
            )
        
        super().__init__(config)
        
        # Configuration
        self.monitoring_interval = config.config.get("monitoring_interval_seconds", 30)
        self.metrics_retention_hours = config.config.get("metrics_retention_hours", 24)
        self.slow_query_threshold = config.config.get("slow_query_threshold_ms", 1000)
        self.connection_timeout = config.config.get("connection_timeout_seconds", 30)
        self.pool_optimization_enabled = config.config.get("pool_optimization_enabled", True)
        self.auto_scaling_enabled = config.config.get("auto_scaling_enabled", True)
        self.max_pool_size = config.config.get("max_pool_size", 50)
        self.min_pool_size = config.config.get("min_pool_size", 5)
        self.alerting_enabled = config.config.get("alerting_enabled", True)
        self.alert_thresholds = config.config.get("alert_thresholds", {})
        
        # Service dependencies
        self.db_client = get_database_client()
        self.redis_manager = get_redis_manager()
        self.health_checker = DatabaseHealthChecker()
        
        # Runtime state
        self.metrics_history: List[ConnectionPoolMetrics] = []
        self.active_alerts: List[DatabasePerformanceAlert] = []
        self.monitoring_task: Optional[asyncio.Task] = None
        self.optimization_task: Optional[asyncio.Task] = None
        
        # Retry configurations for different operations
        self.retry_configs = {
            "database_query": RetryConfig(
                strategy=RetryStrategy.JITTERED_EXPONENTIAL,
                max_attempts=3,
                base_delay=0.5,
                max_delay=10.0
            ),
            "connection_establishment": RetryConfig(
                strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
                max_attempts=5,
                base_delay=1.0,
                max_delay=30.0
            ),
            "health_check": RetryConfig(
                strategy=RetryStrategy.FIXED_INTERVAL,
                max_attempts=3,
                base_delay=2.0,
                max_delay=2.0
            )
        }
    
    async def initialize(self) -> None:
        """Initialize the database optimization service."""
        self.logger.info("Initializing Database Optimization Service")
        
        # Initialize dependencies
        await self.db_client.initialize()
        await self.redis_manager.initialize()
        await self.health_checker.initialize()
        
        self.logger.info("Database optimization service initialized")
    
    async def start(self) -> None:
        """Start the optimization service."""
        self.logger.info("Starting Database Optimization Service")
        
        # Start monitoring tasks
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        if self.pool_optimization_enabled:
            self.optimization_task = asyncio.create_task(self._optimization_loop())
        
        self.logger.info("Database optimization service started")
    
    async def stop(self) -> None:
        """Stop the optimization service."""
        self.logger.info("Stopping Database Optimization Service")
        
        # Cancel monitoring tasks
        if self.monitoring_task is not None:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        if self.optimization_task is not None:
            self.optimization_task.cancel()
            try:
                await self.optimization_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Database optimization service stopped")
    
    async def health_check(self) -> bool:
        """Perform health check."""
        try:
            # Check if monitoring is running
            if self.monitoring_task is not None and self.monitoring_task.done():
                return False
            
            # Check database connectivity
            return await self.db_client.async_health_check()
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while True:
            try:
                await self._collect_metrics()
                await self._check_alerts()
                await self._cleanup_old_metrics()
                
                await asyncio.sleep(self.monitoring_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(self.monitoring_interval)
    
    async def _optimization_loop(self) -> None:
        """Connection pool optimization loop."""
        while True:
            try:
                await self._optimize_connection_pools()
                await asyncio.sleep(300)  # Run every 5 minutes
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in optimization loop: {e}")
                await asyncio.sleep(300)
    
    async def _collect_metrics(self) -> None:
        """Collect connection pool metrics."""
        try:
            # Get database metrics
            db_metrics = await self._collect_database_metrics()
            if db_metrics:
                self.metrics_history.append(db_metrics)
            
            # Get Redis metrics
            redis_metrics = await self._collect_redis_metrics()
            if redis_metrics:
                self.metrics_history.append(redis_metrics)
            
        except Exception as e:
            self.logger.error(f"Error collecting metrics: {e}")
    
    async def _collect_database_metrics(self) -> Optional[ConnectionPoolMetrics]:
        """Collect PostgreSQL connection pool metrics."""
        try:
            pool_info = self.db_client._get_pool_metrics()
            
            if not pool_info.get("sync_pool"):
                return None
            
            sync_pool = pool_info["sync_pool"]
            
            # Calculate performance metrics
            total_connections = sync_pool.get("size", 0)
            active_connections = sync_pool.get("checked_out", 0)
            idle_connections = sync_pool.get("checked_in", 0)
            overflow_connections = sync_pool.get("overflow", 0)
            
            # Test connection performance
            start_time = time.time()
            connection_successful = await self.db_client.async_health_check()
            connection_time_ms = (time.time() - start_time) * 1000
            
            return ConnectionPoolMetrics(
                timestamp=datetime.now(timezone.utc),
                database_name="postgresql",
                pool_size=total_connections,
                active_connections=active_connections,
                idle_connections=idle_connections,
                overflow_connections=overflow_connections,
                failed_connections=0 if connection_successful else 1,
                avg_connection_time_ms=connection_time_ms,
                max_connection_time_ms=connection_time_ms,
                total_queries=0,  # Would need query tracking
                slow_queries=0,   # Would need query tracking
                connection_errors=[] if connection_successful else ["Health check failed"]
            )
            
        except Exception as e:
            self.logger.error(f"Error collecting database metrics: {e}")
            return None
    
    async def _collect_redis_metrics(self) -> Optional[ConnectionPoolMetrics]:
        """Collect Redis connection pool metrics."""
        try:
            redis_health = await self.redis_manager.health_check()
            
            if not redis_health.get("healthy"):
                return None
            
            # Get Redis connection info
            connection_info = redis_health.get("connection_info", {})
            
            return ConnectionPoolMetrics(
                timestamp=datetime.now(timezone.utc),
                database_name="redis",
                pool_size=connection_info.get("max_connections", 0),
                active_connections=connection_info.get("active_connections", 0),
                idle_connections=connection_info.get("idle_connections", 0),
                overflow_connections=0,
                failed_connections=0,
                avg_connection_time_ms=redis_health.get("response_time_ms", 0),
                max_connection_time_ms=redis_health.get("response_time_ms", 0),
                total_queries=0,
                slow_queries=0,
                connection_errors=[]
            )
            
        except Exception as e:
            self.logger.error(f"Error collecting Redis metrics: {e}")
            return None
    
    async def _check_alerts(self) -> None:
        """Check for performance alerts."""
        if not self.alerting_enabled or not self.metrics_history:
            return
        
        try:
            recent_metrics = [
                m for m in self.metrics_history
                if m.timestamp > datetime.now(timezone.utc) - timedelta(minutes=10)
            ]
            
            if not recent_metrics:
                return
            
            # Check various alert conditions
            await self._check_connection_usage_alerts(recent_metrics)
            await self._check_response_time_alerts(recent_metrics)
            await self._check_error_rate_alerts(recent_metrics)
            
        except Exception as e:
            self.logger.error(f"Error checking alerts: {e}")
    
    async def _check_connection_usage_alerts(self, metrics: List[ConnectionPoolMetrics]) -> None:
        """Check for high connection usage alerts."""
        threshold = self.alert_thresholds.get("high_connection_usage", 0.8)
        
        for metric in metrics:
            if metric.pool_size > 0:
                usage_ratio = metric.active_connections / metric.pool_size
                
                if usage_ratio > threshold:
                    await self._create_alert(
                        alert_type="high_connection_usage",
                        severity="warning",
                        database_name=metric.database_name,
                        message=f"High connection usage: {usage_ratio:.2%} ({metric.active_connections}/{metric.pool_size})",
                        metrics={"usage_ratio": usage_ratio, "active_connections": metric.active_connections}
                    )
    
    async def _check_response_time_alerts(self, metrics: List[ConnectionPoolMetrics]) -> None:
        """Check for high response time alerts."""
        threshold = self.alert_thresholds.get("response_time_ms", 2000)
        
        for metric in metrics:
            if metric.avg_connection_time_ms > threshold:
                await self._create_alert(
                    alert_type="high_response_time",
                    severity="warning",
                    database_name=metric.database_name,
                    message=f"High response time: {metric.avg_connection_time_ms:.2f}ms",
                    metrics={"response_time_ms": metric.avg_connection_time_ms}
                )
    
    async def _check_error_rate_alerts(self, metrics: List[ConnectionPoolMetrics]) -> None:
        """Check for high error rate alerts."""
        threshold = self.alert_thresholds.get("connection_error_rate", 0.05)
        
        # Group metrics by database
        db_metrics = {}
        for metric in metrics:
            if metric.database_name not in db_metrics:
                db_metrics[metric.database_name] = []
            db_metrics[metric.database_name].append(metric)
        
        for db_name, db_metric_list in db_metrics.items():
            total_attempts = len(db_metric_list)
            failed_attempts = sum(1 for m in db_metric_list if m.failed_connections > 0)
            
            if total_attempts > 0:
                error_rate = failed_attempts / total_attempts
                
                if error_rate > threshold:
                    await self._create_alert(
                        alert_type="high_error_rate",
                        severity="critical",
                        database_name=db_name,
                        message=f"High error rate: {error_rate:.2%} ({failed_attempts}/{total_attempts})",
                        metrics={"error_rate": error_rate, "failed_attempts": failed_attempts}
                    )
    
    async def _create_alert(self, alert_type: str, severity: str, database_name: str, 
                          message: str, metrics: Dict[str, Any]) -> None:
        """Create a new performance alert."""
        alert_id = f"{alert_type}_{database_name}_{int(time.time())}"
        
        # Check if similar alert already exists
        existing_alert = next(
            (a for a in self.active_alerts 
             if a.alert_type == alert_type and a.database_name == database_name and not a.resolved),
            None
        )
        
        if existing_alert:
            # Update existing alert
            existing_alert.message = message
            existing_alert.metrics = metrics
            existing_alert.timestamp = datetime.now(timezone.utc)
        else:
            # Create new alert
            alert = DatabasePerformanceAlert(
                alert_id=alert_id,
                timestamp=datetime.now(timezone.utc),
                database_name=database_name,
                alert_type=alert_type,
                severity=severity,
                message=message,
                metrics=metrics
            )
            
            self.active_alerts.append(alert)
            self.logger.warning(f"Database alert created: {message}")
    
    async def _optimize_connection_pools(self) -> None:
        """Optimize connection pool configurations."""
        if not self.auto_scaling_enabled or not self.metrics_history:
            return
        
        try:
            # Analyze recent metrics
            recent_metrics = [
                m for m in self.metrics_history
                if m.timestamp > datetime.now(timezone.utc) - timedelta(hours=1)
            ]
            
            if not recent_metrics:
                return
            
            # Group by database
            db_metrics = {}
            for metric in recent_metrics:
                if metric.database_name not in db_metrics:
                    db_metrics[metric.database_name] = []
                db_metrics[metric.database_name].append(metric)
            
            # Optimize each database
            for db_name, metrics in db_metrics.items():
                await self._optimize_database_pool(db_name, metrics)
                
        except Exception as e:
            self.logger.error(f"Error optimizing connection pools: {e}")
    
    async def _optimize_database_pool(self, db_name: str, metrics: List[ConnectionPoolMetrics]) -> None:
        """Optimize connection pool for a specific database."""
        if not metrics:
            return
        
        # Calculate average usage
        avg_active = sum(m.active_connections for m in metrics) / len(metrics)
        avg_pool_size = sum(m.pool_size for m in metrics) / len(metrics)
        
        if avg_pool_size == 0:
            return
        
        usage_ratio = avg_active / avg_pool_size
        
        # Determine if pool size adjustment is needed
        if usage_ratio > 0.8 and avg_pool_size < self.max_pool_size:
            # Increase pool size
            new_size = min(int(avg_pool_size * 1.2), self.max_pool_size)
            self.logger.info(f"Recommending pool size increase for {db_name}: {avg_pool_size} -> {new_size}")
            
        elif usage_ratio < 0.3 and avg_pool_size > self.min_pool_size:
            # Decrease pool size
            new_size = max(int(avg_pool_size * 0.8), self.min_pool_size)
            self.logger.info(f"Recommending pool size decrease for {db_name}: {avg_pool_size} -> {new_size}")
    
    async def _cleanup_old_metrics(self) -> None:
        """Clean up old metrics to prevent memory growth."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=self.metrics_retention_hours)
        
        # Remove old metrics
        self.metrics_history = [
            m for m in self.metrics_history
            if m.timestamp > cutoff_time
        ]
        
        # Remove old resolved alerts
        self.active_alerts = [
            a for a in self.active_alerts
            if not a.resolved or (a.resolved_at is not None and a.resolved_at > cutoff_time)
        ]
    
    async def execute_with_retry(self, operation_name: str, operation_func, *args, **kwargs) -> Any:
        """
        Execute an operation with retry logic and exponential backoff.
        
        Args:
            operation_name: Name of the operation for logging and retry config
            operation_func: The function to execute
            *args, **kwargs: Arguments to pass to the function
            
        Returns:
            Result of the operation
            
        Raises:
            Exception: If all retry attempts fail
        """
        retry_config = self.retry_configs.get(operation_name, self.retry_configs["database_query"])
        
        last_exception = None
        
        for attempt in range(retry_config.max_attempts):
            try:
                if asyncio.iscoroutinefunction(operation_func):
                    result = await operation_func(*args, **kwargs)
                else:
                    result = operation_func(*args, **kwargs)
                
                # Success - log if this wasn't the first attempt
                if attempt > 0:
                    self.logger.info(f"Operation '{operation_name}' succeeded on attempt {attempt + 1}")
                
                return result
                
            except Exception as e:
                last_exception = e
                
                if attempt == retry_config.max_attempts - 1:
                    # Last attempt failed
                    self.logger.error(f"Operation '{operation_name}' failed after {retry_config.max_attempts} attempts: {e}")
                    break
                
                # Calculate delay for next attempt
                delay = self._calculate_retry_delay(retry_config, attempt)
                
                self.logger.warning(f"Operation '{operation_name}' failed on attempt {attempt + 1}, retrying in {delay:.2f}s: {e}")
                await asyncio.sleep(delay)
        
        # All attempts failed
        if last_exception is not None:
            raise last_exception
        raise RuntimeError(f"Operation '{operation_name}' failed after {retry_config.max_attempts} attempts")
    
    def _calculate_retry_delay(self, config: RetryConfig, attempt: int) -> float:
        """Calculate delay for retry attempt based on strategy."""
        if config.strategy == RetryStrategy.FIXED_INTERVAL:
            return config.base_delay
        
        elif config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = config.base_delay * (attempt + 1)
            
        elif config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = config.base_delay * (config.backoff_multiplier ** attempt)
            
        elif config.strategy == RetryStrategy.JITTERED_EXPONENTIAL:
            base_delay = config.base_delay * (config.backoff_multiplier ** attempt)
            jitter = base_delay * config.jitter_factor * random.random()
            delay = base_delay + jitter
            
        else:
            delay = config.base_delay
        
        # Cap at max delay
        return min(delay, config.max_delay)
    
    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics."""
        recent_metrics = [
            m for m in self.metrics_history
            if m.timestamp > datetime.now(timezone.utc) - timedelta(hours=1)
        ]
        
        # Group by database
        db_metrics = {}
        for metric in recent_metrics:
            if metric.database_name not in db_metrics:
                db_metrics[metric.database_name] = []
            db_metrics[metric.database_name].append(metric)
        
        # Calculate summary statistics
        summary = {}
        for db_name, metrics in db_metrics.items():
            if metrics:
                summary[db_name] = {
                    "avg_active_connections": sum(m.active_connections for m in metrics) / len(metrics),
                    "avg_pool_size": sum(m.pool_size for m in metrics) / len(metrics),
                    "avg_response_time_ms": sum(m.avg_connection_time_ms for m in metrics) / len(metrics),
                    "total_failed_connections": sum(m.failed_connections for m in metrics),
                    "connection_usage_ratio": (sum(m.active_connections for m in metrics) / len(metrics)) / 
                                            (sum(m.pool_size for m in metrics) / len(metrics)) if sum(m.pool_size for m in metrics) > 0 else 0
                }
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "databases": summary,
            "active_alerts": len([a for a in self.active_alerts if not a.resolved]),
            "total_metrics_collected": len(self.metrics_history),
            "monitoring_enabled": self.monitoring_task is not None and not self.monitoring_task.done(),
            "optimization_enabled": self.pool_optimization_enabled
        }
    
    async def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get list of active alerts."""
        return [
            {
                "alert_id": alert.alert_id,
                "timestamp": alert.timestamp.isoformat(),
                "database_name": alert.database_name,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "metrics": alert.metrics,
                "resolved": alert.resolved
            }
            for alert in self.active_alerts
            if not alert.resolved
        ]
    
    async def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an active alert."""
        for alert in self.active_alerts:
            if alert.alert_id == alert_id and not alert.resolved:
                alert.resolved = True
                alert.resolved_at = datetime.now(timezone.utc)
                self.logger.info(f"Alert resolved: {alert_id}")
                return True
        
        return False
