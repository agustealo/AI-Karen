"""Plugin Execution Service with Sandboxing.

This service provides secure plugin execution with input/output validation,
resource management, and timeout controls.
"""

import asyncio
import builtins
import inspect
import logging
import re
import resource
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
import uuid
import importlib.util
from concurrent.futures import (
    Future as ConcurrentFuture,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    TimeoutError,
)

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field

from ai_karen_engine.extensions.platform.core.manifest import ExtensionContext, ExtensionManifest
from ai_karen_engine.services.plugin_discovery import PluginRegistry, get_plugin_registry

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """Plugin execution mode."""
    DIRECT = "direct"
    THREAD = "thread"
    PROCESS = "process"
    SANDBOX = "sandbox"


class ExecutionStatus(str, Enum):
    """Plugin execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ResourceLimits:
    """Resource limits for plugin execution."""
    max_memory_mb: int = 128
    max_cpu_time_seconds: int = 30
    max_wall_time_seconds: int = 60
    max_file_descriptors: int = 64
    max_processes: int = 1
    max_threads: int = 4
    max_output_size_kb: int = 1024


@dataclass
class SecurityPolicy:
    """Security policy for plugin execution."""
    allow_network: bool = False
    allow_file_system: bool = False
    allow_subprocess: bool = False
    allow_imports: List[str] = field(default_factory=lambda: [
        "json", "re", "datetime", "math", "random", "uuid", "hashlib",
        "base64", "urllib.parse", "pathlib"
    ])
    blocked_imports: List[str] = field(default_factory=lambda: [
        "os", "sys", "subprocess", "socket", "urllib.request", 
        "requests", "http", "ftplib", "smtplib"
    ])
    allowed_builtins: List[str] = field(default_factory=lambda: [
        "len", "str", "int", "float", "bool", "list", "dict", "tuple",
        "set", "range", "enumerate", "zip", "map", "filter", "sorted",
        "min", "max", "sum", "abs", "round", "print"
    ])


@dataclass
class PluginExecutionContext:
    """Immutable execution context for plugin runtime.

    Security fields are resolved from manifest, RuntimePolicy, and trusted
    runtime config. Callers cannot mutate security fields after policy evaluation.
    """

    user_id: str
    tenant_id: str
    session_id: str
    conversation_id: str
    request_id: str
    correlation_id: str

    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)

    plugin_id: str = ""
    plugin_version: str = ""
    action: str = ""

    policy_decision_id: str = ""

    allowed_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)

    resource_scope: Dict[str, Any] = field(default_factory=dict)
    resource_limits: Optional[Dict[str, Any]] = None
    security_policy: Optional[Dict[str, Any]] = None

    provider_constraints: Optional[Dict[str, Any]] = None


class ExecutionRequest(BaseModel):
    """Plugin execution request."""

    model_config = ConfigDict(extra="forbid")

    plugin_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = ExecutionMode.SANDBOX
    timeout_seconds: int = 30
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    policy_decision_id: Optional[str] = None
    allowed_capabilities: List[str] = Field(default_factory=list)
    forbidden_capabilities: List[str] = Field(default_factory=list)


@dataclass
class ExecutionResult:
    """Plugin execution result."""
    request_id: str
    plugin_name: str
    status: ExecutionStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    memory_used_mb: float = 0.0
    output_size_bytes: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    plugin_id: str = ""
    plugin_version: str = ""
    user_id: str = ""
    tenant_id: str = ""
    correlation_id: str = ""
    policy_decision_id: str = ""
    requested_capabilities: List[str] = field(default_factory=list)
    granted_capabilities: List[str] = field(default_factory=list)
    error_code: Optional[str] = None


@dataclass
class ExecutionHandle:
    """Track the asynchronous handle backing a plugin execution."""

    request_id: str
    mode: ExecutionMode
    future: asyncio.Future
    executor_future: Optional[ConcurrentFuture] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def cancel(self) -> bool:
        """Attempt to cancel the underlying execution future."""

        cancelled = False

        if not self.future.done():
            cancelled = self.future.cancel()

        if self.executor_future and not self.executor_future.done():
            cancelled = self.executor_future.cancel() or cancelled

        return cancelled


class PluginSandbox:
    """Secure plugin execution sandbox."""

    def __init__(self, resource_limits: ResourceLimits, security_policy: SecurityPolicy):
        self.resource_limits = resource_limits
        self.security_policy = security_policy
        self.original_modules = {}
        self.restricted_builtins: Dict[str, Any] = {}
    
    def __enter__(self):
        """Enter sandbox context."""
        self._setup_resource_limits()
        self._setup_import_restrictions()
        self._setup_builtin_restrictions()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit sandbox context."""
        self._restore_environment()
    
    def _setup_resource_limits(self):
        """Set up resource limits."""
        try:
            # Memory limit
            if hasattr(resource, 'RLIMIT_AS'):
                memory_limit = self.resource_limits.max_memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
            
            # CPU time limit
            if hasattr(resource, 'RLIMIT_CPU'):
                cpu_limit = self.resource_limits.max_cpu_time_seconds
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
            
            # File descriptor limit
            if hasattr(resource, 'RLIMIT_NOFILE'):
                fd_limit = self.resource_limits.max_file_descriptors
                resource.setrlimit(resource.RLIMIT_NOFILE, (fd_limit, fd_limit))
            
            # Process limit
            if hasattr(resource, 'RLIMIT_NPROC'):
                proc_limit = self.resource_limits.max_processes
                resource.setrlimit(resource.RLIMIT_NPROC, (proc_limit, proc_limit))
                
        except Exception as e:
            logger.warning(f"Failed to set resource limits: {e}")
    
    def _setup_import_restrictions(self):
        """Set up import restrictions."""

        def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
            """Restricted import function."""
            if name in self.security_policy.blocked_imports:
                raise ImportError(f"Import of '{name}' is not allowed in sandbox")

            if self.security_policy.allow_imports:
                allowed = False
                for allowed_pattern in self.security_policy.allow_imports:
                    if name.startswith(allowed_pattern):
                        allowed = True
                        break

                if not allowed:
                    raise ImportError(f"Import of '{name}' is not allowed in sandbox")

            return builtins.__import__(name, globals, locals, fromlist, level)

        self.restricted_builtins["__import__"] = restricted_import
    
    def _setup_builtin_restrictions(self):
        """Set up builtin function restrictions."""
        # Copy selected builtins into a local dictionary
        allowed = {}
        for name in self.security_policy.allowed_builtins:
            if hasattr(builtins, name):
                allowed[name] = getattr(builtins, name)

        if not self.security_policy.allow_file_system:
            allowed["open"] = self._restricted_open

        # Merge with import restrictions
        self.restricted_builtins.update(allowed)
    
    def _restricted_open(self, *args, **kwargs):
        """Restricted open function."""
        raise PermissionError("File system access is not allowed in sandbox")

    @staticmethod
    def _get_callable_globals(func: Callable) -> Dict[str, Any]:
        """Resolve globals for plain functions and bound methods."""
        if hasattr(func, "__globals__"):
            return getattr(func, "__globals__")  # type: ignore[return-value]
        bound = getattr(func, "__func__", None)
        if bound is not None and hasattr(bound, "__globals__"):
            return getattr(bound, "__globals__")
        return {}

    def _restore_environment(self):
        """Restore original environment."""
        self.restricted_builtins.clear()

    def run(self, func: Callable, *args, **kwargs):
        """Execute a function with restricted builtins."""
        func_globals = self._get_callable_globals(func)
        original_builtins = func_globals.get("__builtins__", builtins.__dict__)
        func_globals["__builtins__"] = self.restricted_builtins
        try:
            exec_globals = {"func": func, "args": args, "kwargs": kwargs, "__builtins__": self.restricted_builtins}
            exec("result = func(*args, **kwargs)", exec_globals)
            return exec_globals["result"]
        finally:
            func_globals["__builtins__"] = original_builtins

    async def run_async(self, func: Callable, *args, **kwargs):
        """Execute an async function with restricted builtins."""
        func_globals = self._get_callable_globals(func)
        original_builtins = func_globals.get("__builtins__", builtins.__dict__)
        func_globals["__builtins__"] = self.restricted_builtins
        try:
            exec_globals = {"__builtins__": self.restricted_builtins}
            exec(
                "async def _runner(func, args, kwargs):\n    return await func(*args, **kwargs)",
                exec_globals,
            )
            return await exec_globals["_runner"](func, args, kwargs)
        finally:
            func_globals["__builtins__"] = original_builtins


