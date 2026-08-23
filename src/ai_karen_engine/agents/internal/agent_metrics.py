"""
Agent Metrics module for the agent system.

This module implements metrics collection for the agent system, including performance metrics,
task metrics, memory metrics, tool usage metrics, communication metrics, error metrics,
session metrics, and resource usage metrics.
"""

import time
import threading
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta
import logging

from ai_karen_engine.core.services.base import BaseService, ServiceConfig

try:
    from ai_karen_engine.monitoring.agent_metrics_prometheus import get_agent_prometheus_metrics
    _AGENT_PROMETHEUS_METRICS = get_agent_prometheus_metrics()
except Exception:
    _AGENT_PROMETHEUS_METRICS = None

logger = logging.getLogger(__name__)


class AgentMetrics(BaseService):
    """
    Agent Metrics service for collecting and managing agent system metrics.
    
    This service provides comprehensive metrics collection for all components of the agent system,
    enabling monitoring, analysis, and optimization of agent performance and resource usage.
    """
    
    def __init__(self, config: Optional[ServiceConfig] = None):
        super().__init__(config or ServiceConfig(name="agent_metrics"))
        self._initialized = False
        self._lock = threading.RLock()
        
        # Performance metrics
        self._agent_execution_times: Dict[str, List[float]] = defaultdict(list)
        self._agent_success_rates: Dict[str, Dict[str, int]] = defaultdict(lambda: {"success": 0, "failure": 0})
        self._agent_throughput: Dict[str, List[Tuple[datetime, int]]] = defaultdict(list)
        
        # Task metrics
        self._task_queue_lengths: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._task_processing_times: Dict[str, List[float]] = defaultdict(list)
        self._task_status_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # Memory metrics
        self._memory_usage: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        self._memory_hits: Dict[str, int] = defaultdict(int)
        self._memory_misses: Dict[str, int] = defaultdict(int)
        self._memory_evictions: Dict[str, int] = defaultdict(int)
        
        # Tool usage metrics
        self._tool_usage_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._tool_execution_times: Dict[str, List[float]] = defaultdict(list)
        self._tool_error_rates: Dict[str, Dict[str, int]] = defaultdict(lambda: {"success": 0, "failure": 0})
        
        # Communication metrics
        self._message_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._message_latencies: Dict[str, List[float]] = defaultdict(list)
        self._communication_bandwidth: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        
        # Error metrics
        self._error_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._error_rates: Dict[str, List[float]] = defaultdict(list)
        self._error_recovery_times: Dict[str, List[float]] = defaultdict(list)
        
        # Session metrics
        self._session_counts: Dict[str, int] = defaultdict(int)
        self._session_durations: Dict[str, List[float]] = defaultdict(list)
        self._session_activity: Dict[str, List[Tuple[datetime, int]]] = defaultdict(list)
        
        # Resource usage metrics
        self._cpu_usage: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        self._memory_usage_bytes: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        self._disk_usage: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        self._network_usage: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        
        # Configuration
        self._metrics_retention_hours = 24 * 7  # Keep metrics for 7 days
        self._metrics_cleanup_interval_hours = 24  # Clean up old metrics every 24 hours
        self._last_cleanup_time = datetime.now()
    
    async def initialize(self) -> None:
        """Initialize the agent metrics service."""
        if self._initialized:
            return
            
        self._initialized = True
        logger.info("Agent metrics service initialized successfully")
    
    async def start(self) -> None:
        """Start the agent metrics service."""
        logger.info("Agent metrics service started")
    
    async def stop(self) -> None:
        """Stop the agent metrics service."""
        logger.info("Agent metrics service stopped")
    
    async def health_check(self) -> bool:
        """Check the health of the agent metrics service."""
        return self._initialized
    
    # Agent Performance Metrics
    
    async def record_agent_execution_time(self, agent_id: str, execution_time: float) -> None:
        """
        Record agent execution time.
        
        Args:
            agent_id: ID of the agent
            execution_time: Execution time in seconds
        """
        with self._lock:
            self._agent_execution_times[agent_id].append(execution_time)
            
            # Keep only the last 1000 records
            if len(self._agent_execution_times[agent_id]) > 1000:
                self._agent_execution_times[agent_id] = self._agent_execution_times[agent_id][-1000:]
        
        if _AGENT_PROMETHEUS_METRICS is not None:
            _AGENT_PROMETHEUS_METRICS.record_agent_execution(
                agent_id=agent_id,
                status="success",
                duration_seconds=execution_time,
            )
    
    async def record_agent_success(self, agent_id: str) -> None:
        """
        Record a successful agent operation.
        
        Args:
            agent_id: ID of the agent
        """
        with self._lock:
            self._agent_success_rates[agent_id]["success"] += 1
        
        if _AGENT_PROMETHEUS_METRICS is not None:
            _AGENT_PROMETHEUS_METRICS.record_agent_execution(
                agent_id=agent_id,
                status="success",
                duration_seconds=0.0,
            )
    
    async def record_agent_failure(self, agent_id: str) -> None:
        """
        Record a failed agent operation.
        
        Args:
            agent_id: ID of the agent
        """
        with self._lock:
            self._agent_success_rates[agent_id]["failure"] += 1
        
        if _AGENT_PROMETHEUS_METRICS is not None:
            _AGENT_PROMETHEUS_METRICS.record_agent_execution(
                agent_id=agent_id,
                status="failure",
                duration_seconds=0.0,
            )
    
    async def record_agent_throughput(self, agent_id: str, tasks_processed: int) -> None:
        """
        Record agent throughput.
        
        Args:
            agent_id: ID of the agent
            tasks_processed: Number of tasks processed
        """
        with self._lock:
            now = datetime.now()
            self._agent_throughput[agent_id].append((now, tasks_processed))
            
            # Keep only the last 1000 records
            if len(self._agent_throughput[agent_id]) > 1000:
                self._agent_throughput[agent_id] = self._agent_throughput[agent_id][-1000:]
    
    async def get_agent_performance_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get agent performance metrics.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Dictionary containing performance metrics
        """
        with self._lock:
            metrics = {}
            
            agent_ids = [agent_id] if agent_id else list(self._agent_execution_times.keys())
            
            for aid in agent_ids:
                if aid in self._agent_execution_times and self._agent_execution_times[aid]:
                    exec_times = self._agent_execution_times[aid]
                    metrics[aid] = {
                        "execution_time": {
                            "min": min(exec_times),
                            "max": max(exec_times),
                            "avg": sum(exec_times) / len(exec_times),
                            "count": len(exec_times)
                        }
                    }
                
                if aid in self._agent_success_rates:
                    success_stats = self._agent_success_rates[aid]
                    total = success_stats["success"] + success_stats["failure"]
                    success_rate = success_stats["success"] / total if total > 0 else 0
                    metrics[aid]["success_rate"] = success_rate
                    metrics[aid]["total_operations"] = total
                
                if aid in self._agent_throughput and self._agent_throughput[aid]:
                    throughput_data = self._agent_throughput[aid]
                    total_tasks = sum(count for _, count in throughput_data)
                    if len(throughput_data) > 1:
                        time_span = (throughput_data[-1][0] - throughput_data[0][0]).total_seconds()
                        if time_span > 0:
                            avg_throughput = total_tasks / time_span
                            metrics[aid]["throughput"] = {
                                "avg_tasks_per_second": avg_throughput,
                                "total_tasks": total_tasks
                            }
            
            return metrics
    
    # Task Metrics
    
    async def record_task_queue_length(self, agent_id: str, queue_length: int) -> None:
        """
        Record task queue length.
        
        Args:
            agent_id: ID of the agent
            queue_length: Current queue length
        """
        with self._lock:
            self._task_queue_lengths[agent_id].append((datetime.now(), queue_length))
    
    async def record_task_processing_time(self, agent_id: str, processing_time: float) -> None:
        """
        Record task processing time.
        
        Args:
            agent_id: ID of the agent
            processing_time: Processing time in seconds
        """
        with self._lock:
            self._task_processing_times[agent_id].append(processing_time)
            
            # Keep only the last 1000 records
            if len(self._task_processing_times[agent_id]) > 1000:
                self._task_processing_times[agent_id] = self._task_processing_times[agent_id][-1000:]
    
    async def record_task_status(self, agent_id: str, status: str) -> None:
        """
        Record task status.
        
        Args:
            agent_id: ID of the agent
            status: Task status
        """
        with self._lock:
            self._task_status_counts[agent_id][status] += 1
    
    async def get_task_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get task metrics.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Dictionary containing task metrics
        """
        with self._lock:
            metrics = {}
            
            agent_ids = [agent_id] if agent_id else list(self._task_queue_lengths.keys())
            
            for aid in agent_ids:
                metrics[aid] = {}
                
                # Queue length metrics
                if aid in self._task_queue_lengths and self._task_queue_lengths[aid]:
                    queue_lengths = [length for _, length in self._task_queue_lengths[aid]]
                    metrics[aid]["queue_length"] = {
                        "current": queue_lengths[-1] if queue_lengths else 0,
                        "min": min(queue_lengths),
                        "max": max(queue_lengths),
                        "avg": sum(queue_lengths) / len(queue_lengths)
                    }
                
                # Processing time metrics
                if aid in self._task_processing_times and self._task_processing_times[aid]:
                    proc_times = self._task_processing_times[aid]
                    metrics[aid]["processing_time"] = {
                        "min": min(proc_times),
                        "max": max(proc_times),
                        "avg": sum(proc_times) / len(proc_times),
                        "count": len(proc_times)
                    }
                
                # Status counts
                if aid in self._task_status_counts:
                    metrics[aid]["status_counts"] = dict(self._task_status_counts[aid])
            
            return metrics
    
    # Memory Metrics
    
    async def record_memory_usage(self, agent_id: str, usage_mb: float) -> None:
        """
        Record memory usage.
        
        Args:
            agent_id: ID of the agent
            usage_mb: Memory usage in megabytes
        """
        with self._lock:
            now = datetime.now()
            self._memory_usage[agent_id].append((now, usage_mb))
            
            # Keep only the last 1000 records
            if len(self._memory_usage[agent_id]) > 1000:
                self._memory_usage[agent_id] = self._memory_usage[agent_id][-1000:]
    
    async def record_memory_hit(self, agent_id: str) -> None:
        """
        Record a memory hit.
        
        Args:
            agent_id: ID of the agent
        """
        with self._lock:
            self._memory_hits[agent_id] += 1
    
    async def record_memory_miss(self, agent_id: str) -> None:
        """
        Record a memory miss.
        
        Args:
            agent_id: ID of the agent
        """
        with self._lock:
            self._memory_misses[agent_id] += 1
    
    async def record_memory_eviction(self, agent_id: str) -> None:
        """
        Record a memory eviction.
        
        Args:
            agent_id: ID of the agent
        """
        with self._lock:
            self._memory_evictions[agent_id] += 1
    
    async def get_memory_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get memory metrics.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Dictionary containing memory metrics
        """
        with self._lock:
            metrics = {}
            
            agent_ids = [agent_id] if agent_id else list(self._memory_usage.keys())
            
            for aid in agent_ids:
                metrics[aid] = {}
                
                # Usage metrics
                if aid in self._memory_usage and self._memory_usage[aid]:
                    usage_data = self._memory_usage[aid]
                    usage_values = [usage for _, usage in usage_data]
                    metrics[aid]["usage_mb"] = {
                        "current": usage_values[-1] if usage_values else 0,
                        "min": min(usage_values),
                        "max": max(usage_values),
                        "avg": sum(usage_values) / len(usage_values)
                    }
                
                # Hit/miss metrics
                hits = self._memory_hits.get(aid, 0)
                misses = self._memory_misses.get(aid, 0)
                total = hits + misses
                
                if total > 0:
                    hit_rate = hits / total
                    metrics[aid]["hit_rate"] = hit_rate
                    metrics[aid]["total_accesses"] = total
                    metrics[aid]["hits"] = hits
                    metrics[aid]["misses"] = misses
                
                # Eviction metrics
                if aid in self._memory_evictions:
                    metrics[aid]["evictions"] = self._memory_evictions[aid]
            
            return metrics
    
    async def record_memory_operation(self, agent_id: str, operation: str, memory_type: str) -> None:
        """
        Record a memory operation.
        
        Args:
            agent_id: ID of the agent
            operation: Type of operation (store, retrieve, search, share, consolidate)
            memory_type: Type of memory
        """
        with self._lock:
            # Record as a memory hit or miss based on operation type
            if operation == "retrieve" or operation == "search":
                self._memory_hits[agent_id] += 1
            elif operation == "store":
                # For store operations, we don't count as hit/miss but could track separately
                pass
    
    # Tool Usage Metrics
    
    async def record_tool_usage(self, agent_id: str, tool_id: str) -> None:
        """
        Record tool usage.
        
        Args:
            agent_id: ID of the agent
            tool_id: ID of the tool
        """
        with self._lock:
            self._tool_usage_counts[agent_id][tool_id] += 1
        
        if _AGENT_PROMETHEUS_METRICS is not None:
            _AGENT_PROMETHEUS_METRICS.record_tool_execution(
                tool_id=tool_id,
                status="success",
            )
    
    async def record_tool_execution_time(self, tool_id: str, execution_time: float) -> None:
        """
        Record tool execution time.
        
        Args:
            tool_id: ID of the tool
            execution_time: Execution time in seconds
        """
        with self._lock:
            self._tool_execution_times[tool_id].append(execution_time)
            
            # Keep only the last 1000 records
            if len(self._tool_execution_times[tool_id]) > 1000:
                self._tool_execution_times[tool_id] = self._tool_execution_times[tool_id][-1000:]
        
        if _AGENT_PROMETHEUS_METRICS is not None:
            _AGENT_PROMETHEUS_METRICS.record_tool_execution(
                tool_id=tool_id,
                status="success",
            )
    
    async def record_tool_success(self, tool_id: str) -> None:
        """
        Record a successful tool operation.
        
        Args:
            tool_id: ID of the tool
        """
        with self._lock:
            self._tool_error_rates[tool_id]["success"] += 1
        
        if _AGENT_PROMETHEUS_METRICS is not None:
            _AGENT_PROMETHEUS_METRICS.record_tool_execution(
                tool_id=tool_id,
                status="success",
            )
    
    async def record_tool_failure(self, tool_id: str) -> None:
        """
        Record a failed tool operation.
        
        Args:
            tool_id: ID of the tool
        """
        with self._lock:
            self._tool_error_rates[tool_id]["failure"] += 1
        
        if _AGENT_PROMETHEUS_METRICS is not None:
            _AGENT_PROMETHEUS_METRICS.record_tool_execution(
                tool_id=tool_id,
                status="failure",
            )
    
    async def get_tool_usage_metrics(self, agent_id: Optional[str] = None, tool_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get tool usage metrics.
        
        Args:
            agent_id: Optional agent ID to filter by
            tool_id: Optional tool ID to filter by
            
        Returns:
            Dictionary containing tool usage metrics
        """
        with self._lock:
            metrics = {}
            
            # Filter by agent if specified
            if agent_id:
                if agent_id in self._tool_usage_counts:
                    metrics[agent_id] = dict(self._tool_usage_counts[agent_id])
            else:
                # Get all tool usage counts
                for aid, tools in self._tool_usage_counts.items():
                    metrics[aid] = dict(tools)
            
            # Add tool execution time metrics
            tool_ids = [tool_id] if tool_id else list(self._tool_execution_times.keys())
            
            for tid in tool_ids:
                if tid in self._tool_execution_times and self._tool_execution_times[tid]:
                    exec_times = self._tool_execution_times[tid]
                    metrics[tid] = metrics.get(tid, {})
                    metrics[tid]["execution_time"] = {
                        "min": min(exec_times),
                        "max": max(exec_times),
                        "avg": sum(exec_times) / len(exec_times),
                        "count": len(exec_times)
                    }
                
                if tid in self._tool_error_rates:
                    error_stats = self._tool_error_rates[tid]
                    total = error_stats["success"] + error_stats["failure"]
                    success_rate = error_stats["success"] / total if total > 0 else 0
                    metrics[tid] = metrics.get(tid, {})
                    metrics[tid]["success_rate"] = success_rate
                    metrics[tid]["total_operations"] = total
            
            return metrics
    
    # Communication Metrics
    
    async def record_message(self, sender_id: str, recipient_id: str, message_type: str) -> None:
        """
        Record a message.
        
        Args:
            sender_id: ID of the sender
            recipient_id: ID of the recipient
            message_type: Type of the message
        """
        with self._lock:
            self._message_counts[sender_id][f"sent_{message_type}"] += 1
            self._message_counts[recipient_id][f"received_{message_type}"] += 1
    
    async def record_message_latency(self, agent_id: str, latency: float) -> None:
        """
        Record message latency.
        
        Args:
            agent_id: ID of the agent
            latency: Message latency in seconds
        """
        with self._lock:
            self._message_latencies[agent_id].append(latency)
            
            # Keep only the last 1000 records
            if len(self._message_latencies[agent_id]) > 1000:
                self._message_latencies[agent_id] = self._message_latencies[agent_id][-1000:]
    
    async def record_communication_bandwidth(self, agent_id: str, bandwidth_mbps: float) -> None:
        """
        Record communication bandwidth.
        
        Args:
            agent_id: ID of the agent
            bandwidth_mbps: Bandwidth in megabits per second
        """
        with self._lock:
            now = datetime.now()
            self._communication_bandwidth[agent_id].append((now, bandwidth_mbps))
            
            # Keep only the last 1000 records
            if len(self._communication_bandwidth[agent_id]) > 1000:
                self._communication_bandwidth[agent_id] = self._communication_bandwidth[agent_id][-1000:]
    
    async def get_communication_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get communication metrics.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Dictionary containing communication metrics
        """
        with self._lock:
            metrics = {}
            
            agent_ids = [agent_id] if agent_id else list(self._message_counts.keys())
            
            for aid in agent_ids:
                metrics[aid] = {}
                
                # Message counts
                if aid in self._message_counts:
                    metrics[aid]["message_counts"] = dict(self._message_counts[aid])
                
                # Message latency
                if aid in self._message_latencies and self._message_latencies[aid]:
                    latencies = self._message_latencies[aid]
                    metrics[aid]["message_latency"] = {
                        "min": min(latencies),
                        "max": max(latencies),
                        "avg": sum(latencies) / len(latencies),
                        "count": len(latencies)
                    }
                
                # Communication bandwidth
                if aid in self._communication_bandwidth and self._communication_bandwidth[aid]:
                    bandwidth_data = self._communication_bandwidth[aid]
                    bandwidth_values = [bandwidth for _, bandwidth in bandwidth_data]
                    metrics[aid]["bandwidth_mbps"] = {
                        "current": bandwidth_values[-1] if bandwidth_values else 0,
                        "min": min(bandwidth_values),
                        "max": max(bandwidth_values),
                        "avg": sum(bandwidth_values) / len(bandwidth_values)
                    }
            
            return metrics
    
    # Error Metrics
    
    async def record_error(self, agent_id: str, error_type: str) -> None:
        """
        Record an error.
        
        Args:
            agent_id: ID of the agent
            error_type: Type of the error
        """
        with self._lock:
            self._error_counts[agent_id][error_type] += 1
    
    async def record_error_rate(self, agent_id: str, error_rate: float) -> None:
        """
        Record error rate.
        
        Args:
            agent_id: ID of the agent
            error_rate: Error rate (0.0 to 1.0)
        """
        with self._lock:
            self._error_rates[agent_id].append(error_rate)
            
            # Keep only the last 1000 records
            if len(self._error_rates[agent_id]) > 1000:
                self._error_rates[agent_id] = self._error_rates[agent_id][-1000:]
    
    async def record_error_recovery_time(self, agent_id: str, recovery_time: float) -> None:
        """
        Record error recovery time.
        
        Args:
            agent_id: ID of the agent
            recovery_time: Recovery time in seconds
        """
        with self._lock:
            self._error_recovery_times[agent_id].append(recovery_time)
            
            # Keep only the last 1000 records
            if len(self._error_recovery_times[agent_id]) > 1000:
                self._error_recovery_times[agent_id] = self._error_recovery_times[agent_id][-1000:]
    
    async def get_error_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get error metrics.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Dictionary containing error metrics
        """
        with self._lock:
            metrics = {}
            
            agent_ids = [agent_id] if agent_id else list(self._error_counts.keys())
            
            for aid in agent_ids:
                metrics[aid] = {}
                
                # Error counts
                if aid in self._error_counts:
                    metrics[aid]["error_counts"] = dict(self._error_counts[aid])
                
                # Error rates
                if aid in self._error_rates and self._error_rates[aid]:
                    rates = self._error_rates[aid]
                    metrics[aid]["error_rate"] = {
                        "min": min(rates),
                        "max": max(rates),
                        "avg": sum(rates) / len(rates),
                        "count": len(rates)
                    }
                
                # Error recovery times
                if aid in self._error_recovery_times and self._error_recovery_times[aid]:
                    recovery_times = self._error_recovery_times[aid]
                    metrics[aid]["recovery_time"] = {
                        "min": min(recovery_times),
                        "max": max(recovery_times),
                        "avg": sum(recovery_times) / len(recovery_times),
                        "count": len(recovery_times)
                    }
            
            return metrics
    
    # Session Metrics
    
    async def record_session_start(self, agent_id: str) -> None:
        """
        Record a session start.
        
        Args:
            agent_id: ID of the agent
        """
        with self._lock:
            self._session_counts[agent_id] += 1
    
    async def record_session_duration(self, agent_id: str, duration: float) -> None:
        """
        Record session duration.
        
        Args:
            agent_id: ID of the agent
            duration: Session duration in seconds
        """
        with self._lock:
            self._session_durations[agent_id].append(duration)
            
            # Keep only the last 1000 records
            if len(self._session_durations[agent_id]) > 1000:
                self._session_durations[agent_id] = self._session_durations[agent_id][-1000:]
    
    async def record_session_activity(self, agent_id: str, activity_count: int) -> None:
        """
        Record session activity.
        
        Args:
            agent_id: ID of the agent
            activity_count: Number of activities in the session
        """
        with self._lock:
            now = datetime.now()
            self._session_activity[agent_id].append((now, activity_count))
            
            # Keep only the last 1000 records
            if len(self._session_activity[agent_id]) > 1000:
                self._session_activity[agent_id] = self._session_activity[agent_id][-1000:]
    
    async def get_session_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get session metrics.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Dictionary containing session metrics
        """
        with self._lock:
            metrics = {}
            
            agent_ids = [agent_id] if agent_id else list(self._session_counts.keys())
            
            for aid in agent_ids:
                metrics[aid] = {}
                
                # Session counts
                if aid in self._session_counts:
                    metrics[aid]["session_count"] = self._session_counts[aid]
                
                # Session durations
                if aid in self._session_durations and self._session_durations[aid]:
                    durations = self._session_durations[aid]
                    metrics[aid]["session_duration"] = {
                        "min": min(durations),
                        "max": max(durations),
                        "avg": sum(durations) / len(durations),
                        "count": len(durations)
                    }
                
                # Session activity
                if aid in self._session_activity and self._session_activity[aid]:
                    activity_data = self._session_activity[aid]
                    activity_values = [activity for _, activity in activity_data]
                    metrics[aid]["session_activity"] = {
                        "current": activity_values[-1] if activity_values else 0,
                        "min": min(activity_values),
                        "max": max(activity_values),
                        "avg": sum(activity_values) / len(activity_values)
                    }
            
            return metrics
    
    # Resource Usage Metrics
    
    async def record_cpu_usage(self, agent_id: str, cpu_percent: float) -> None:
        """
        Record CPU usage.
        
        Args:
            agent_id: ID of the agent
            cpu_percent: CPU usage percentage
        """
        with self._lock:
            now = datetime.now()
            self._cpu_usage[agent_id].append((now, cpu_percent))
            
            # Keep only the last 1000 records
            if len(self._cpu_usage[agent_id]) > 1000:
                self._cpu_usage[agent_id] = self._cpu_usage[agent_id][-1000:]
    
    async def record_memory_usage_bytes(self, agent_id: str, memory_bytes: float) -> None:
        """
        Record memory usage in bytes.
        
        Args:
            agent_id: ID of the agent
            memory_bytes: Memory usage in bytes
        """
        with self._lock:
            now = datetime.now()
            self._memory_usage_bytes[agent_id].append((now, memory_bytes))
            
            # Keep only the last 1000 records
            if len(self._memory_usage_bytes[agent_id]) > 1000:
                self._memory_usage_bytes[agent_id] = self._memory_usage_bytes[agent_id][-1000:]
    
    async def record_disk_usage(self, agent_id: str, disk_bytes: float) -> None:
        """
        Record disk usage.
        
        Args:
            agent_id: ID of the agent
            disk_bytes: Disk usage in bytes
        """
        with self._lock:
            now = datetime.now()
            self._disk_usage[agent_id].append((now, disk_bytes))
            
            # Keep only the last 1000 records
            if len(self._disk_usage[agent_id]) > 1000:
                self._disk_usage[agent_id] = self._disk_usage[agent_id][-1000:]
    
    async def record_network_usage(self, agent_id: str, network_bytes: float) -> None:
        """
        Record network usage.
        
        Args:
            agent_id: ID of the agent
            network_bytes: Network usage in bytes
        """
        with self._lock:
            now = datetime.now()
            self._network_usage[agent_id].append((now, network_bytes))
            
            # Keep only the last 1000 records
            if len(self._network_usage[agent_id]) > 1000:
                self._network_usage[agent_id] = self._network_usage[agent_id][-1000:]
    
    async def get_resource_usage_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get resource usage metrics.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Dictionary containing resource usage metrics
        """
        with self._lock:
            metrics = {}
            
            agent_ids = [agent_id] if agent_id else list(self._cpu_usage.keys())
            
            for aid in agent_ids:
                metrics[aid] = {}
                
                # CPU usage
                if aid in self._cpu_usage and self._cpu_usage[aid]:
                    cpu_data = self._cpu_usage[aid]
                    cpu_values = [cpu for _, cpu in cpu_data]
                    metrics[aid]["cpu_percent"] = {
                        "current": cpu_values[-1] if cpu_values else 0,
                        "min": min(cpu_values),
                        "max": max(cpu_values),
                        "avg": sum(cpu_values) / len(cpu_values)
                    }
                
                # Memory usage
                if aid in self._memory_usage_bytes and self._memory_usage_bytes[aid]:
                    memory_data = self._memory_usage_bytes[aid]
                    memory_values = [memory for _, memory in memory_data]
                    metrics[aid]["memory_bytes"] = {
                        "current": memory_values[-1] if memory_values else 0,
                        "min": min(memory_values),
                        "max": max(memory_values),
                        "avg": sum(memory_values) / len(memory_values)
                    }
                
                # Disk usage
                if aid in self._disk_usage and self._disk_usage[aid]:
                    disk_data = self._disk_usage[aid]
                    disk_values = [disk for _, disk in disk_data]
                    metrics[aid]["disk_bytes"] = {
                        "current": disk_values[-1] if disk_values else 0,
                        "min": min(disk_values),
                        "max": max(disk_values),
                        "avg": sum(disk_values) / len(disk_values)
                    }
                
                # Network usage
                if aid in self._network_usage and self._network_usage[aid]:
                    network_data = self._network_usage[aid]
                    network_values = [network for _, network in network_data]
                    metrics[aid]["network_bytes"] = {
                        "current": network_values[-1] if network_values else 0,
                        "min": min(network_values),
                        "max": max(network_values),
                        "avg": sum(network_values) / len(network_values)
                    }
            
            return metrics
    
    # Utility Methods
    
    async def cleanup_old_metrics(self) -> None:
        """Clean up old metrics data based on retention policy."""
        with self._lock:
            now = datetime.now()
            cutoff_time = now - timedelta(hours=self._metrics_retention_hours)
            
            # Clean up agent throughput metrics
            for agent_id, data in self._agent_throughput.items():
                self._agent_throughput[agent_id] = [
                    (timestamp, value) for timestamp, value in data
                    if timestamp > cutoff_time
                ]
            
            # Clean up memory usage metrics
            for agent_id, data in self._memory_usage.items():
                self._memory_usage[agent_id] = [
                    (timestamp, value) for timestamp, value in data
                    if timestamp > cutoff_time
                ]
            
            # Clean up communication bandwidth metrics
            for agent_id, data in self._communication_bandwidth.items():
                self._communication_bandwidth[agent_id] = [
                    (timestamp, value) for timestamp, value in data
                    if timestamp > cutoff_time
                ]
            
            # Clean up CPU usage metrics
            for agent_id, data in self._cpu_usage.items():
                self._cpu_usage[agent_id] = [
                    (timestamp, value) for timestamp, value in data
                    if timestamp > cutoff_time
                ]
            
            # Clean up memory usage bytes metrics
            for agent_id, data in self._memory_usage_bytes.items():
                self._memory_usage_bytes[agent_id] = [
                    (timestamp, value) for timestamp, value in data
                    if timestamp > cutoff_time
                ]
            
            # Clean up disk usage metrics
            for agent_id, data in self._disk_usage.items():
                self._disk_usage[agent_id] = [
                    (timestamp, value) for timestamp, value in data
                    if timestamp > cutoff_time
                ]
            
            # Clean up network usage metrics
            for agent_id, data in self._network_usage.items():
                self._network_usage[agent_id] = [
                    (timestamp, value) for timestamp, value in data
                    if timestamp > cutoff_time
                ]
            
            # Clean up session activity metrics
            for agent_id, data in self._session_activity.items():
                self._session_activity[agent_id] = [
                    (timestamp, value) for timestamp, value in data
                    if timestamp > cutoff_time
                ]
            
            self._last_cleanup_time = now
            logger.info("Cleaned up old metrics data")
    
    async def should_cleanup_metrics(self) -> bool:
        """Check if metrics cleanup should be performed."""
        now = datetime.now()
        time_since_cleanup = (now - self._last_cleanup_time).total_seconds()
        return time_since_cleanup > self._metrics_cleanup_interval_hours * 3600
    
    async def get_all_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get all metrics for an agent or all agents.
        
        Args:
            agent_id: Optional agent ID to filter by
            
        Returns:
            Dictionary containing all metrics
        """
        # Check if cleanup is needed
        if await self.should_cleanup_metrics():
            await self.cleanup_old_metrics()
        
        return {
            "agent_performance": await self.get_agent_performance_metrics(agent_id),
            "task": await self.get_task_metrics(agent_id),
            "memory": await self.get_memory_metrics(agent_id),
            "tool_usage": await self.get_tool_usage_metrics(agent_id),
            "communication": await self.get_communication_metrics(agent_id),
            "error": await self.get_error_metrics(agent_id),
            "session": await self.get_session_metrics(agent_id),
            "resource_usage": await self.get_resource_usage_metrics(agent_id)
        }