"""
Performance Audit Engine for Runtime Performance Optimization.

This module provides comprehensive performance auditing capabilities including
startup time measurement, runtime analysis, service discovery, and bottleneck identification.
"""

import asyncio
import logging
import json
import time
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
from pathlib import Path
from enum import Enum
from collections import defaultdict, deque
import inspect
import sys
import gc

logger = logging.getLogger(__name__)


class ServiceType(Enum):
    """Types of services for classification."""
    ESSENTIAL = "essential"
    OPTIONAL = "optional"
    BACKGROUND = "background"
    UNKNOWN = "unknown"


class BottleneckType(Enum):
    """Types of performance bottlenecks."""
    CPU_INTENSIVE = "cpu_intensive"
    MEMORY_LEAK = "memory_leak"
    IO_BOUND = "io_bound"
    STARTUP_SLOW = "startup_slow"
    RESOURCE_CONTENTION = "resource_contention"
    BLOCKING_OPERATION = "blocking_operation"


@dataclass
class ServiceInfo:
    """Information about a discovered service."""
    name: str
    pid: Optional[int]
    service_type: ServiceType
    startup_time: Optional[float]
    memory_usage: int  # bytes
    cpu_percent: float
    io_read_bytes: int
    io_write_bytes: int
    thread_count: int
    status: str
    dependencies: List[str]
    last_accessed: Optional[datetime]
    module_path: Optional[str]


@dataclass
class StartupMetrics:
    """Metrics for service startup performance."""
    service_name: str
    start_time: float
    end_time: float
    duration: float
    memory_before: int
    memory_after: int
    memory_delta: int
    cpu_usage: float
    dependencies_loaded: List[str]
    errors: List[str]


@dataclass
class RuntimeMetrics:
    """Runtime performance metrics for a service."""
    service_name: str
    timestamp: datetime
    cpu_percent: float
    memory_usage: int
    memory_percent: float
    io_read_bytes: int
    io_write_bytes: int
    thread_count: int
    open_files: int
    network_connections: int
    response_time: Optional[float]


@dataclass
class Bottleneck:
    """Identified performance bottleneck."""
    service_name: str
    bottleneck_type: BottleneckType
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    impact_score: float  # 0-100
    recommendations: List[str]
    metrics: Dict[str, Any]
    detected_at: datetime


@dataclass
class StartupReport:
    """Comprehensive startup performance report."""
    total_startup_time: float
    services_analyzed: int
    startup_metrics: List[StartupMetrics]
    bottlenecks: List[Bottleneck]
    recommendations: List[str]
    baseline_memory: int
    peak_memory: int
    generated_at: datetime


@dataclass
class RuntimeReport:
    """Comprehensive runtime performance report."""
    analysis_duration: float
    services_monitored: int
    runtime_metrics: List[RuntimeMetrics]
    bottlenecks: List[Bottleneck]
    resource_trends: Dict[str, List[float]]
    recommendations: List[str]
    generated_at: datetime