class PluginExecutionEngine:
    """
    Plugin execution engine with sandboxing and resource management.
    """
    
    def __init__(self, registry: Optional[PluginRegistry] = None):
        """Initialize plugin execution engine."""
        self.registry = registry or get_plugin_registry()

        # Execution settings
        self.default_resource_limits = ResourceLimits()
        self.default_security_policy = SecurityPolicy()
        self.default_timeout = 30

        # Execution tracking
        self.active_executions: Dict[str, ExecutionResult] = {}
        self.execution_handles: Dict[str, ExecutionHandle] = {}
        self.execution_history: List[ExecutionResult] = []
        self.max_history_size = 1000

        # Thread/process pools
        self.thread_pool = ThreadPoolExecutor(max_workers=4)
        self.process_pool = ProcessPoolExecutor(max_workers=2)

        # Metrics
        self.metrics = {
            "executions_total": 0,
            "executions_successful": 0,
            "executions_failed": 0,
            "executions_timeout": 0,
            "executions_cancelled": 0,
            "average_execution_time": 0.0,
            "total_execution_time": 0.0
        }

    def _resolve_resource_limits(self, manifest: Any) -> ResourceLimits:
        """Resolve resource limits from manifest, falling back to defaults."""
        resources = getattr(manifest, "resources", None)
        if resources is None:
            return ResourceLimits()

        if hasattr(resources, "model_dump"):
            data = resources.model_dump()
        elif isinstance(resources, dict):
            data = resources
        else:
            data = {}

        return ResourceLimits(
            max_memory_mb=data.get("max_memory_mb", 128),
            max_cpu_time_seconds=data.get("max_cpu_time_seconds", 30),
            max_wall_time_seconds=data.get("max_wall_time_seconds", 60),
            max_file_descriptors=data.get("max_file_descriptors", 64),
            max_processes=data.get("max_processes", 1),
            max_threads=data.get("max_threads", 4),
            max_output_size_kb=data.get("max_output_size_kb", 1024),
        )

    def _resolve_security_policy(self, manifest: Any) -> SecurityPolicy:
        """Resolve security policy from manifest, falling back to defaults."""
        capabilities = getattr(manifest, "capabilities", None)
        if capabilities is None:
            return SecurityPolicy()

        if hasattr(capabilities, "model_dump"):
            data = capabilities.model_dump()
        elif isinstance(capabilities, dict):
            data = capabilities
        else:
            data = {}

        return SecurityPolicy(
            allow_network=data.get("allow_network", False),
            allow_file_system=data.get("allow_file_system", False),
            allow_subprocess=data.get("allow_subprocess", False),
        )

    def _build_execution_context(
        self,
        request: ExecutionRequest,
        manifest: Any,
    ) -> PluginExecutionContext:
        """Build restricted execution context from manifest and request."""
        plugin_name = getattr(manifest, "name", request.plugin_name)
        plugin_version = getattr(manifest, "version", "unknown")
        plugin_id = request.plugin_name or plugin_name

        return PluginExecutionContext(
            user_id=request.user_id or "",
            tenant_id="",
            session_id=request.session_id or "",
            conversation_id="",
            request_id=request.request_id,
            correlation_id="",
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            action="execute",
            policy_decision_id=request.policy_decision_id or "",
            allowed_capabilities=list(request.allowed_capabilities),
            forbidden_capabilities=list(request.forbidden_capabilities),
            resource_scope={},
            resource_limits=None,
            security_policy=None,
            provider_constraints=None,
        )

    def _validate_execution_authorization(
        self,
        context: PluginExecutionContext,
        manifest: Any,
    ) -> None:
        """Validate that plugin execution is authorized by policy."""
        if not context.policy_decision_id:
            raise ValueError(
                f"Plugin '{context.plugin_id}' requires a policy_decision_id for execution. "
                "CORTEX must route through RuntimePolicy before execution."
            )

        manifest_permissions = getattr(manifest, "permissions", None)
        if manifest_permissions is None:
            return

        if hasattr(manifest_permissions, "model_dump"):
            perms = manifest_permissions.model_dump()
        elif isinstance(manifest_permissions, dict):
            perms = manifest_permissions
        else:
            return

        required_perms = []
        for perm_key, perm_value in perms.items():
            if perm_value is True:
                required_perms.append(perm_key)
            elif isinstance(perm_value, list):
                required_perms.extend(perm_value)

        denied = [p for p in required_perms if p in context.forbidden_capabilities]
        if denied:
            raise ValueError(
                f"Plugin '{context.plugin_id}' denied: forbidden capabilities {denied}"
            )

        if context.allowed_capabilities:
            missing = [p for p in required_perms if p not in context.allowed_capabilities]
            if missing:
                raise ValueError(
                    f"Plugin '{context.plugin_id}' denied: missing allowed capabilities {missing}"
                )
    
    async def execute_plugin(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Execute a plugin with the specified parameters.
        
        Args:
            request: Plugin execution request
            
        Returns:
            Execution result
        """
        # Create execution result
        result = ExecutionResult(
            request_id=request.request_id,
            plugin_name=request.plugin_name,
            status=ExecutionStatus.PENDING
        )
        
        # Track active execution
        self.active_executions[request.request_id] = result

        start_time = time.time()
        plugin_result: Any = None

        try:
            # RuntimePolicy authorization gate
            if not request.policy_decision_id:
                raise ValueError(
                    f"Plugin '{request.plugin_name}' requires a policy_decision_id for execution. "
                    "CORTEX must route through RuntimePolicy before execution."
                )

            # Validate plugin exists and is registered
            plugin_metadata = self.registry.get_plugin(request.plugin_name)
            if not plugin_metadata:
                raise ValueError(f"Plugin '{request.plugin_name}' not found")

            if plugin_metadata.get("status") not in ["registered", "loaded", "active"]:
                raise ValueError(f"Plugin '{request.plugin_name}' is not available for execution")
            
            # Build restricted execution context from manifest and policy
            manifest = plugin_metadata.get("manifest")
            execution_context = self._build_execution_context(request, manifest)

            # Validate plugin capabilities against policy decision
            self._validate_execution_authorization(execution_context, manifest)

            # Validate and sanitize input
            sanitized_params = await self._validate_and_sanitize_input(
                request.parameters, plugin_metadata
            )

            resource_limits = self._resolve_resource_limits(manifest)
            security_policy = self._resolve_security_policy(manifest)

            # Execute plugin based on mode
            result.status = ExecutionStatus.RUNNING

            if request.execution_mode == ExecutionMode.DIRECT:
                plugin_result = await self._execute_direct(
                    plugin_metadata, sanitized_params, resource_limits, security_policy
                )
            elif request.execution_mode == ExecutionMode.THREAD:
                plugin_result = await self._execute_in_thread(
                    plugin_metadata,
                    sanitized_params,
                    resource_limits,
                    security_policy,
                    request.timeout_seconds,
                    request.request_id
                )
            elif request.execution_mode == ExecutionMode.PROCESS:
                plugin_result = await self._execute_in_process(
                    plugin_metadata,
                    sanitized_params,
                    resource_limits,
                    security_policy,
                    request.timeout_seconds,
                    request.request_id
                )
            else:  # SANDBOX mode
                plugin_result = await self._execute_in_sandbox(
                    plugin_metadata,
                    sanitized_params,
                    resource_limits,
                    security_policy,
                    request.timeout_seconds,
                    request.request_id
                )

            if result.status == ExecutionStatus.CANCELLED:
                raise asyncio.CancelledError()

            # Calculate execution time
            execution_time = time.time() - start_time

            # Validate and sanitize output
            sanitized_result = await self._validate_and_sanitize_output(
                plugin_result, plugin_metadata, resource_limits
            )
            
            # Update result
            result.status = ExecutionStatus.COMPLETED
            result.result = sanitized_result
            result.execution_time = execution_time
            result.completed_at = datetime.utcnow()
            result.plugin_id = execution_context.plugin_id
            result.plugin_version = execution_context.plugin_version
            result.user_id = execution_context.user_id
            result.tenant_id = execution_context.tenant_id
            result.policy_decision_id = execution_context.policy_decision_id
            result.requested_capabilities = list(request.allowed_capabilities)
            result.granted_capabilities = list(execution_context.allowed_capabilities)
            
            # Update metrics
            self.metrics["executions_successful"] += 1

        except asyncio.CancelledError:
            result.status = ExecutionStatus.CANCELLED
            result.error = "Plugin execution cancelled"
            result.execution_time = time.time() - start_time
            result.completed_at = datetime.utcnow()
            result.metadata.setdefault("cancel_requested", True)
            self.metrics["executions_cancelled"] += 1
            return result
        except ValueError as exc:
            result.status = ExecutionStatus.FAILED
            result.error = str(exc)
            result.error_code = "policy_denied"
            result.execution_time = time.time() - start_time
            result.completed_at = datetime.utcnow()
            result.metadata["traceback"] = ""
            self.metrics["executions_failed"] += 1
            logger.error("Plugin execution policy denied: %s", exc)
            return result
        except TimeoutError:
            result.status = ExecutionStatus.TIMEOUT
            result.error = f"Plugin execution timed out after {request.timeout_seconds} seconds"
            result.error_code = "timeout"
            self.metrics["executions_timeout"] += 1

        except Exception as e:
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            result.error_code = "execution_error"
            result.metadata["traceback"] = traceback.format_exc()
            self.metrics["executions_failed"] += 1
            logger.error(f"Plugin execution failed: {e}")
        
        finally:
            # Clean up active execution
            self.active_executions.pop(request.request_id, None)
            self.execution_handles.pop(request.request_id, None)

            # Add to history
            self._add_to_history(result)

            # Update metrics
            self.metrics["executions_total"] += 1
            self.metrics["total_execution_time"] += result.execution_time
            if self.metrics["executions_total"] > 0:
                self.metrics["average_execution_time"] = (
                    self.metrics["total_execution_time"] / self.metrics["executions_total"]
                )
        
        return result
    
    async def _execute_direct(
        self, 
        plugin_metadata: Dict[str, Any], 
        parameters: Dict[str, Any],
        resource_limits: ResourceLimits,
        security_policy: SecurityPolicy
    ) -> Any:
        """Execute plugin directly in current context."""
        entry_point = await self._load_plugin_entrypoint(plugin_metadata)
        
        with PluginSandbox(resource_limits, security_policy) as sandbox:
            if asyncio.iscoroutinefunction(entry_point):
                return await sandbox.run_async(entry_point, parameters)
            else:
                return sandbox.run(entry_point, parameters)
    
    async def _execute_in_thread(
        self,
        plugin_metadata: Dict[str, Any],
        parameters: Dict[str, Any],
        resource_limits: ResourceLimits,
        security_policy: SecurityPolicy,
        timeout_seconds: int,
        request_id: str
    ) -> Any:
        """Execute plugin in a separate thread."""

        def thread_execution():
            entry_point = self._load_plugin_entrypoint_sync(plugin_metadata)

            with PluginSandbox(resource_limits, security_policy) as sandbox:
                if asyncio.iscoroutinefunction(entry_point):
                    return asyncio.run(sandbox.run_async(entry_point, parameters))
                return sandbox.run(entry_point, parameters)

        executor_future = self.thread_pool.submit(thread_execution)
        loop = asyncio.get_running_loop()
        wrapped_future = asyncio.wrap_future(executor_future, loop=loop)

        self.execution_handles[request_id] = ExecutionHandle(
            request_id=request_id,
            mode=ExecutionMode.THREAD,
            future=wrapped_future,
            executor_future=executor_future
        )

        try:
            return await asyncio.wait_for(wrapped_future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Plugin execution timed out after {timeout_seconds} seconds")
        finally:
            self.execution_handles.pop(request_id, None)
    
    async def _execute_in_process(
        self,
        plugin_metadata: Dict[str, Any],
        parameters: Dict[str, Any],
        resource_limits: ResourceLimits,
        security_policy: SecurityPolicy,
        timeout_seconds: int,
        request_id: str
    ) -> Any:
        """Execute plugin in a separate process."""
        def process_execution():
            try:
                entry_point = self._load_plugin_entrypoint_sync(plugin_metadata)

                with PluginSandbox(resource_limits, security_policy) as sandbox:
                    if asyncio.iscoroutinefunction(entry_point):
                        return asyncio.run(sandbox.run_async(entry_point, parameters))
                    return sandbox.run(entry_point, parameters)
            except Exception as e:
                return {"error": str(e), "traceback": traceback.format_exc()}

        executor_future = self.process_pool.submit(process_execution)
        loop = asyncio.get_running_loop()
        wrapped_future = asyncio.wrap_future(executor_future, loop=loop)

        self.execution_handles[request_id] = ExecutionHandle(
            request_id=request_id,
            mode=ExecutionMode.PROCESS,
            future=wrapped_future,
            executor_future=executor_future
        )

        try:
            result = await asyncio.wait_for(wrapped_future, timeout=timeout_seconds)

            if isinstance(result, dict) and "error" in result:
                raise Exception(result["error"])

            return result
        except asyncio.TimeoutError:
            raise TimeoutError(f"Plugin execution timed out after {timeout_seconds} seconds")
        finally:
            self.execution_handles.pop(request_id, None)
    
    async def _execute_in_sandbox(
        self,
        plugin_metadata: Dict[str, Any],
        parameters: Dict[str, Any],
        resource_limits: ResourceLimits,
        security_policy: SecurityPolicy,
        timeout_seconds: int,
        request_id: str
    ) -> Any:
        """Execute plugin in enhanced sandbox mode."""
        # Class-based extensions in this repository are already constrained to
        # prompt-first handler logic and can safely use the direct sandbox path.
        if ":" in (getattr(plugin_metadata.manifest, "entry_point", None) or ""):
            return await self._execute_direct(
                plugin_metadata,
                parameters,
                resource_limits,
                security_policy,
            )

        # Otherwise fall back to process execution for stricter isolation.
        return await self._execute_in_process(
            plugin_metadata,
            parameters,
            resource_limits,
            security_policy,
            timeout_seconds,
            request_id
        )
    
    async def _load_plugin_entrypoint(self, plugin_metadata: Dict[str, Any]):
        """Load plugin entrypoint asynchronously and handle initialization."""
        entrypoint_obj = self._load_plugin_entrypoint_sync(plugin_metadata)
        
        instance = getattr(entrypoint_obj, "__self__", None)
        manifest = plugin_metadata.get("manifest")
        logger.debug(f"_load_plugin_entrypoint for {getattr(manifest, 'name', 'unknown')}, instance found: {instance is not None}")
        
        if instance:
            is_ext = hasattr(instance, "initialize") and hasattr(instance, "is_initialized")
            if is_ext:
                try:
                    if not instance.is_initialized():
                        logger.info(f"Initializing extension instance for {getattr(manifest, 'name', 'unknown')}")
                        await instance.initialize()
                        if hasattr(instance, "_is_initialized"):
                            instance._is_initialized = True
                    else:
                        logger.debug(f"Extension instance for {getattr(manifest, 'name', 'unknown')} already initialized")
                except Exception as e:
                    logger.error(f"Failed to initialize extension {getattr(manifest, 'name', 'unknown')}: {e}")
        
        return entrypoint_obj
    
    def _load_plugin_entrypoint_sync(self, plugin_metadata: Dict[str, Any]):
        """Load plugin entrypoint synchronously."""
        plugin_path = plugin_metadata["path"]
        init_path = plugin_path / "__init__.py"
        handler_path = plugin_path / "handler.py"
        manifest = plugin_metadata["manifest"]
        package_name = f"plugin_{manifest.name.replace('-', '_').replace('.', '_')}"
        entrypoint = getattr(manifest, "entrypoint", None) or "run"

        if not init_path.exists() or not handler_path.exists():
            raise ImportError(f"Cannot load plugin package from {plugin_path}")

        package_spec = importlib.util.spec_from_file_location(
            package_name,
            init_path,
            submodule_search_locations=[str(plugin_path)],
        )

        if package_spec is None or package_spec.loader is None:
            raise ImportError(f"Cannot load plugin package from {init_path}")

        package_module = importlib.util.module_from_spec(package_spec)
        sys.modules[package_name] = package_module
        package_spec.loader.exec_module(package_module)

        handler_module = importlib.import_module(f"{package_name}.handler")

        if ":" in entrypoint:
            module_name, attr_name = entrypoint.split(":", 1)
            if module_name != "handler":
                raise ImportError(
                    f"Unsupported entrypoint module '{module_name}' for {manifest.name}"
                )

            entrypoint_obj = getattr(handler_module, attr_name, None)
            if entrypoint_obj is None:
                raise ImportError(
                    f"Entrypoint '{attr_name}' not found in {handler_path}"
                )

            if inspect.isclass(entrypoint_obj):
                manifest_data = manifest.to_dict() if hasattr(manifest, "to_dict") else {}
                if isinstance(manifest_data.get("dependencies"), list):
                    manifest_data["dependencies"] = {
                        "plugins": manifest_data.get("dependencies", []),
                        "extensions": [],
                        "system_services": [],
                    }
                elif not isinstance(manifest_data.get("dependencies"), dict):
                    manifest_data["dependencies"] = {
                        "plugins": [],
                        "extensions": [],
                        "system_services": [],
                    }

                if not isinstance(manifest_data.get("rbac"), dict):
                    manifest_data["rbac"] = {
                        "allowed_roles": manifest_data.get("required_roles", ["user"]),
                        "default_enabled": manifest_data.get("default_enabled", True),
                    }

                extension_manifest = ExtensionManifest.from_dict(manifest_data)
                extension_context = ExtensionContext(
                    plugin_router=None,
                    db_session=None,
                    app_instance=None,
                    tenant_id=None,
                    user_id=None,
                    extension_dir=plugin_path,
                    config={},
                )
                extension_instance = entrypoint_obj(extension_manifest, extension_context)
                if hasattr(extension_instance, "run"):
                    return extension_instance.run
                return extension_instance

            return entrypoint_obj

        entrypoint_obj = getattr(handler_module, entrypoint, None)
        if entrypoint_obj is None:
            raise ImportError(
                f"Entrypoint '{entrypoint}' not found in {handler_path}"
            )

        return entrypoint_obj
    
    async def _validate_and_sanitize_input(
        self,
        parameters: Dict[str, Any],
        plugin_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate and sanitize plugin input parameters."""
        if not isinstance(parameters, dict):
            raise ValueError("Plugin parameters must be a dictionary")

        import json
        param_size = len(json.dumps(parameters, default=str))
        if param_size > 1024 * 1024:
            raise ValueError("Plugin parameters too large")

        manifest = plugin_metadata["manifest"]
        extras = getattr(manifest, "model_extra", {}) or {}
        schema = extras.get("parameters") or extras.get("input_schema") or {}
        allow_additional = extras.get("allow_additional_parameters", True)

        sanitized: Dict[str, Any] = {}

        for name, rules in schema.items():
            is_required = bool(rules.get("required"))
            has_default = "default" in rules
            value_present = name in parameters

            if not value_present and not has_default and is_required:
                raise ValueError(
                    f"Missing required parameter '{name}' for plugin '{manifest.name}'"
                )

            if not value_present and has_default:
                sanitized[name] = rules["default"]
                continue

            if not value_present:
                continue

            sanitized[name] = self._apply_parameter_rules(
                name, parameters[name], rules, manifest
            )

        if allow_additional:
            for key, value in parameters.items():
                if key not in sanitized:
                    sanitized[key] = value
        else:
            unexpected = set(parameters) - set(schema)
            if unexpected:
                joined = ", ".join(sorted(unexpected))
                raise ValueError(
                    f"Unexpected parameters for plugin '{manifest.name}': {joined}"
                )

        return sanitized

    def _apply_parameter_rules(
        self,
        name: str,
        value: Any,
        rules: Dict[str, Any],
        manifest: Any,
    ) -> Any:
        """Apply manifest rules to a parameter value."""

        expected_type = rules.get("type")
        coerced_value = value

        if expected_type:
            coerced_value = self._coerce_parameter_type(
                name, coerced_value, expected_type, manifest
            )

        if isinstance(coerced_value, str):
            if rules.get("strip", True):
                coerced_value = coerced_value.strip()

            max_length = rules.get("max_length")
            min_length = rules.get("min_length")

            if max_length is not None and len(coerced_value) > max_length:
                raise ValueError(
                    f"Parameter '{name}' exceeds maximum length of {max_length}"
                )

            if min_length is not None and len(coerced_value) < min_length:
                raise ValueError(
                    f"Parameter '{name}' must be at least {min_length} characters"
                )

            pattern = rules.get("pattern")
            if pattern and not re.fullmatch(pattern, coerced_value):
                raise ValueError(
                    f"Parameter '{name}' does not match required pattern"
                )

        if isinstance(coerced_value, (int, float)):
            minimum = rules.get("min")
            maximum = rules.get("max")

            if minimum is not None and coerced_value < minimum:
                raise ValueError(
                    f"Parameter '{name}' must be greater than or equal to {minimum}"
                )

            if maximum is not None and coerced_value > maximum:
                raise ValueError(
                    f"Parameter '{name}' must be less than or equal to {maximum}"
                )

        allowed_values = rules.get("enum") or rules.get("choices")
        if allowed_values is not None and coerced_value not in allowed_values:
            allowed_display = ", ".join(map(str, allowed_values))
            raise ValueError(
                f"Parameter '{name}' must be one of: {allowed_display}"
            )

        if isinstance(coerced_value, list):
            item_rules = rules.get("items", {})
            if item_rules:
                coerced_value = [
                    self._apply_parameter_rules(
                        f"{name}[{idx}]", item, item_rules, manifest
                    )
                    for idx, item in enumerate(coerced_value)
                ]

        if isinstance(coerced_value, dict):
            nested_schema = rules.get("properties") or {}
            allow_nested_extra = rules.get("allow_additional_properties", True)

            if nested_schema:
                validated: Dict[str, Any] = {}
                for key, val in coerced_value.items():
                    if key in nested_schema:
                        validated[key] = self._apply_parameter_rules(
                            f"{name}.{key}", val, nested_schema[key], manifest
                        )
                    elif allow_nested_extra:
                        validated[key] = val
                    else:
                        raise ValueError(
                            f"Unexpected nested parameter '{name}.{key}' in plugin '{manifest.name}'"
                        )
                coerced_value = validated

        return coerced_value

    def _coerce_parameter_type(
        self,
        name: str,
        value: Any,
        expected_type: str,
        manifest: Any,
    ) -> Any:
        """Coerce a parameter value into the expected manifest type."""

        type_map = {
            "string": str,
            "str": str,
            "integer": int,
            "int": int,
            "float": float,
            "number": (int, float),
            "boolean": bool,
            "bool": bool,
            "array": list,
            "list": list,
            "object": dict,
            "dict": dict,
        }

        normalized_type = expected_type.lower()
        target_type = type_map.get(normalized_type)

        if not target_type:
            logger.warning(
                "Unknown parameter type '%s' in manifest '%s'", expected_type, getattr(manifest, "name", "unknown")
            )
            return value

        if normalized_type in {"string", "str"}:
            return str(value)

        if normalized_type in {"integer", "int"}:
            if isinstance(value, bool):
                raise ValueError(f"Parameter '{name}' must be an integer")
            try:
                return int(value)
            except (TypeError, ValueError):
                raise ValueError(f"Parameter '{name}' must be an integer") from None

        if normalized_type in {"float", "number"}:
            if isinstance(value, bool):
                raise ValueError(f"Parameter '{name}' must be a number")
            try:
                return float(value)
            except (TypeError, ValueError):
                raise ValueError(f"Parameter '{name}' must be a number") from None

        if normalized_type in {"boolean", "bool"}:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "y", "on"}:
                    return True
                if lowered in {"false", "0", "no", "n", "off"}:
                    return False
            raise ValueError(f"Parameter '{name}' must be a boolean value")

        if not isinstance(value, target_type):
            raise ValueError(
                f"Parameter '{name}' must be of type '{expected_type}'"
            )

        return value
    
    async def _validate_and_sanitize_output(
        self,
        result: Any,
        plugin_metadata: Dict[str, Any],
        resource_limits: ResourceLimits
    ) -> Any:
        """Validate and sanitize plugin output."""
        import json
        try:
            result_json = json.dumps(result, default=str)
            result_size = len(result_json)
            
            max_size = resource_limits.max_output_size_kb * 1024
            if result_size > max_size:
                raise ValueError(f"Plugin output too large: {result_size} bytes > {max_size} bytes")
            
        except (TypeError, ValueError) as e:
            if "too large" in str(e):
                raise
            # If result is not JSON serializable, convert to string
            result = str(result)
            if len(result) > resource_limits.max_output_size_kb * 1024:
                result = result[:resource_limits.max_output_size_kb * 1024] + "... [truncated]"
        
        return result
    
    def _add_to_history(self, result: ExecutionResult):
        """Add execution result to history."""
        self.execution_history.append(result)
        
        # Maintain history size limit
        if len(self.execution_history) > self.max_history_size:
            self.execution_history = self.execution_history[-self.max_history_size:]
    
    async def cancel_execution(self, request_id: str) -> bool:
        """
        Cancel an active plugin execution.

        Args:
            request_id: Request ID to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        if request_id not in self.active_executions:
            return False

        try:
            result = self.active_executions[request_id]
            handle = self.execution_handles.get(request_id)

            if handle and handle.future.done():
                # Execution already completed but cleanup not processed yet
                return False

            result.status = ExecutionStatus.CANCELLED
            result.completed_at = datetime.utcnow()
            result.metadata["cancel_requested"] = True
            result.metadata["cancelled_at"] = result.completed_at.isoformat()

            cancel_success = False
            if handle:
                cancel_success = handle.cancel()
                self.execution_handles.pop(request_id, None)

            if not cancel_success:
                logger.warning(
                    "Cancellation requested for %s but underlying execution could not be interrupted",
                    request_id
                )

            # Ensure active map cleanup mirrors execute_plugin finally block
            self.active_executions.pop(request_id, None)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel execution {request_id}: {e}")
            return False
    
    def get_active_executions(self) -> List[ExecutionResult]:
        """Get list of active executions."""
        return list(self.active_executions.values())
    
    def get_execution_history(self, limit: int = 100) -> List[ExecutionResult]:
        """Get execution history."""
        return self.execution_history[-limit:]
    
    def get_execution_metrics(self) -> Dict[str, Any]:
        """Get execution metrics."""
        return self.metrics.copy()
    
    async def cleanup(self):
        """Clean up resources."""
        try:
            self.thread_pool.shutdown(wait=True)
            self.process_pool.shutdown(wait=True)
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


# Global execution engine instance
_execution_engine: Optional[PluginExecutionEngine] = None


def get_plugin_execution_engine() -> PluginExecutionEngine:
    """Get global plugin execution engine instance."""
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = PluginExecutionEngine()
    return _execution_engine


async def initialize_plugin_execution_engine(
    registry: Optional[PluginRegistry] = None
) -> PluginExecutionEngine:
    """
    Initialize the plugin execution engine.
    
    Args:
        registry: Plugin registry to use
        
    Returns:
        Initialized plugin execution engine
    """
    global _execution_engine
    _execution_engine = PluginExecutionEngine(registry)
    return _execution_engine

# Compatibility shim: routes/runtime should dispatch through unified registry only.
from ai_karen_engine.extensions.platform.core.cortex_execution_registry import CortexExecutionContext
from ai_karen_engine.services.plugin_registry import UNIFIED_REGISTRY


def execute_plugin(plugin_name: str, user_ctx: Dict[str, Any], query: Any, context: Optional[Dict[str, Any]] = None, stream: Optional[Callable[[Dict[str, Any]], None]] = None) -> Any:
    """Legacy execute shim backed by unified interface."""
    return UNIFIED_REGISTRY.execute(
        CortexExecutionContext(
            plugin_name=plugin_name,
            user_ctx=user_ctx,
            query=query,
            context=context,
            stream=stream,
        )
    )
