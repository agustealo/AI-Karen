"""
Agent Monitor service for monitoring agent activities and performance.

.. deprecated::
    The legacy agent monitor is deprecated. Use ``ai_karen_engine.agent_medusa.telemetry``
    for canonical metrics and tracing.
"""

import asyncio
import logging
import warnings
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from ai_karen_engine.core.services.base import BaseService, ServiceConfig

warnings.warn(
    "ai_karen_engine.agents.agent_monitor is deprecated. "
    "Use ai_karen_engine.agent_medusa.telemetry instead.",
    DeprecationWarning,
    stacklevel=2,
)

logger = logging.getLogger(__name__)


class AgentMonitor(BaseService):
    """
    Agent Monitor service for monitoring agent activities and performance.
    
    This service provides monitoring capabilities for agents, tracking their activities,
    performance metrics, and health status.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_monitor"))
        self._initialized = False
        self._agent_metrics: Dict[str, Dict[str, Any]] = {}
        self._agent_activities: List[Dict[str, Any]] = []
        self._agent_health_status: Dict[str, str] = {}
        self._alerts: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize the agent monitor."""
        if self._initialized:
            return
            
        self._agent_metrics = {}
        self._agent_activities = []
        self._agent_health_status = {}
        self._alerts = []
        self._initialized = True
        logger.info("Agent monitor initialized successfully")
    
    async def start(self) -> None:
        """Start the agent monitor."""
        logger.info("Agent monitor started")
    
    async def stop(self) -> None:
        """Stop the agent monitor."""
        logger.info("Agent monitor stopped")
    
    async def health_check(self) -> bool:
        """Check health of the agent monitor."""
        return self._initialized
    
    async def record_agent_activity(
        self, 
        agent_id: str, 
        activity_type: str, 
        details: Dict[str, Any]
    ) -> bool:
        """
        Record an agent activity.
        
        Args:
            agent_id: Identifier of the agent
            activity_type: Type of activity
            details: Details about the activity
            
        Returns:
            True if recording was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            # Initialize agent metrics if not exists
            if agent_id not in self._agent_metrics:
                self._agent_metrics[agent_id] = {
                    "total_activities": 0,
                    "activities_by_type": {},
                    "first_activity": None,
                    "last_activity": None,
                    "average_response_time": 0.0,
                    "total_response_time": 0.0,
                    "response_count": 0
                }
            
            # Update metrics
            metrics = self._agent_metrics[agent_id]
            metrics["total_activities"] += 1
            
            if activity_type not in metrics["activities_by_type"]:
                metrics["activities_by_type"][activity_type] = 0
            metrics["activities_by_type"][activity_type] += 1
            
            now = datetime.utcnow()
            if not metrics["first_activity"]:
                metrics["first_activity"] = now.isoformat()
            metrics["last_activity"] = now.isoformat()
            
            # Update response time metrics if available
            if "response_time" in details:
                response_time = details["response_time"]
                metrics["total_response_time"] += response_time
                metrics["response_count"] += 1
                metrics["average_response_time"] = (
                    metrics["total_response_time"] / metrics["response_count"]
                )
            
            # Record activity
            activity = {
                "agent_id": agent_id,
                "activity_type": activity_type,
                "timestamp": now.isoformat(),
                "details": details
            }
            
            self._agent_activities.append(activity)
            
            # Keep only last 1000 activities
            if len(self._agent_activities) > 1000:
                self._agent_activities = self._agent_activities[-1000:]
            
            logger.debug(f"Recorded activity {activity_type} for agent {agent_id}")
            return True
    
    async def update_agent_health(
        self, 
        agent_id: str, 
        health_status: str
    ) -> bool:
        """
        Update the health status of an agent.
        
        Args:
            agent_id: Identifier of the agent
            health_status: Health status (healthy, degraded, unhealthy)
            
        Returns:
            True if update was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            old_status = self._agent_health_status.get(agent_id)
            self._agent_health_status[agent_id] = health_status
            
            # Create alert if status changed to unhealthy or degraded
            if old_status and old_status != health_status:
                if health_status in ["unhealthy", "degraded"]:
                    alert = {
                        "agent_id": agent_id,
                        "alert_type": "health_status_change",
                        "message": f"Agent health status changed from {old_status} to {health_status}",
                        "timestamp": datetime.utcnow().isoformat(),
                        "severity": "warning" if health_status == "degraded" else "critical"
                    }
                    self._alerts.append(alert)
                    
                    # Keep only last 100 alerts
                    if len(self._alerts) > 100:
                        self._alerts = self._alerts[-100:]
                    
                    logger.warning(f"Agent {agent_id} health status changed to {health_status}")
            
            return True
    
    async def get_agent_metrics(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metrics for a specific agent.
        
        Args:
            agent_id: Identifier of the agent
            
        Returns:
            Agent metrics or None if not found
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            if agent_id in self._agent_metrics:
                return self._agent_metrics[agent_id].copy()
            return None
    
    async def get_agent_activities(
        self, 
        agent_id: Optional[str] = None,
        activity_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get agent activities, optionally filtered.
        
        Args:
            agent_id: Optional filter for agent ID
            activity_type: Optional filter for activity type
            limit: Maximum number of activities to return
            
        Returns:
            List of agent activities
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            activities = self._agent_activities.copy()
            
            # Filter by agent ID if specified
            if agent_id:
                activities = [a for a in activities if a["agent_id"] == agent_id]
            
            # Filter by activity type if specified
            if activity_type:
                activities = [a for a in activities if a["activity_type"] == activity_type]
            
            # Return most recent activities first
            activities.sort(key=lambda a: a["timestamp"], reverse=True)
            
            return activities[:limit]
    
    async def get_agent_health_status(self, agent_id: str) -> Optional[str]:
        """
        Get the health status of a specific agent.
        
        Args:
            agent_id: Identifier of the agent
            
        Returns:
            Health status or None if not found
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            return self._agent_health_status.get(agent_id)
    
    async def get_all_agent_health_status(self) -> Dict[str, str]:
        """
        Get the health status of all agents.
        
        Returns:
            Dictionary mapping agent IDs to health status
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            return self._agent_health_status.copy()
    
    async def get_alerts(
        self, 
        agent_id: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get alerts, optionally filtered.
        
        Args:
            agent_id: Optional filter for agent ID
            severity: Optional filter for alert severity
            limit: Maximum number of alerts to return
            
        Returns:
            List of alerts
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            alerts = self._alerts.copy()
            
            # Filter by agent ID if specified
            if agent_id:
                alerts = [a for a in alerts if a["agent_id"] == agent_id]
            
            # Filter by severity if specified
            if severity:
                alerts = [a for a in alerts if a["severity"] == severity]
            
            # Return most recent alerts first
            alerts.sort(key=lambda a: a["timestamp"], reverse=True)
            
            return alerts[:limit]
    
    async def get_system_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the agent monitoring system.
        
        Returns:
            System summary information
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            # Count agents by health status
            health_counts = {"healthy": 0, "degraded": 0, "unhealthy": 0}
            for status in self._agent_health_status.values():
                if status in health_counts:
                    health_counts[status] += 1
            
            # Calculate total activities
            total_activities = sum(m["total_activities"] for m in self._agent_metrics.values())
            
            # Count agents by activity level
            now = datetime.utcnow()
            active_agents = 0
            inactive_agents = 0
            
            for agent_id, metrics in self._agent_metrics.items():
                if metrics["last_activity"]:
                    last_activity = datetime.fromisoformat(metrics["last_activity"])
                    if now - last_activity < timedelta(minutes=5):
                        active_agents += 1
                    else:
                        inactive_agents += 1
            
            return {
                "total_agents": len(self._agent_metrics),
                "agent_health_status": health_counts,
                "total_activities": total_activities,
                "active_agents": active_agents,
                "inactive_agents": inactive_agents,
                "total_alerts": len(self._alerts),
                "unresolved_alerts": len([a for a in self._alerts if not a.get("resolved", False)])
            }
    
    async def resolve_alert(self, alert_id: int) -> bool:
        """
        Resolve an alert.
        
        Args:
            alert_id: ID of the alert to resolve
            
        Returns:
            True if resolution was successful, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        async with self._lock:
            if 0 <= alert_id < len(self._alerts):
                self._alerts[alert_id]["resolved"] = True
                self._alerts[alert_id]["resolved_at"] = datetime.utcnow().isoformat()
                logger.info(f"Resolved alert {alert_id}")
                return True
            return False