class ServiceDiscovery:
    """Service discovery mechanism to identify running services."""
    
    def __init__(self):
        self.known_services = {}
        self.service_patterns = {
            # Common service patterns in the codebase
            'auth': ['auth', 'authentication', 'login'],
            'llm': ['llm', 'model', 'inference', 'orchestrator'],
            'database': ['db', 'database', 'postgres', 'sqlite'],
            'api': ['api', 'routes', 'fastapi', 'server'],
            'monitoring': ['monitoring', 'metrics', 'health'],
            'memory': ['memory', 'cache', 'vector'],
            'chat': ['chat', 'conversation', 'copilot'],
            'security': ['security', 'rbac', 'audit'],
            'extensions': ['extension', 'plugin', 'marketplace'],
            'automation': ['automation', 'scheduler', 'hooks']
        }
    
    async def discover_services(self) -> List[ServiceInfo]:
        """Discover all running services and their resource usage."""
        services = []
        
        # Get current process and all child processes
        current_process = psutil.Process()
        processes = [current_process] + current_process.children(recursive=True)
        
        for proc in processes:
            try:
                service_info = await self._analyze_process(proc)
                if service_info:
                    services.append(service_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # Discover Python modules/services
        python_services = await self._discover_python_services()
        services.extend(python_services)
        
        return services
    
    async def _analyze_process(self, proc: psutil.Process) -> Optional[ServiceInfo]:
        """Analyze a single process for service information."""
        try:
            proc_info = proc.as_dict([
                'pid', 'name', 'memory_info', 'cpu_percent', 
                'io_counters', 'num_threads', 'status', 'cmdline'
            ])
            
            # Determine service type based on process name and command line
            service_name = self._determine_service_name(proc_info)
            service_type = self._classify_service_type(service_name, proc_info)
            
            # Get I/O counters
            io_counters = proc_info.get('io_counters')
            io_read = io_counters.read_bytes if io_counters else 0
            io_write = io_counters.write_bytes if io_counters else 0
            
            return ServiceInfo(
                name=service_name,
                pid=proc_info['pid'],
                service_type=service_type,
                startup_time=None,  # Will be measured separately
                memory_usage=proc_info['memory_info'].rss,
                cpu_percent=proc_info['cpu_percent'],
                io_read_bytes=io_read,
                io_write_bytes=io_write,
                thread_count=proc_info['num_threads'],
                status=proc_info['status'],
                dependencies=[],  # Will be analyzed separately
                last_accessed=None,
                module_path=None
            )
            
        except Exception as e:
            logger.debug(f"Error analyzing process {proc.pid}: {e}")
            return None
    
    async def _discover_python_services(self) -> List[ServiceInfo]:
        """Discover Python modules that represent services."""
        services = []
        
        # Analyze loaded modules
        for module_name, module in sys.modules.items():
            if self._is_service_module(module_name):
                service_info = await self._analyze_python_module(module_name, module)
                if service_info:
                    services.append(service_info)
        
        return services
    
    def _is_service_module(self, module_name: str) -> bool:
        """Determine if a module represents a service."""
        if not module_name.startswith('ai_karen_engine'):
            return False
        
        # Check for service patterns
        for service_type, patterns in self.service_patterns.items():
            for pattern in patterns:
                if pattern in module_name.lower():
                    return True
        
        return False
    
    async def _analyze_python_module(self, module_name: str, module) -> Optional[ServiceInfo]:
        """Analyze a Python module for service characteristics."""
        try:
            # Get module file path
            module_path = getattr(module, '__file__', None)
            
            # Estimate memory usage (rough approximation)
            memory_usage = sys.getsizeof(module)
            for attr_name in dir(module):
                try:
                    attr = getattr(module, attr_name)
                    memory_usage += sys.getsizeof(attr)
                except:
                    continue
            
            service_type = self._classify_service_type(module_name, {})
            
            return ServiceInfo(
                name=module_name,
                pid=None,
                service_type=service_type,
                startup_time=None,
                memory_usage=memory_usage,
                cpu_percent=0.0,  # Cannot measure for modules
                io_read_bytes=0,
                io_write_bytes=0,
                thread_count=0,
                status="loaded",
                dependencies=self._get_module_dependencies(module),
                last_accessed=None,
                module_path=module_path
            )
            
        except Exception as e:
            logger.debug(f"Error analyzing module {module_name}: {e}")
            return None
    
    def _determine_service_name(self, proc_info: Dict) -> str:
        """Determine service name from process information."""
        name = proc_info.get('name', 'unknown')
        cmdline = proc_info.get('cmdline', [])
        
        # Look for Python scripts in command line
        if cmdline:
            for arg in cmdline:
                if arg.endswith('.py'):
                    return Path(arg).stem
        
        return name
    
    def _classify_service_type(self, service_name: str, proc_info: Dict) -> ServiceType:
        """Classify service type based on name and characteristics."""
        service_name_lower = service_name.lower()
        
        # Essential services
        essential_patterns = ['auth', 'server', 'main', 'core', 'api']
        if any(pattern in service_name_lower for pattern in essential_patterns):
            return ServiceType.ESSENTIAL
        
        # Background services
        background_patterns = ['monitor', 'scheduler', 'cleanup', 'backup', 'log']
        if any(pattern in service_name_lower for pattern in background_patterns):
            return ServiceType.BACKGROUND
        
        # Optional services
        optional_patterns = ['plugin', 'extension', 'analytics', 'copilot']
        if any(pattern in service_name_lower for pattern in optional_patterns):
            return ServiceType.OPTIONAL
        
        return ServiceType.UNKNOWN
    
    def _get_module_dependencies(self, module) -> List[str]:
        """Get dependencies for a Python module."""
        dependencies = []
        
        try:
            # Look for common dependency attributes
            if hasattr(module, '__dependencies__'):
                dependencies.extend(module.__dependencies__)
            
            # Analyze imports (basic analysis)
            if hasattr(module, '__file__') and module.__file__:
                # This is a simplified approach - in practice, you'd use AST parsing
                pass
                
        except Exception as e:
            logger.debug(f"Error getting dependencies for module: {e}")
        
        return dependencies


class StartupTimeTracker:
    """Tracks startup time for services and components."""
    
    def __init__(self):
        self.startup_times = {}
        self.active_measurements = {}
        self.startup_order = []
    
    def start_measurement(self, service_name: str) -> None:
        """Start measuring startup time for a service."""
        start_time = time.time()
        memory_before = psutil.Process().memory_info().rss
        
        self.active_measurements[service_name] = {
            'start_time': start_time,
            'memory_before': memory_before,
            'dependencies_loaded': []
        }
        
        logger.debug(f"Started measuring startup time for {service_name}")
    
    def end_measurement(self, service_name: str, errors: Optional[List[str]] = None) -> Optional[StartupMetrics]:
        """End measuring startup time for a service."""
        end_time = time.time()
        memory_after = psutil.Process().memory_info().rss
        
        if service_name not in self.active_measurements:
            logger.warning(f"No active measurement found for {service_name}")
            return None
        
        measurement = self.active_measurements.pop(service_name)
        start_time = measurement['start_time']
        memory_before = measurement['memory_before']
        
        duration = end_time - start_time
        memory_delta = memory_after - memory_before
        
        # Estimate CPU usage during startup (rough approximation)
        cpu_usage = psutil.Process().cpu_percent()
        
        metrics = StartupMetrics(
            service_name=service_name,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            memory_before=memory_before,
            memory_after=memory_after,
            memory_delta=memory_delta,
            cpu_usage=cpu_usage,
            dependencies_loaded=measurement['dependencies_loaded'],
            errors=errors or []
        )
        
        self.startup_times[service_name] = metrics
        self.startup_order.append(service_name)
        
        logger.info(f"Service {service_name} startup completed in {duration:.2f}s")
        return metrics
    
    def add_dependency_loaded(self, service_name: str, dependency: str) -> None:
        """Record that a dependency was loaded during startup."""
        if service_name in self.active_measurements:
            self.active_measurements[service_name]['dependencies_loaded'].append(dependency)
    
    def get_startup_summary(self) -> Dict[str, Any]:
        """Get summary of all startup measurements."""
        if not self.startup_times:
            return {}
        
        total_time = sum(metrics.duration for metrics in self.startup_times.values())
        slowest_services = sorted(
            self.startup_times.items(),
            key=lambda x: x[1].duration,
            reverse=True
        )[:5]
        
        total_memory_delta = sum(metrics.memory_delta for metrics in self.startup_times.values())
        
        return {
            'total_startup_time': total_time,
            'services_count': len(self.startup_times),
            'slowest_services': [(name, metrics.duration) for name, metrics in slowest_services],
            'total_memory_delta': total_memory_delta,
            'startup_order': self.startup_order
        }


class ResourceUsageTracker:
    """Tracks resource usage for services over time."""
    
    def __init__(self, history_size: int = 1000):
        self.history_size = history_size
        self.metrics_history = defaultdict(lambda: deque(maxlen=history_size))
        self.monitoring_active = False
        self.monitor_thread = None
        self.monitor_interval = 5.0  # seconds
    
    def start_monitoring(self, services: List[ServiceInfo]) -> None:
        """Start continuous monitoring of resource usage."""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(services,),
            daemon=True
        )
        self.monitor_thread.start()
        logger.info("Started resource usage monitoring")
    
    def stop_monitoring(self) -> None:
        """Stop continuous monitoring."""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
        logger.info("Stopped resource usage monitoring")
    
    def _monitor_loop(self, services: List[ServiceInfo]) -> None:
        """Main monitoring loop."""
        while self.monitoring_active:
            try:
                for service in services:
                    metrics = self._collect_service_metrics(service)
                    if metrics:
                        self.metrics_history[service.name].append(metrics)
                
                time.sleep(self.monitor_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.monitor_interval)
    
    def _collect_service_metrics(self, service: ServiceInfo) -> Optional[RuntimeMetrics]:
        """Collect current metrics for a service."""
        try:
            if service.pid:
                # Process-based service
                proc = psutil.Process(service.pid)
                proc_info = proc.as_dict([
                    'memory_info', 'memory_percent', 'cpu_percent',
                    'io_counters', 'num_threads', 'num_fds', 'connections'
                ])
                
                io_counters = proc_info.get('io_counters')
                io_read = io_counters.read_bytes if io_counters else 0
                io_write = io_counters.write_bytes if io_counters else 0
                
                return RuntimeMetrics(
                    service_name=service.name,
                    timestamp=datetime.now(),
                    cpu_percent=proc_info['cpu_percent'],
                    memory_usage=proc_info['memory_info'].rss,
                    memory_percent=proc_info['memory_percent'],
                    io_read_bytes=io_read,
                    io_write_bytes=io_write,
                    thread_count=proc_info['num_threads'],
                    open_files=proc_info.get('num_fds', 0),
                    network_connections=len(proc_info.get('connections', [])),
                    response_time=None  # Would need specific measurement
                )
            else:
                # Module-based service - limited metrics
                return RuntimeMetrics(
                    service_name=service.name,
                    timestamp=datetime.now(),
                    cpu_percent=0.0,
                    memory_usage=service.memory_usage,
                    memory_percent=0.0,
                    io_read_bytes=0,
                    io_write_bytes=0,
                    thread_count=0,
                    open_files=0,
                    network_connections=0,
                    response_time=None
                )
                
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        except Exception as e:
            logger.debug(f"Error collecting metrics for {service.name}: {e}")
            return None
    
    def get_service_trends(self, service_name: str, duration_minutes: int = 60) -> Dict[str, List[float]]:
        """Get resource usage trends for a service."""
        if service_name not in self.metrics_history:
            return {}
        
        cutoff_time = datetime.now() - timedelta(minutes=duration_minutes)
        recent_metrics = [
            m for m in self.metrics_history[service_name]
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_metrics:
            return {}
        
        return {
            'cpu_percent': [m.cpu_percent for m in recent_metrics],
            'memory_usage': [m.memory_usage for m in recent_metrics],
            'memory_percent': [m.memory_percent for m in recent_metrics],
            'io_read_bytes': [m.io_read_bytes for m in recent_metrics],
            'io_write_bytes': [m.io_write_bytes for m in recent_metrics],
            'thread_count': [m.thread_count for m in recent_metrics],
            'timestamps': [m.timestamp.isoformat() for m in recent_metrics]
        }


class BottleneckAnalyzer:
    """Analyzes performance data to identify bottlenecks."""
    
    def __init__(self):
        self.thresholds = {
            'cpu_high': 80.0,  # CPU usage %
            'memory_high': 1024 * 1024 * 1024,  # 1GB
            'startup_slow': 10.0,  # seconds
            'io_high': 100 * 1024 * 1024,  # 100MB
            'thread_high': 50,
            'memory_growth_rate': 0.1  # 10% growth per minute
        }
    
    def analyze_startup_bottlenecks(self, startup_metrics: List[StartupMetrics]) -> List[Bottleneck]:
        """Analyze startup metrics to identify bottlenecks."""
        bottlenecks = []
        
        for metrics in startup_metrics:
            # Slow startup detection
            if metrics.duration > self.thresholds['startup_slow']:
                severity = self._calculate_severity(
                    metrics.duration, self.thresholds['startup_slow'], 30.0
                )
                
                bottlenecks.append(Bottleneck(
                    service_name=metrics.service_name,
                    bottleneck_type=BottleneckType.STARTUP_SLOW,
                    severity=severity,
                    description=f"Service takes {metrics.duration:.2f}s to start (threshold: {self.thresholds['startup_slow']}s)",
                    impact_score=min(100, (metrics.duration / self.thresholds['startup_slow']) * 50),
                    recommendations=[
                        "Consider lazy loading for non-essential components",
                        "Optimize initialization code",
                        "Move heavy operations to background tasks",
                        "Cache expensive computations"
                    ],
                    metrics={
                        'startup_duration': metrics.duration,
                        'memory_delta': metrics.memory_delta,
                        'dependencies_count': len(metrics.dependencies_loaded)
                    },
                    detected_at=datetime.now()
                ))
            
            # Memory usage during startup
            if metrics.memory_delta > self.thresholds['memory_high']:
                severity = self._calculate_severity(
                    metrics.memory_delta, self.thresholds['memory_high'], 
                    self.thresholds['memory_high'] * 3
                )
                
                bottlenecks.append(Bottleneck(
                    service_name=metrics.service_name,
                    bottleneck_type=BottleneckType.MEMORY_LEAK,
                    severity=severity,
                    description=f"Service uses {metrics.memory_delta / (1024*1024):.1f}MB during startup",
                    impact_score=min(100, (metrics.memory_delta / self.thresholds['memory_high']) * 40),
                    recommendations=[
                        "Review memory allocation patterns",
                        "Implement object pooling",
                        "Use lazy initialization",
                        "Profile memory usage with memory_profiler"
                    ],
                    metrics={
                        'memory_delta': metrics.memory_delta,
                        'memory_before': metrics.memory_before,
                        'memory_after': metrics.memory_after
                    },
                    detected_at=datetime.now()
                ))
        
        return bottlenecks
    
    def analyze_runtime_bottlenecks(self, runtime_metrics: List[RuntimeMetrics]) -> List[Bottleneck]:
        """Analyze runtime metrics to identify bottlenecks."""
        bottlenecks = []
        
        # Group metrics by service
        service_metrics = defaultdict(list)
        for metrics in runtime_metrics:
            service_metrics[metrics.service_name].append(metrics)
        
        for service_name, metrics_list in service_metrics.items():
            if not metrics_list:
                continue
            
            # Analyze CPU usage
            avg_cpu = sum(m.cpu_percent for m in metrics_list) / len(metrics_list)
            max_cpu = max(m.cpu_percent for m in metrics_list)
            
            if avg_cpu > self.thresholds['cpu_high']:
                severity = self._calculate_severity(avg_cpu, self.thresholds['cpu_high'], 100.0)
                
                bottlenecks.append(Bottleneck(
                    service_name=service_name,
                    bottleneck_type=BottleneckType.CPU_INTENSIVE,
                    severity=severity,
                    description=f"High CPU usage: {avg_cpu:.1f}% average, {max_cpu:.1f}% peak",
                    impact_score=min(100, (avg_cpu / self.thresholds['cpu_high']) * 60),
                    recommendations=[
                        "Profile CPU usage to identify hot spots",
                        "Implement async/await for I/O operations",
                        "Use multiprocessing for CPU-bound tasks",
                        "Optimize algorithms and data structures",
                        "Consider caching frequently computed results"
                    ],
                    metrics={
                        'avg_cpu_percent': avg_cpu,
                        'max_cpu_percent': max_cpu,
                        'samples_count': len(metrics_list)
                    },
                    detected_at=datetime.now()
                ))
            
            # Analyze memory usage
            avg_memory = sum(m.memory_usage for m in metrics_list) / len(metrics_list)
            max_memory = max(m.memory_usage for m in metrics_list)
            
            if avg_memory > self.thresholds['memory_high']:
                severity = self._calculate_severity(
                    avg_memory, self.thresholds['memory_high'], 
                    self.thresholds['memory_high'] * 3
                )
                
                bottlenecks.append(Bottleneck(
                    service_name=service_name,
                    bottleneck_type=BottleneckType.MEMORY_LEAK,
                    severity=severity,
                    description=f"High memory usage: {avg_memory/(1024*1024):.1f}MB average, {max_memory/(1024*1024):.1f}MB peak",
                    impact_score=min(100, (avg_memory / self.thresholds['memory_high']) * 50),
                    recommendations=[
                        "Profile memory usage to identify leaks",
                        "Implement proper cleanup in destructors",
                        "Use weak references where appropriate",
                        "Optimize data structures",
                        "Implement memory limits and monitoring"
                    ],
                    metrics={
                        'avg_memory_usage': avg_memory,
                        'max_memory_usage': max_memory,
                        'samples_count': len(metrics_list)
                    },
                    detected_at=datetime.now()
                ))
            
            # Analyze I/O usage
            total_io = sum(m.io_read_bytes + m.io_write_bytes for m in metrics_list)
            if total_io > self.thresholds['io_high'] * len(metrics_list):
                severity = self._calculate_severity(
                    total_io, self.thresholds['io_high'] * len(metrics_list),
                    self.thresholds['io_high'] * len(metrics_list) * 3
                )
                
                bottlenecks.append(Bottleneck(
                    service_name=service_name,
                    bottleneck_type=BottleneckType.IO_BOUND,
                    severity=severity,
                    description=f"High I/O usage: {total_io/(1024*1024):.1f}MB total",
                    impact_score=min(100, (total_io / (self.thresholds['io_high'] * len(metrics_list))) * 40),
                    recommendations=[
                        "Implement I/O caching",
                        "Use async I/O operations",
                        "Batch I/O operations",
                        "Optimize database queries",
                        "Use connection pooling"
                    ],
                    metrics={
                        'total_io_bytes': total_io,
                        'avg_read_bytes': sum(m.io_read_bytes for m in metrics_list) / len(metrics_list),
                        'avg_write_bytes': sum(m.io_write_bytes for m in metrics_list) / len(metrics_list)
                    },
                    detected_at=datetime.now()
                ))
        
        return bottlenecks
    
    def _calculate_severity(self, value: float, threshold: float, critical_threshold: float) -> str:
        """Calculate severity level based on value and thresholds."""
        if value >= critical_threshold:
            return "CRITICAL"
        elif value >= threshold * 1.5:
            return "HIGH"
        elif value >= threshold * 1.2:
            return "MEDIUM"
        else:
            return "LOW"


class PerformanceAuditor:
    """Main performance audit engine."""
    
    def __init__(self, audit_log_path: Optional[Path] = None):
        self.audit_log_path = audit_log_path or Path("logs/performance_audit.log")
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.service_discovery = ServiceDiscovery()
        self.startup_tracker = StartupTimeTracker()
        self.resource_tracker = ResourceUsageTracker()
        self.bottleneck_analyzer = BottleneckAnalyzer()
        
        self.baseline_metrics = None
        self.audit_history = []
        
        logger.info(f"Performance auditor initialized: {self.audit_log_path}")
    
    async def initialize(self) -> None:
        """Initialize the performance auditor."""
        # Ensure audit log directory exists
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize baseline metrics if needed
        if self.baseline_metrics is None:
            self.baseline_metrics = {
                'startup_time': 0.0,
                'memory_usage': 0,
                'cpu_usage': 0.0
            }
        
        logger.info("Performance auditor initialization complete")
    
    async def audit_startup_performance(self) -> StartupReport:
        """Audit startup performance and generate comprehensive report."""
        logger.info("Starting startup performance audit")
        
        # Record baseline memory
        baseline_memory = psutil.Process().memory_info().rss
        
        # Discover services
        services = await self.service_discovery.discover_services()
        logger.info(f"Discovered {len(services)} services")
        
        # Get startup metrics
        startup_metrics = list(self.startup_tracker.startup_times.values())
        
        # Analyze bottlenecks
        bottlenecks = self.bottleneck_analyzer.analyze_startup_bottlenecks(startup_metrics)
        
        # Calculate total startup time
        total_startup_time = sum(metrics.duration for metrics in startup_metrics)
        
        # Get current memory usage
        current_memory = psutil.Process().memory_info().rss
        
        # Generate recommendations
        recommendations = self._generate_startup_recommendations(startup_metrics, bottlenecks)
        
        report = StartupReport(
            total_startup_time=total_startup_time,
            services_analyzed=len(services),
            startup_metrics=startup_metrics,
            bottlenecks=bottlenecks,
            recommendations=recommendations,
            baseline_memory=baseline_memory,
            peak_memory=current_memory,
            generated_at=datetime.now()
        )
        
        # Save report
        await self._save_report(report, "startup")
        
        logger.info(f"Startup audit completed: {total_startup_time:.2f}s total, {len(bottlenecks)} bottlenecks found")
        return report
    
    async def audit_runtime_performance(self, duration_minutes: int = 10) -> RuntimeReport:
        """Audit runtime performance over a specified duration."""
        logger.info(f"Starting runtime performance audit for {duration_minutes} minutes")
        
        start_time = time.time()
        
        # Discover services
        services = await self.service_discovery.discover_services()
        
        # Start monitoring
        self.resource_tracker.start_monitoring(services)
        
        # Wait for monitoring period
        await asyncio.sleep(duration_minutes * 60)
        
        # Stop monitoring
        self.resource_tracker.stop_monitoring()
        
        # Collect all runtime metrics
        all_metrics = []
        for service in services:
            service_metrics = list(self.resource_tracker.metrics_history[service.name])
            all_metrics.extend(service_metrics)
        
        # Analyze bottlenecks
        bottlenecks = self.bottleneck_analyzer.analyze_runtime_bottlenecks(all_metrics)
        
        # Generate resource trends
        resource_trends = {}
        for service in services:
            trends = self.resource_tracker.get_service_trends(service.name, duration_minutes)
            if trends:
                resource_trends[service.name] = trends
        
        # Generate recommendations
        recommendations = self._generate_runtime_recommendations(all_metrics, bottlenecks)
        
        analysis_duration = time.time() - start_time
        
        report = RuntimeReport(
            analysis_duration=analysis_duration,
            services_monitored=len(services),
            runtime_metrics=all_metrics,
            bottlenecks=bottlenecks,
            resource_trends=resource_trends,
            recommendations=recommendations,
            generated_at=datetime.now()
        )
        
        # Save report
        await self._save_report(report, "runtime")
        
        logger.info(f"Runtime audit completed: {len(all_metrics)} metrics collected, {len(bottlenecks)} bottlenecks found")
        return report
    
    async def identify_bottlenecks(self) -> List[Bottleneck]:
        """Identify current performance bottlenecks."""
        logger.info("Identifying performance bottlenecks")
        
        bottlenecks = []
        
        # Analyze startup bottlenecks
        startup_metrics = list(self.startup_tracker.startup_times.values())
        if startup_metrics:
            startup_bottlenecks = self.bottleneck_analyzer.analyze_startup_bottlenecks(startup_metrics)
            bottlenecks.extend(startup_bottlenecks)
        
        # Analyze runtime bottlenecks from recent metrics
        recent_metrics = []
        for service_metrics in self.resource_tracker.metrics_history.values():
            recent_metrics.extend(list(service_metrics)[-10:])  # Last 10 measurements
        
        if recent_metrics:
            runtime_bottlenecks = self.bottleneck_analyzer.analyze_runtime_bottlenecks(recent_metrics)
            bottlenecks.extend(runtime_bottlenecks)
        
        # Sort by impact score
        bottlenecks.sort(key=lambda b: b.impact_score, reverse=True)
        
        logger.info(f"Identified {len(bottlenecks)} bottlenecks")
        return bottlenecks
    
    async def generate_optimization_recommendations(self) -> List[str]:
        """Generate actionable optimization recommendations."""
        logger.info("Generating optimization recommendations")
        
        recommendations = []
        
        # Get current bottlenecks
        bottlenecks = await self.identify_bottlenecks()
        
        # Service-specific recommendations
        service_recommendations = defaultdict(set)
        for bottleneck in bottlenecks:
            service_recommendations[bottleneck.service_name].update(bottleneck.recommendations)
        
        # General recommendations based on analysis
        if any(b.bottleneck_type == BottleneckType.STARTUP_SLOW for b in bottlenecks):
            recommendations.extend([
                "Implement lazy loading for non-essential services",
                "Create service classification system (essential/optional/background)",
                "Use async initialization patterns",
                "Implement service dependency management"
            ])
        
        if any(b.bottleneck_type == BottleneckType.CPU_INTENSIVE for b in bottlenecks):
            recommendations.extend([
                "Implement async task orchestrator for parallel processing",
                "Move CPU-intensive operations to background workers",
                "Consider GPU acceleration for compute-heavy tasks",
                "Implement CPU usage monitoring and throttling"
            ])
        
        if any(b.bottleneck_type == BottleneckType.MEMORY_LEAK for b in bottlenecks):
            recommendations.extend([
                "Implement automatic memory cleanup and garbage collection",
                "Add memory usage monitoring and alerting",
                "Use memory-efficient data structures",
                "Implement memory limits per service"
            ])
        
        if any(b.bottleneck_type == BottleneckType.IO_BOUND for b in bottlenecks):
            recommendations.extend([
                "Implement async I/O operations",
                "Add connection pooling and caching",
                "Batch I/O operations where possible",
                "Implement I/O monitoring and optimization"
            ])
        
        # Add service-specific recommendations
        for service_name, service_recs in service_recommendations.items():
            recommendations.append(f"For {service_name}: {', '.join(list(service_recs)[:3])}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_recommendations = []
        for rec in recommendations:
            if rec not in seen:
                seen.add(rec)
                unique_recommendations.append(rec)
        
        logger.info(f"Generated {len(unique_recommendations)} optimization recommendations")
        return unique_recommendations
    
    def _generate_startup_recommendations(self, startup_metrics: List[StartupMetrics], bottlenecks: List[Bottleneck]) -> List[str]:
        """Generate startup-specific recommendations."""
        recommendations = []
        
        if not startup_metrics:
            return ["No startup metrics available - implement startup time tracking"]
        
        # Analyze startup patterns
        total_time = sum(m.duration for m in startup_metrics)
        avg_time = total_time / len(startup_metrics)
        
        if total_time > 30.0:  # More than 30 seconds total
            recommendations.append("Total startup time is excessive - implement service prioritization")
        
        if avg_time > 5.0:  # Average service takes more than 5 seconds
            recommendations.append("Average service startup time is high - optimize initialization code")
        
        # Memory usage recommendations
        total_memory = sum(m.memory_delta for m in startup_metrics)
        if total_memory > 512 * 1024 * 1024:  # More than 512MB
            recommendations.append("High memory usage during startup - implement memory-efficient initialization")
        
        # Dependency recommendations
        max_deps = max((len(m.dependencies_loaded) for m in startup_metrics), default=0)
        if max_deps > 20:
            recommendations.append("High dependency count detected - consider dependency injection and lazy loading")
        
        return recommendations
    
    def _generate_runtime_recommendations(self, runtime_metrics: List[RuntimeMetrics], bottlenecks: List[Bottleneck]) -> List[str]:
        """Generate runtime-specific recommendations."""
        recommendations = []
        
        if not runtime_metrics:
            return ["No runtime metrics available - implement runtime monitoring"]
        
        # Analyze resource usage patterns
        avg_cpu = sum(m.cpu_percent for m in runtime_metrics) / len(runtime_metrics)
        avg_memory = sum(m.memory_usage for m in runtime_metrics) / len(runtime_metrics)
        
        if avg_cpu > 50.0:
            recommendations.append("High average CPU usage - implement CPU optimization strategies")
        
        if avg_memory > 1024 * 1024 * 1024:  # 1GB
            recommendations.append("High memory usage - implement memory management and cleanup")
        
        # Thread usage analysis
        avg_threads = sum(m.thread_count for m in runtime_metrics) / len(runtime_metrics)
        if avg_threads > 20:
            recommendations.append("High thread count - optimize threading and use async patterns")
        
        return recommendations
    
    async def _save_report(self, report, report_type: str) -> None:
        """Save audit report to file."""
        try:
            report_data = {
                'type': report_type,
                'timestamp': datetime.now().isoformat(),
                'report': asdict(report)
            }
            
            with open(self.audit_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(report_data, default=str) + '\n')
            
            logger.debug(f"Saved {report_type} audit report")
            
        except Exception as e:
            logger.error(f"Failed to save audit report: {e}")


# Global auditor instance
_performance_auditor: Optional[PerformanceAuditor] = None


def get_performance_auditor() -> PerformanceAuditor:
    """Get the global performance auditor instance."""
    global _performance_auditor
    if _performance_auditor is None:
        _performance_auditor = PerformanceAuditor()
    return _performance_auditor


# Context manager for startup time tracking
class StartupTimeContext:
    """Context manager for tracking service startup time."""
    
    def __init__(self, service_name: str, auditor: Optional[PerformanceAuditor] = None):
        self.service_name = service_name
        self.auditor = auditor or get_performance_auditor()
        self.errors = []
    
    def __enter__(self):
        self.auditor.startup_tracker.start_measurement(self.service_name)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.errors.append(f"{exc_type.__name__}: {exc_val}")
        
        self.auditor.startup_tracker.end_measurement(self.service_name, self.errors)
    
    def add_dependency(self, dependency: str):
        """Add a dependency that was loaded during startup."""
        self.auditor.startup_tracker.add_dependency_loaded(self.service_name, dependency)