"""
Agent Integration Service for CoPilot Architecture.

.. deprecated::
    The legacy integration service is deprecated. Use ``ai_karen_engine.agent_medusa``
    for canonical multi-agent execution, or ``ai_karen_engine.agents.integration_service``
    for legacy UI compatibility only.
"""

import logging
import warnings

warnings.warn(
    "ai_karen_engine.agents.agent_integration_service is deprecated. "
    "Use ai_karen_engine.agent_medusa instead.",
    DeprecationWarning,
    stacklevel=2,
)

import logging
import asyncio
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from enum import Enum

from .internal.agent_schemas import AgentTask, AgentResponse, AgentDefinition
from .agent_orchestrator import AgentOrchestrator
from .adapters.deepagents_adapter import DeepAgentsAdapter
from .adapters.langchain_adapter import LangChainAdapter
from .adapters.langgraph_adapter import LangGraphAdapter
from .bridges.karen_langchain_bridge import KarenLangChainBridge

logger = logging.getLogger(__name__)


class AgentExecutionMode(str, Enum):
    """Agent execution mode enumeration."""

    NATIVE = "native"
    LANGCHAIN = "langchain"
    DEEPAGENTS = "deepagents"
    LANGGRAPH = "langgraph"


class AgentIntegrationService:
    """
    Service for integrating different agent execution modes.

    This service provides a unified interface for executing agents using
    different execution modes while maintaining compatibility with the
    existing agent framework.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        agent_orchestrator: Optional[AgentOrchestrator] = None,
        langchain_adapter: Optional[LangChainAdapter] = None,
        karen_langchain_bridge: Optional[KarenLangChainBridge] = None,
        deepagents_adapter: Optional[DeepAgentsAdapter] = None,
        langgraph_adapter: Optional[LangGraphAdapter] = None,
    ):
        """
        Initialize the Agent Integration Service.

        Args:
            config: Configuration dictionary for the service
            agent_orchestrator: Agent orchestrator instance for native mode
            deepagents_adapter: DeepAgents adapter instance
            langchain_adapter: LangChain adapter instance
        """
        self.config = config or {}
        self.agent_orchestrator = agent_orchestrator
        self.langchain_adapter = langchain_adapter
        self.karen_langchain_bridge = karen_langchain_bridge
        self.deepagents_adapter = deepagents_adapter
        self.langgraph_adapter = langgraph_adapter

        # Force LANGGRAPH mode as per the new architecture
        self._default_mode = AgentExecutionMode.LANGGRAPH
        self._auto_mode_selection = False  # Disable auto mode selection

        # Mode-specific configurations
        self._mode_configs = {
            AgentExecutionMode.NATIVE: self.config.get("native_config", {}),
            AgentExecutionMode.LANGCHAIN: self.config.get("langchain_config", {}),
            AgentExecutionMode.DEEPAGENTS: self.config.get("deepagents_config", {}),
            AgentExecutionMode.LANGGRAPH: self.config.get("langgraph_config", {}),
        }

        # Mode selection criteria
        self._mode_selection_criteria = self.config.get(
            "mode_selection_criteria",
            {
                "task_complexity_threshold": 0.7,
                "task_length_threshold": 1000,
                "reasoning_required_threshold": 0.8,
                "creativity_required_threshold": 0.6,
            },
        )

        # Performance metrics
        self._mode_performance_metrics = {
            AgentExecutionMode.NATIVE: {
                "execution_count": 0,
                "average_execution_time": 0.0,
                "success_rate": 0.0,
                "total_execution_time": 0.0,
            },
            AgentExecutionMode.LANGCHAIN: {
                "execution_count": 0,
                "average_execution_time": 0.0,
                "success_rate": 0.0,
                "total_execution_time": 0.0,
            },
            AgentExecutionMode.DEEPAGENTS: {
                "execution_count": 0,
                "average_execution_time": 0.0,
                "success_rate": 0.0,
                "total_execution_time": 0.0,
            },
            AgentExecutionMode.LANGGRAPH: {
                "execution_count": 0,
                "average_execution_time": 0.0,
                "success_rate": 0.0,
                "total_execution_time": 0.0,
            },
        }

        logger.info("Agent Integration Service initialized successfully")

    async def initialize(self) -> None:
        """Initialize the Agent Integration Service and its components."""
        logger.info("Initializing Agent Integration Service")

        # Initialize agent orchestrator if not provided
        if not self.agent_orchestrator:
            self.agent_orchestrator = AgentOrchestrator(
                config=self.config.get("orchestrator_config", {})
            )
            await self.agent_orchestrator.initialize()

        if (
            not self.langchain_adapter
            and self._mode_configs[AgentExecutionMode.LANGCHAIN]
        ):
            self.langchain_adapter = LangChainAdapter(
                config=self._mode_configs[AgentExecutionMode.LANGCHAIN]
            )

        if not self.karen_langchain_bridge and self.langchain_adapter:
            self.karen_langchain_bridge = KarenLangChainBridge(
                config=self._mode_configs[AgentExecutionMode.LANGCHAIN]
            )

        # Initialize DeepAgents adapter if not provided
        if (
            not self.deepagents_adapter
            and self._mode_configs[AgentExecutionMode.DEEPAGENTS]
        ):
            self.deepagents_adapter = DeepAgentsAdapter(
                config=self._mode_configs[AgentExecutionMode.DEEPAGENTS]
            )

        # Initialize LangGraph adapter if not provided
        if (
            not self.langgraph_adapter
            and self._mode_configs[AgentExecutionMode.LANGGRAPH]
        ):
            self.langgraph_adapter = LangGraphAdapter(
                config=self._mode_configs[AgentExecutionMode.LANGGRAPH]
            )

        logger.info("Agent Integration Service initialized successfully")

    async def execute_task(
        self,
        task: AgentTask,
        execution_mode: Optional[AgentExecutionMode] = None,
        agent_definition: Optional[AgentDefinition] = None,
    ) -> AgentResponse:
        """
        Execute a task using the appropriate execution mode.

        Args:
            task: Task to execute
            execution_mode: Specific execution mode to use (if None, uses auto-selection)
            agent_definition: Agent definition for the task

        Returns:
            Agent response with execution results
        """
        # Force LANGGRAPH mode as per the new architecture
        if not execution_mode:
            execution_mode = AgentExecutionMode.LANGGRAPH

        logger.info(f"Executing task {task.task_id} using {execution_mode.value} mode")

        # Execute task using the selected mode
        try:
            start_time = datetime.utcnow()

            if execution_mode == AgentExecutionMode.NATIVE:
                response = await self._execute_native_mode(task, agent_definition)
            elif execution_mode == AgentExecutionMode.LANGCHAIN:
                response = await self._execute_langchain_mode(task, agent_definition)
            elif execution_mode == AgentExecutionMode.DEEPAGENTS:
                response = await self._execute_deepagents_mode(task, agent_definition)
            elif execution_mode == AgentExecutionMode.LANGGRAPH:
                response = await self._execute_langgraph_mode(task, agent_definition)
            else:
                raise ValueError(f"Unsupported execution mode: {execution_mode}")

            end_time = datetime.utcnow()
            execution_time = (end_time - start_time).total_seconds()

            # Update performance metrics
            await self._update_performance_metrics(
                execution_mode, response, execution_time
            )

            # Add execution metadata to response
            response.data["execution_metadata"] = {
                "execution_mode": execution_mode.value,
                "execution_time": execution_time,
                "timestamp": end_time.isoformat(),
            }

            return response

        except Exception as e:
            logger.error(
                f"Error executing task {task.task_id} in {execution_mode.value} mode: {e}"
            )
            return AgentResponse(
                response_id=f"resp_{task.task_id}",
                task_id=task.task_id,
                agent_id=task.agent_id,
                success=False,
                data={},
                error=str(e),
                execution_time=0.0,
            )

    async def _execute_native_mode(
        self, task: AgentTask, agent_definition: Optional[AgentDefinition] = None
    ) -> AgentResponse:
        """
        Execute a task using native mode.

        Args:
            task: Task to execute
            agent_definition: Agent definition for the task

        Returns:
            Agent response with execution results
        """
        if not self.agent_orchestrator:
            raise ValueError(
                "Agent orchestrator not available for native mode execution"
            )

        # Create agent if not already registered
        if agent_definition and task.agent_id:
            agent_exists = await self.agent_orchestrator.get_agent_status(task.agent_id)
            if not agent_exists:
                await self.agent_orchestrator.register_agent(
                    agent_id=task.agent_id,
                    agent_type=agent_definition.agent_type,
                    config=agent_definition.config,
                )

        # Route task to agent
        result = await self.agent_orchestrator.route_task(
            task_type=task.task_type, task_data=task.input_data or {}
        )

        # Convert result to AgentResponse
        return AgentResponse(
            response_id=f"resp_{task.task_id}",
            task_id=task.task_id,
            agent_id=task.agent_id,
            success=result.get("status") == "completed",
            data=result.get("result", {}),
            message=result.get("error", "Task completed successfully"),
            execution_time=result.get("execution_time", 0.0),
        )

    async def _execute_deepagents_mode(
        self, task: AgentTask, agent_definition: Optional[AgentDefinition] = None
    ) -> AgentResponse:
        """
        Execute a task using DeepAgents mode.

        Args:
            task: Task to execute
            agent_definition: Agent definition for the task

        Returns:
            Agent response with execution results
        """
        if not self.deepagents_adapter:
            raise ValueError(
                "DeepAgents adapter not available for DeepAgents mode execution"
            )

        # Create agent if not already created
        if agent_definition and task.agent_id:
            agent_exists = self.deepagents_adapter.get_agent(task.agent_id)
            if not agent_exists:
                await self.deepagents_adapter.create_agent(
                    agent_id=task.agent_id, agent_definition=agent_definition
                )

        # Execute task
        response = await self.deepagents_adapter.execute_task(
            agent_id=task.agent_id, task=task
        )

        return response

    async def _execute_langchain_mode(
        self, task: AgentTask, agent_definition: Optional[AgentDefinition] = None
    ) -> AgentResponse:
        """
        Execute a task using LangChain mode via the Karen bridge.
        """
        if not self.karen_langchain_bridge:
            raise ValueError(
                "LangChain bridge not available for LangChain mode execution"
            )

        if agent_definition and task.agent_id:
            agent_exists = self.karen_langchain_bridge.get_agent(task.agent_id)
            if not agent_exists:
                await self.karen_langchain_bridge.create_agent(
                    agent_definition=agent_definition
                )

        return await self.karen_langchain_bridge.execute_agent(
            agent_id=task.agent_id, task=task
        )

    async def _execute_langgraph_mode(
        self, task: AgentTask, agent_definition: Optional[AgentDefinition] = None
    ) -> AgentResponse:
        """
        Execute a task using LangGraph mode.

        Args:
            task: Task to execute
            agent_definition: Agent definition for the task

        Returns:
            Agent response with execution results
        """
        if not self.langgraph_adapter:
            raise ValueError(
                "LangGraph adapter not available for LangGraph mode execution"
            )

        # Create graph if not already created
        if agent_definition and task.agent_id:
            graph_exists = self.langgraph_adapter.get_graph(task.agent_id)
            if not graph_exists:
                await self.langgraph_adapter.create_graph(
                    graph_id=task.agent_id, agent_definition=agent_definition
                )

        # Execute task
        response = await self.langgraph_adapter.execute_graph(
            graph_id=task.agent_id, task=task
        )

        return response

    async def _update_performance_metrics(
        self,
        execution_mode: AgentExecutionMode,
        response: AgentResponse,
        execution_time: float,
    ) -> None:
        """
        Update performance metrics for an execution mode.

        Args:
            execution_mode: Execution mode that was used
            response: Response from the execution
            execution_time: Time taken for execution
        """
        metrics = self._mode_performance_metrics[execution_mode]

        # Update execution count
        metrics["execution_count"] += 1

        # Update total execution time
        metrics["total_execution_time"] += execution_time

        # Update average execution time
        if metrics["execution_count"] > 0:
            metrics["average_execution_time"] = (
                metrics["total_execution_time"] / metrics["execution_count"]
            )

        # Update success rate
        if metrics["execution_count"] > 0:
            success_count = sum(1 for m in [metrics] if m.get("last_success", False))
            metrics["success_rate"] = success_count / metrics["execution_count"]

        # Track last execution success
        metrics["last_success"] = response.success

        logger.debug(f"Updated performance metrics for {execution_mode.value} mode")

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics for all execution modes.

        Returns:
            Dictionary of performance metrics
        """
        return {
            "modes": {
                mode.value: metrics.copy()
                for mode, metrics in self._mode_performance_metrics.items()
            },
            "auto_mode_selection": self._auto_mode_selection,
            "default_mode": self._default_mode.value,
            "mode_selection_criteria": self._mode_selection_criteria,
        }

    async def set_default_mode(self, mode: AgentExecutionMode) -> None:
        """
        Set the default execution mode.

        Args:
            mode: Default execution mode to set
        """
        self._default_mode = mode
        logger.info(f"Set default execution mode to {mode.value}")

    async def enable_auto_mode_selection(self, enabled: bool) -> None:
        """
        Enable or disable automatic mode selection.

        Args:
            enabled: Whether to enable automatic mode selection
        """
        self._auto_mode_selection = enabled
        logger.info(f"{'Enabled' if enabled else 'Disabled'} automatic mode selection")

    async def update_mode_selection_criteria(self, criteria: Dict[str, float]) -> None:
        """
        Update the criteria for automatic mode selection.

        Args:
            criteria: New criteria for mode selection
        """
        self._mode_selection_criteria.update(criteria)
        logger.info(f"Updated mode selection criteria: {criteria}")

    async def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the Agent Integration Service.

        Returns:
            Health status information
        """
        health_status = {
            "service": "agent_integration_service",
            "timestamp": datetime.utcnow().isoformat(),
            "default_mode": self._default_mode.value,
            "auto_mode_selection": self._auto_mode_selection,
            "modes_available": {},
        }

        # Check native mode availability
        health_status["modes_available"]["native"] = self.agent_orchestrator is not None

        # Check DeepAgents mode availability
        if self.deepagents_adapter:
            deepagents_health = await self.deepagents_adapter.health_check()
            health_status["modes_available"]["deepagents"] = deepagents_health.get(
                "deepagents_available", False
            )
        else:
            health_status["modes_available"]["deepagents"] = False

        # Check LangGraph mode availability
        if self.langgraph_adapter:
            langgraph_health = await self.langgraph_adapter.health_check()
            health_status["modes_available"]["langgraph"] = langgraph_health.get(
                "langgraph_available", False
            )
        else:
            health_status["modes_available"]["langgraph"] = False

        return health_status
