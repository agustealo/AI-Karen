"""Tenant-scoped LangGraph checkpoints via Karen's existing PostgreSQL engine.

The Medusa durable run ledger owns lifecycle and identity. This module is
only a graph-state repository. It uses a forward-only migration with RLS and
per-transaction tenant context; it never opens another database pool or
creates tables at runtime. Graph resume remains a separately authorized
runtime operation, not a capability inferred from the existence of rows.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    writes_sort_key,
)
from sqlalchemy import text

from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    _canonical_tenant_id,
)
from ai_karen_engine.persistence.postgres import (
    PostgresEngine,
    get_postgres_engine,
)

_ALLOWED_ENCODING = frozenset({"json", "msgpack", "null", "bytes", "bytearray"})
_MAX_LIST_SCAN = 5000


class DeepAgentsCheckpointScopeError(PermissionError):
    """Graph checkpoint identity or ownership is not authorized."""


class ScopedPostgresDeepAgentsSaver(BaseCheckpointSaver[str]):
    """Real LangGraph async saver bound to one governed Medusa run.

    Scope cannot be changed by graph-config fields. Client-provided thread
    IDs and checkpoint namespaces never convey tenant permissions.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        policy_decision_id: str,
        run_id: str,
        thread_id: str,
        postgres: PostgresEngine | None = None,
    ) -> None:
        super().__init__()
        values = (user_id, session_id, policy_decision_id, run_id, thread_id)
        if not tenant_id or any(not isinstance(v, str) or not v.strip() for v in values):
            raise DeepAgentsCheckpointScopeError(
                "A durable checkpoint requires trusted tenant, principal, session, policy, run and thread identity"
            )
        self._tenant_id = _canonical_tenant_id(tenant_id)
        self._user_id = user_id
        self._session_id = session_id
        self._policy_decision_id = policy_decision_id
        self._run_id = run_id
        self._thread_id = thread_id
        self._postgres = postgres or get_postgres_engine()

    @classmethod
    def for_authorized_execution(
        cls, execution: Any, *, thread_id: str,
        postgres: PostgresEngine | None = None,
    ) -> "ScopedPostgresDeepAgentsSaver":
        plan = execution.authorized_plan
        if not plan.matches_execution_scope(
            user_id=execution.user_id,
            tenant_id=execution.tenant_id,
            session_id=execution.session_id,
            policy_decision_id=execution.policy_decision_id,
        ):
            raise DeepAgentsCheckpointScopeError(
                "Deep Agents checkpoint execution scope does not match RuntimePolicy"
            )
        if not execution.trajectory_id:
            raise DeepAgentsCheckpointScopeError(
                "Checkpoint thread must belong to a durable Medusa run"
            )
        return cls(
            tenant_id=execution.tenant_id,
            user_id=execution.user_id,
            session_id=execution.session_id,
            policy_decision_id=execution.policy_decision_id,
            run_id=execution.trajectory_id,
            thread_id=thread_id,
            postgres=postgres,
        )

    async def _set_scope(self, session: Any) -> None:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": self._tenant_id},
        )

    def _scope(self, config: RunnableConfig | None) -> tuple[str, str | None]:
        options = (config or {}).get("configurable") or {}
        if not isinstance(options, Mapping):
            raise DeepAgentsCheckpointScopeError("Invalid checkpoint configuration")
        thread_id = options.get("thread_id", self._thread_id)
        if thread_id != self._thread_id:
            raise DeepAgentsCheckpointScopeError("Checkpoint thread does not belong to this run")
        namespace = options.get("checkpoint_ns") or ""
        checkpoint_id = options.get("checkpoint_id")
        if (
            not isinstance(namespace, str) or len(namespace) > 512
            or checkpoint_id is not None
            and (not isinstance(checkpoint_id, str) or len(checkpoint_id) > 256)
        ):
            raise DeepAgentsCheckpointScopeError("Invalid checkpoint namespace or ID")
        return namespace, checkpoint_id

    def _identity(self, namespace: str) -> dict[str, str]:
        return {
            "tenant_id": self._tenant_id,
            "user_id": self._user_id,
            "session_id": self._session_id,
            "policy_decision_id": self._policy_decision_id,
            "run_id": self._run_id,
            "thread_id": self._thread_id,
            "namespace": namespace,
        }

    def _serialize(self, value: Any) -> tuple[str, bytes]:
        encoding, data = self.serde.dumps_typed(value)
        if encoding not in _ALLOWED_ENCODING:
            raise ValueError("Unsafe LangGraph checkpoint serialization type")
        return encoding, data

    def _deserialize(self, encoding: Any, value: Any) -> Any:
        if encoding not in _ALLOWED_ENCODING:
            raise ValueError("Unsafe stored LangGraph checkpoint serialization type")
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise ValueError("Corrupt stored LangGraph checkpoint bytes")
        return self.serde.loads_typed((encoding, bytes(value)))

    @staticmethod
    def _config(thread_id: str, namespace: str, checkpoint_id: str) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput(
        self, config: RunnableConfig, checkpoint: Checkpoint,
        metadata: CheckpointMetadata, new_versions: ChannelVersions,
    ) -> RunnableConfig:
        del new_versions  # The complete typed checkpoint records channel versions.
        namespace, parent_id = self._scope(config)
        checkpoint_id = checkpoint.get("id")
        if not isinstance(checkpoint_id, str) or not 1 <= len(checkpoint_id) <= 256:
            raise ValueError("Checkpoint requires a valid LangGraph-generated ID")
        cp_type, cp_bytes = self._serialize(checkpoint)
        meta_type, meta_bytes = self._serialize(metadata)
        params: dict[str, Any] = {
            **self._identity(namespace),
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": parent_id,
            "checkpoint_encoding": cp_type,
            "checkpoint_bytes": cp_bytes,
            "metadata_encoding": meta_type,
            "metadata_bytes": meta_bytes,
        }
        async with self._postgres.get_async_session() as session:
            await self._set_scope(session)
            result = await session.execute(text("""
                INSERT INTO agent_medusa_deepagents_checkpoints (
                    tenant_id, user_id, session_id, policy_decision_id, run_id,
                    thread_id, checkpoint_ns, checkpoint_id,
                    parent_checkpoint_id, checkpoint_encoding, checkpoint_bytes,
                    metadata_encoding, metadata_bytes
                ) VALUES (
                    CAST(:tenant_id AS uuid), :user_id, :session_id,
                    :policy_decision_id, :run_id, :thread_id, :namespace,
                    :checkpoint_id, :parent_checkpoint_id,
                    :checkpoint_encoding, :checkpoint_bytes,
                    :metadata_encoding, :metadata_bytes
                )
                ON CONFLICT (
                    tenant_id, thread_id, checkpoint_ns, checkpoint_id
                ) DO UPDATE SET
                    parent_checkpoint_id = EXCLUDED.parent_checkpoint_id,
                    checkpoint_encoding = EXCLUDED.checkpoint_encoding,
                    checkpoint_bytes = EXCLUDED.checkpoint_bytes,
                    metadata_encoding = EXCLUDED.metadata_encoding,
                    metadata_bytes = EXCLUDED.metadata_bytes
                WHERE
                    agent_medusa_deepagents_checkpoints.user_id = EXCLUDED.user_id
                    AND agent_medusa_deepagents_checkpoints.session_id = EXCLUDED.session_id
                    AND agent_medusa_deepagents_checkpoints.policy_decision_id = EXCLUDED.policy_decision_id
                    AND agent_medusa_deepagents_checkpoints.run_id = EXCLUDED.run_id
            """), params)
            if result.rowcount != 1:
                raise DeepAgentsCheckpointScopeError(
                    "Checkpoint update rejected for an unauthorized principal or run"
                )
            await session.commit()
        return self._config(self._thread_id, namespace, checkpoint_id)

    async def aput_writes(
        self, config: RunnableConfig, writes: Sequence[tuple[str, Any]],
        task_id: str, task_path: str = "",
    ) -> None:
        namespace, checkpoint_id = self._scope(config)
        if not checkpoint_id or not task_id:
            raise ValueError("Checkpoint writes require checkpoint and task identity")
        if not isinstance(task_path, str) or len(task_path) > 2048:
            raise ValueError("Invalid LangGraph task path")
        async with self._postgres.get_async_session() as session:
            await self._set_scope(session)
            for idx, (channel, value) in enumerate(writes):
                if not isinstance(channel, str) or not channel:
                    raise ValueError("Invalid LangGraph checkpoint write channel")
                encoding, data = self._serialize(value)
                await session.execute(text("""
                    INSERT INTO agent_medusa_deepagents_checkpoint_writes (
                        tenant_id, thread_id, checkpoint_ns, checkpoint_id,
                        task_id, task_path, write_index, channel,
                        value_encoding, value_bytes
                    ) VALUES (
                        CAST(:tenant_id AS uuid), :thread_id, :namespace,
                        :checkpoint_id, :task_id, :task_path, :write_index,
                        :channel, :value_encoding, :value_bytes
                    )
                    ON CONFLICT (
                        tenant_id, thread_id, checkpoint_ns, checkpoint_id,
                        task_id, write_index
                    ) DO UPDATE SET
                        task_path = EXCLUDED.task_path,
                        channel = EXCLUDED.channel,
                        value_encoding = EXCLUDED.value_encoding,
                        value_bytes = EXCLUDED.value_bytes
                """), {
                    **self._identity(namespace),
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "task_path": task_path,
                    "write_index": WRITES_IDX_MAP.get(channel, idx),
                    "channel": channel,
                    "value_encoding": encoding,
                    "value_bytes": data,
                })
            await session.commit()

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        namespace, checkpoint_id = self._scope(config)
        params: dict[str, Any] = {
            **self._identity(namespace), "checkpoint_id": checkpoint_id,
        }
        async with self._postgres.get_async_session() as session:
            await self._set_scope(session)
            selected = await session.execute(text("""
                SELECT checkpoint_id, parent_checkpoint_id,
                       checkpoint_encoding, checkpoint_bytes,
                       metadata_encoding, metadata_bytes
                FROM agent_medusa_deepagents_checkpoints
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND user_id = :user_id
                  AND session_id = :session_id
                  AND policy_decision_id = :policy_decision_id
                  AND run_id = :run_id
                  AND thread_id = :thread_id
                  AND checkpoint_ns = :namespace
                  AND (:checkpoint_id IS NULL OR checkpoint_id = :checkpoint_id)
                ORDER BY checkpoint_id DESC LIMIT 1
            """), params)
            row = selected.mappings().first()
            if row is None:
                return None
            selected_id = row["checkpoint_id"]
            writes = await session.execute(text("""
                SELECT task_id, task_path, write_index, channel,
                       value_encoding, value_bytes
                FROM agent_medusa_deepagents_checkpoint_writes
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND thread_id = :thread_id
                  AND checkpoint_ns = :namespace
                  AND checkpoint_id = :checkpoint_id
                ORDER BY task_path, task_id, write_index
            """), {**params, "checkpoint_id": selected_id})
            ordered = sorted(
                [dict(item) for item in writes.mappings().all()],
                key=lambda item: writes_sort_key(
                    item["task_path"], item["task_id"], item["write_index"]
                ),
            )
        checkpoint = self._deserialize(
            row["checkpoint_encoding"], row["checkpoint_bytes"]
        )
        metadata = self._deserialize(
            row["metadata_encoding"], row["metadata_bytes"]
        )
        if not isinstance(checkpoint, dict) or not isinstance(metadata, dict):
            raise ValueError("Invalid persisted checkpoint structure")
        pending_writes = [
            (
                item["task_id"], item["channel"],
                self._deserialize(item["value_encoding"], item["value_bytes"]),
            )
            for item in ordered
        ]
        parent_id = row["parent_checkpoint_id"]
        parent_config = (
            self._config(self._thread_id, namespace, parent_id)
            if parent_id else None
        )
        return CheckpointTuple(
            config=self._config(self._thread_id, namespace, selected_id),
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    async def alist(
        self, config: RunnableConfig | None,
        *, filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        namespace, _ = self._scope(config)
        before_id = self._scope(before)[1] if before is not None else None
        if limit is not None and (not isinstance(limit, int) or not 1 <= limit <= _MAX_LIST_SCAN):
            raise ValueError("Checkpoint history limit must be 1-5000")
        async with self._postgres.get_async_session() as session:
            await self._set_scope(session)
            result = await session.execute(text("""
                SELECT checkpoint_id
                FROM agent_medusa_deepagents_checkpoints
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND user_id = :user_id AND session_id = :session_id
                  AND policy_decision_id = :policy_decision_id
                  AND run_id = :run_id AND thread_id = :thread_id
                  AND checkpoint_ns = :namespace
                  AND (:before_id IS NULL OR checkpoint_id < :before_id)
                ORDER BY checkpoint_id DESC
                LIMIT :scan_limit
            """), {
                **self._identity(namespace),
                "before_id": before_id,
                "scan_limit": _MAX_LIST_SCAN + 1,
            })
            ids = [row["checkpoint_id"] for row in result.mappings().all()]
        if len(ids) > _MAX_LIST_SCAN:
            raise ValueError("Checkpoint history exceeds bounded scan limit")
        emitted = 0
        for checkpoint_id in ids:
            item = await self.aget_tuple(
                self._config(self._thread_id, namespace, checkpoint_id)
            )
            if item is None:
                continue
            if filter and any(item.metadata.get(key) != value
                              for key, value in filter.items()):
                continue
            yield item
            emitted += 1
            if limit is not None and emitted >= limit:
                break

    async def adelete_thread(self, thread_id: str) -> None:
        if thread_id != self._thread_id:
            raise DeepAgentsCheckpointScopeError(
                "Cannot delete checkpoints belonging to another thread"
            )
        async with self._postgres.get_async_session() as session:
            await self._set_scope(session)
            await session.execute(text("""
                DELETE FROM agent_medusa_deepagents_checkpoints
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND user_id = :user_id AND session_id = :session_id
                  AND policy_decision_id = :policy_decision_id
                  AND run_id = :run_id AND thread_id = :thread_id
            """), self._identity(""))
            await session.commit()


def trusted_thread_id(execution: Any) -> str:
    """Stable opaque graph identity bound to canonical tenant/run/specialist."""
    if not execution.tenant_id or not execution.session_id:
        raise DeepAgentsCheckpointScopeError("Missing tenant or session")
    if not execution.trajectory_id or not execution.step_id:
        raise DeepAgentsCheckpointScopeError("Missing Medusa run or step")
    value = ":".join((
        execution.tenant_id, execution.user_id, execution.session_id,
        execution.policy_decision_id, execution.trajectory_id, execution.step_id,
    ))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
