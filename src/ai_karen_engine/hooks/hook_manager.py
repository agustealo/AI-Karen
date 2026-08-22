"""
Unified Hook Manager that integrates with Karen's existing infrastructure.
"""
# mypy: ignore-errors

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ai_karen_engine.database.client import get_db_session_context
from ai_karen_engine.database.models import HookExecutionStat
from ai_karen_engine.event_bus import get_event_bus
from ai_karen_engine.hooks.hook_types import HookTypes
from ai_karen_engine.hooks.models import (
    HookContext,
    HookExecutionSummary,
    HookPriority,
    HookRegistration,
    HookResult,
)

logger = logging.getLogger(__name__)


class HookManager:
    """
    Unified hook system that integrates with Karen's existing infrastructure.

    This manager coordinates hooks across plugins, extensions, and other components,
    providing a unified interface for hook registration and execution.
    """

    def __init__(self):
        """Initialize the hook manager."""
        self.hooks: Dict[str, List[HookRegistration]] = defaultdict(list)
        self.hook_registry: Dict[str, HookRegistration] = {}
        self.event_bus = get_event_bus()
        self.logger = logging.getLogger("hook_manager")
        self._execution_stats = defaultdict(int)
        self._enabled = True
        self._registration_sequence = 0
        self._hook_depth = 0
        self._max_hook_depth = 5
        self._active_hook_chains: Dict[str, List[str]] = {}

    async def register_hook(
        self,
        hook_type: str,
        handler: Callable,
        priority: int = HookPriority.NORMAL.value,
        conditions: Optional[Dict[str, Any]] = None,
        source_type: str = "custom",
        source_name: Optional[str] = None,
        trust_level: str = "observational",
        criticality: str = "best_effort",
    ) -> str:
        """
        Register a hook with the unified system.

        Args:
            hook_type: Type of hook to register
            handler: Hook handler function
            priority: Hook priority (lower = higher priority)
            conditions: Conditions for hook execution
            source_type: Type of source (plugin, extension, etc.)
            source_name: Name of the source
            trust_level: observational, transformational, or side_effecting
            criticality: best_effort, important, or critical

        Returns:
            Hook ID
        """
        if not HookTypes.is_valid_type(hook_type):
            self.logger.warning(f"Registering hook with non-standard type: {hook_type}")

        hook_id = f"{source_type}_{hook_type}_{uuid.uuid4().hex[:8]}"

        self._registration_sequence += 1
        registration = HookRegistration(
            id=hook_id,
            hook_type=hook_type,
            handler=handler,
            priority=priority,
            conditions=conditions or {},
            source_type=source_type,
            source_name=source_name,
            trust_level=trust_level,
            criticality=criticality,
            sequence=self._registration_sequence,
        )

        # Add to hooks list and sort by priority, then sequence for deterministic ordering
        self.hooks[hook_type].append(registration)
        self.hooks[hook_type].sort(key=lambda x: (x.priority, x.sequence))

        # Add to registry
        self.hook_registry[hook_id] = registration

        # Publish hook registration event
        try:
            self.event_bus.publish(
                "hook_system",
                "hook_registered",
                {
                    "hook_id": hook_id,
                    "hook_type": hook_type,
                    "source_type": source_type,
                    "source_name": source_name,
                    "priority": priority,
                },
                roles=["admin"],
            )
        except Exception as e:
            self.logger.debug(f"Failed to publish hook registration event: {e}")

        self.logger.info(f"Registered hook {hook_id} for type {hook_type}")
        return hook_id

    async def unregister_hook(self, hook_id: str) -> bool:
        """
        Unregister a hook.

        Args:
            hook_id: ID of hook to unregister

        Returns:
            True if successful, False otherwise
        """
        if hook_id not in self.hook_registry:
            self.logger.warning(f"Hook {hook_id} not found for unregistration")
            return False

        registration = self.hook_registry[hook_id]
        hook_type = registration.hook_type

        # Remove from hooks list
        self.hooks[hook_type] = [
            hook for hook in self.hooks[hook_type] if hook.id != hook_id
        ]

        # Remove from registry
        del self.hook_registry[hook_id]

        # Publish hook unregistration event
        try:
            self.event_bus.publish(
                "hook_system",
                "hook_unregistered",
                {
                    "hook_id": hook_id,
                    "hook_type": hook_type,
                    "source_type": registration.source_type,
                    "source_name": registration.source_name,
                },
                roles=["admin"],
            )
        except Exception as e:
            self.logger.debug(f"Failed to publish hook unregistration event: {e}")

        self.logger.info(f"Unregistered hook {hook_id}")
        return True

    async def trigger_hooks(
        self, context: HookContext, timeout_seconds: float = 30.0
    ) -> HookExecutionSummary:
        """
        Trigger all registered hooks of a specific type.

        Args:
            context: Hook execution context
            timeout_seconds: Timeout for hook execution

        Returns:
            Summary of hook execution
        """
        if not self._enabled:
            self.logger.debug(f"Hook manager disabled, skipping {context.hook_type}")
            return HookExecutionSummary(
                hook_type=context.hook_type,
                total_hooks=0,
                successful_hooks=0,
                failed_hooks=0,
                total_execution_time_ms=0.0,
                results=[],
            )

        # Recursion protection
        self._hook_depth += 1
        if self._hook_depth > self._max_hook_depth:
            self._hook_depth -= 1
            self.logger.warning(
                f"Hook recursion depth {self._hook_depth} exceeds maximum {self._max_hook_depth}. "
                f"Skipping {context.hook_type} to prevent infinite loops."
            )
            return HookExecutionSummary(
                hook_type=context.hook_type,
                total_hooks=0,
                successful_hooks=0,
                failed_hooks=0,
                total_execution_time_ms=0.0,
                results=[],
            )

        # Track hook chain for cycle detection
        chain_key = f"{context.hook_type}:{id(context)}"
        if chain_key not in self._active_hook_chains:
            self._active_hook_chains[chain_key] = []
        self._active_hook_chains[chain_key].append(context.hook_type)

        try:
            return await self._execute_hooks(context, timeout_seconds)
        finally:
            self._hook_depth -= 1
            self._active_hook_chains[chain_key].pop()
            if not self._active_hook_chains[chain_key]:
                del self._active_hook_chains[chain_key]

    async def _execute_hooks(
        self, context: HookContext, timeout_seconds: float
    ) -> HookExecutionSummary:
        """Internal hook execution after recursion checks pass."""

        hook_type = context.hook_type
        hooks_to_execute = self.hooks.get(hook_type, [])

        if not hooks_to_execute:
            self.logger.debug(f"No hooks registered for type {hook_type}")
            return HookExecutionSummary(
                hook_type=hook_type,
                total_hooks=0,
                successful_hooks=0,
                failed_hooks=0,
                total_execution_time_ms=0.0,
                results=[],
            )

        # Filter hooks based on conditions
        filtered_hooks = []
        for hook_reg in hooks_to_execute:
            if not hook_reg.enabled:
                continue
            if self._check_conditions(hook_reg.conditions, context):
                filtered_hooks.append(hook_reg)

        if not filtered_hooks:
            self.logger.debug(f"No hooks passed conditions for type {hook_type}")
            return HookExecutionSummary(
                hook_type=hook_type,
                total_hooks=len(hooks_to_execute),
                successful_hooks=0,
                failed_hooks=0,
                total_execution_time_ms=0.0,
                results=[],
            )

        # Publish pre-hook event
        try:
            self.event_bus.publish(
                "hook_system",
                "hooks_triggered",
                {
                    "hook_type": hook_type,
                    "context_keys": list(context.data.keys()),
                    "hook_count": len(filtered_hooks),
                    "source_types": list(set(h.source_type for h in filtered_hooks)),
                },
                roles=["admin"],
            )
        except Exception as e:
            self.logger.debug(f"Failed to publish hooks triggered event: {e}")

        # Execute hooks
        results = []
        start_time = time.time()

        for hook_reg in filtered_hooks:
            hook_start = time.time()
            try:
                # Execute hook with timeout
                result = await asyncio.wait_for(
                    self._execute_hook(hook_reg, context), timeout=timeout_seconds
                )

                execution_time = (time.time() - hook_start) * 1000
                results.append(
                    HookResult.success_result(hook_reg.id, result, execution_time)
                )

                self._execution_stats[f"{hook_type}_success"] += 1

            except asyncio.TimeoutError:
                execution_time = (time.time() - hook_start) * 1000
                error_msg = f"Hook {hook_reg.id} timed out after {timeout_seconds}s"
                results.append(
                    HookResult.error_result(hook_reg.id, error_msg, execution_time)
                )

                self.logger.warning(error_msg)
                self._execution_stats[f"{hook_type}_timeout"] += 1

                if hook_reg.criticality == "critical":
                    self.logger.error(
                        f"Critical hook {hook_reg.id} timed out — halting execution"
                    )
                    break

            except Exception as e:
                execution_time = (time.time() - hook_start) * 1000
                error_msg = f"Hook {hook_reg.id} failed: {str(e)}"
                results.append(
                    HookResult.error_result(hook_reg.id, error_msg, execution_time)
                )

                self.logger.error(error_msg, exc_info=True)
                self._execution_stats[f"{hook_type}_error"] += 1

                if hook_reg.criticality == "critical":
                    self.logger.error(
                        f"Critical hook {hook_reg.id} failed — halting execution"
                    )
                    break

                # Publish error event
                try:
                    self.event_bus.publish(
                        "hook_system",
                        "hook_error",
                        {
                            "hook_id": hook_reg.id,
                            "hook_type": hook_type,
                            "error": str(e),
                            "source_type": hook_reg.source_type,
                            "source_name": hook_reg.source_name,
                        },
                        roles=["admin"],
                    )
                except Exception as pub_error:
                    self.logger.debug(
                        f"Failed to publish hook error event: {pub_error}"
                    )

        total_execution_time = (time.time() - start_time) * 1000
        successful_hooks = sum(1 for r in results if r.success)
        failed_hooks = len(results) - successful_hooks

        summary = HookExecutionSummary(
            hook_type=hook_type,
            total_hooks=len(filtered_hooks),
            successful_hooks=successful_hooks,
            failed_hooks=failed_hooks,
            total_execution_time_ms=total_execution_time,
            results=results,
        )

        self.logger.debug(
            f"Executed {len(filtered_hooks)} hooks for {hook_type}: "
            f"{successful_hooks} successful, {failed_hooks} failed, "
            f"{total_execution_time:.2f}ms total"
        )

        # Persist execution statistics grouped by source
        try:
            stats_by_source: Dict[str, Dict[str, float]] = {}
            for hook_reg, result in zip(filtered_hooks, results):
                src = hook_reg.source_name or "unknown"
                data = stats_by_source.setdefault(
                    src,
                    {
                        "executions": 0,
                        "successes": 0,
                        "errors": 0,
                        "timeouts": 0,
                        "total_duration": 0.0,
                    },
                )
                data["executions"] += 1
                if result.success:
                    data["successes"] += 1
                else:
                    data["errors"] += 1
                    if result.error and "timed out" in result.error:
                        data["timeouts"] += 1
                data["total_duration"] += result.execution_time_ms

            with get_db_session_context() as session:
                for source_name, data in stats_by_source.items():
                    stat = HookExecutionStat(
                        hook_type=hook_type,
                        source_name=source_name,
                        executions=data["executions"],
                        successes=data["successes"],
                        errors=data["errors"],
                        timeouts=data["timeouts"],
                        avg_duration_ms=int(data["total_duration"] / data["executions"])
                        if data["executions"]
                        else 0,
                        window_start=datetime.utcnow(),
                        window_end=datetime.utcnow(),
                    )
                    session.add(stat)
                session.commit()
        except Exception as db_error:
            self.logger.debug(f"Failed to record hook execution stats: {db_error}")

        return summary

    async def _execute_hook(
        self, hook_reg: HookRegistration, context: HookContext
    ) -> Any:
        """
        Execute a single hook.

        Args:
            hook_reg: Hook registration
            context: Hook context

        Returns:
            Hook result
        """
        handler = hook_reg.handler

        # Handle different handler signatures
        if asyncio.iscoroutinefunction(handler):
            # Async handler
            try:
                # Try with context parameter
                return await handler(context)
            except TypeError:
                # Fallback to legacy signature
                return await handler(context.data, context.user_context)
        else:
            # Sync handler
            try:
                # Try with context parameter
                result = handler(context)
                # If result is a coroutine, await it
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except TypeError:
                # Fallback to legacy signature
                result = handler(context.data, context.user_context)
                if asyncio.iscoroutine(result):
                    return await result
                return result

    def _check_conditions(
        self, conditions: Dict[str, Any], context: HookContext
    ) -> bool:
        """
        Check if hook conditions are met.

        Args:
            conditions: Hook conditions
            context: Hook context

        Returns:
            True if conditions are met, False otherwise
        """
        if not conditions:
            return True

        # Check user context conditions
        if "user_roles" in conditions and context.user_context:
            required_roles = conditions["user_roles"]
            user_roles = context.user_context.get("roles", [])
            if not set(required_roles).intersection(set(user_roles)):
                return False

        # Check tenant conditions
        if "tenant_id" in conditions and context.user_context:
            required_tenant = conditions["tenant_id"]
            user_tenant = context.user_context.get("tenant_id")
            if required_tenant != user_tenant:
                return False

        # Check data conditions
        if "data_keys" in conditions:
            required_keys = conditions["data_keys"]
            if not all(key in context.data for key in required_keys):
                return False

        # Check custom conditions
        if "custom" in conditions:
            custom_conditions = conditions["custom"]
            for key, expected_value in custom_conditions.items():
                if context.data.get(key) != expected_value:
                    return False

        return True

    def get_hooks_by_type(self, hook_type: str) -> List[HookRegistration]:
        """Get all hooks of a specific type."""
        return self.hooks.get(hook_type, []).copy()

    def get_hooks_by_source(
        self, source_type: str, source_name: Optional[str] = None
    ) -> List[HookRegistration]:
        """Get all hooks from a specific source."""
        result = []
        for hook_list in self.hooks.values():
            for hook in hook_list:
                if hook.source_type == source_type:
                    if source_name is None or hook.source_name == source_name:
                        result.append(hook)
        return result

    def get_hook_by_id(self, hook_id: str) -> Optional[HookRegistration]:
        """Get a hook by its ID."""
        return self.hook_registry.get(hook_id)

    def get_all_hooks(self) -> List[HookRegistration]:
        """Get all registered hooks."""
        return list(self.hook_registry.values())

    def get_hook_types(self) -> List[str]:
        """Get all registered hook types."""
        return list(self.hooks.keys())

    def get_execution_stats(self) -> Dict[str, int]:
        """Get hook execution statistics."""
        return dict(self._execution_stats)

    def clear_execution_stats(self) -> None:
        """Clear hook execution statistics."""
        self._execution_stats.clear()

    def enable(self) -> None:
        """Enable the hook manager."""
        self._enabled = True
        self.logger.info("Hook manager enabled")

    def disable(self) -> None:
        """Disable the hook manager."""
        self._enabled = False
        self.logger.info("Hook manager disabled")

    def is_enabled(self) -> bool:
        """Check if the hook manager is enabled."""
        return self._enabled

    async def clear_hooks_by_source(
        self, source_type: str, source_name: Optional[str] = None
    ) -> int:
        """
        Clear all hooks from a specific source.

        Args:
            source_type: Type of source
            source_name: Name of source (optional)

        Returns:
            Number of hooks cleared
        """
        hooks_to_remove = self.get_hooks_by_source(source_type, source_name)

        for hook in hooks_to_remove:
            await self.unregister_hook(hook.id)

        return len(hooks_to_remove)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the hook manager state."""
        total_hooks = len(self.hook_registry)
        hook_types = len(self.hooks)
        source_types = set(hook.source_type for hook in self.hook_registry.values())

        return {
            "enabled": self._enabled,
            "total_hooks": total_hooks,
            "hook_types": hook_types,
            "source_types": list(source_types),
            "execution_stats": dict(self._execution_stats),
        }


# Global hook manager instance
_hook_manager: Optional[HookManager] = None


def get_hook_manager() -> HookManager:
    """Get the global hook manager instance."""
    global _hook_manager
    if _hook_manager is None:
        _hook_manager = HookManager()
    return _hook_manager


def create_hook_manager() -> HookManager:
    """Create a new hook manager instance."""
    return HookManager()


__all__ = [
    "HookManager",
    "get_hook_manager",
    "create_hook_manager",
]
