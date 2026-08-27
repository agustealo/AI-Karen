"""Projection-only AG-UI adapter for canonical memory runtime data.

This module intentionally contains no memory classification, semantic ranking,
relationship inference, embedding/NLP calls, persistence policy, or retrieval
fallbacks. NeuroRecall and the canonical memory runtime own those decisions.
The AG-UI adapter only projects returned memory records into visualization
shapes, applies user-selected display filters, and computes display aggregates.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.core.memory.memory_runtime_manager import (
    get_metrics,
    recall_context,
    update_memory,
)

logger = logging.getLogger("kari.memory.ag_ui_manager")


@dataclass
class MemoryGridRow:
    """Presentation projection for an authoritative memory record."""

    id: str
    content: str
    type: str
    confidence: Optional[float]
    last_accessed: Optional[str]
    relevance_score: Optional[float]
    semantic_cluster: Optional[str]
    relationships: List[str]
    timestamp: Optional[float]
    user_id: str
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None


@dataclass
class MemoryNetworkNode:
    """Presentation node derived only from projected memory metadata."""

    id: str
    label: str
    type: str
    confidence: Optional[float]
    cluster: Optional[str]
    size: int
    color: str


@dataclass
class MemoryNetworkEdge:
    """Presentation edge for an authoritative relationship reference."""

    source: str
    target: str
    weight: float
    type: str
    label: str


@dataclass
class MemoryAnalytics:
    """Display aggregates computed from canonical memory records."""

    total_memories: int
    memories_by_type: Dict[str, int]
    memories_by_cluster: Dict[str, int]
    confidence_distribution: List[Dict[str, Union[str, int]]]
    access_patterns: List[Dict[str, Union[str, int]]]
    relationship_stats: Dict[str, Union[int, float]]
    runtime_metrics: Dict[str, Any]


class AGUIMemoryManager:
    """AG-UI presenter over the canonical memory runtime.

    The manager preserves the historical AG-UI method surface while delegating
    retrieval and mutation to the canonical memory runtime. It never changes
    recall order or synthesizes cognitive metadata when the backend did not
    provide it.
    """

    _CLUSTER_COLORS = (
        "#FF6B6B",
        "#4ECDC4",
        "#45B7D1",
        "#96CEB4",
        "#FFEAA7",
        "#DDA0DD",
        "#98D8C8",
    )

    def __init__(self) -> None:
        self._memory_cache: Dict[str, List[MemoryGridRow]] = {}

    @staticmethod
    def _scope(user_ctx: Dict[str, Any]) -> tuple[str, str]:
        user_id = str(user_ctx.get("user_id") or user_ctx.get("id") or "").strip()
        tenant_id = str(user_ctx.get("tenant_id") or "").strip()
        if not user_id or not tenant_id:
            raise ValueError("user_id and tenant_id are required for AG-UI memory views")
        return user_id, tenant_id

    @staticmethod
    def _metadata(memory: Dict[str, Any]) -> Dict[str, Any]:
        metadata = memory.get("metadata")
        return dict(metadata) if isinstance(metadata, dict) else {}

    @staticmethod
    def _optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp_to_iso(value: Any) -> Optional[str]:
        timestamp = AGUIMemoryManager._optional_float(value)
        if timestamp is None:
            return None
        try:
            return datetime.fromtimestamp(timestamp).isoformat()
        except (OSError, OverflowError, ValueError):
            return None

    @staticmethod
    def _relationships(metadata: Dict[str, Any]) -> List[str]:
        relationships = metadata.get("relationships")
        if not isinstance(relationships, list):
            return []
        return [str(item) for item in relationships if item is not None]

    def _project_memory(
        self,
        memory: Dict[str, Any],
        *,
        user_id: str,
        tenant_id: str,
    ) -> MemoryGridRow:
        metadata = self._metadata(memory)
        content = str(memory.get("content") or memory.get("result") or "")
        memory_type = str(
            memory.get("memory_type") or metadata.get("memory_type") or "unknown"
        )
        confidence = self._optional_float(
            memory.get("confidence", metadata.get("confidence"))
        )
        relevance = self._optional_float(
            memory.get("similarity_score", memory.get("relevance_score"))
        )
        timestamp = self._optional_float(memory.get("timestamp"))
        cluster_value = metadata.get("semantic_cluster", metadata.get("cluster"))
        cluster = str(cluster_value) if cluster_value is not None else None

        return MemoryGridRow(
            id=str(memory.get("id") or ""),
            content=content,
            type=memory_type,
            confidence=confidence,
            last_accessed=self._timestamp_to_iso(timestamp),
            relevance_score=relevance,
            semantic_cluster=cluster,
            relationships=self._relationships(metadata),
            timestamp=timestamp,
            user_id=user_id,
            session_id=(
                str(memory.get("session_id") or metadata.get("session_id"))
                if memory.get("session_id") or metadata.get("session_id")
                else None
            ),
            tenant_id=tenant_id,
        )

    @staticmethod
    def _passes_filters(
        memory: MemoryGridRow, filters: Optional[Dict[str, Any]]
    ) -> bool:
        """Apply display-only filters without changing backend ranking."""

        if not filters:
            return True

        for field, condition in filters.items():
            if field == "type" and condition != memory.type:
                return False
            if field == "cluster" and condition != memory.semantic_cluster:
                return False
            if field == "confidence_min":
                if memory.confidence is None or memory.confidence < float(condition):
                    return False
            if field == "confidence_max":
                if memory.confidence is None or memory.confidence > float(condition):
                    return False
        return True

    async def _recall_rows(
        self,
        user_ctx: Dict[str, Any],
        *,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryGridRow]:
        user_id, tenant_id = self._scope(user_ctx)
        response = await recall_context(
            user_id=user_id,
            tenant_id=tenant_id,
            query=query,
            top_k=max(1, int(limit)),
            conversation_id=user_ctx.get("conversation_id"),
            session_id=user_ctx.get("session_id"),
            correlation_id=user_ctx.get("correlation_id"),
            request_id=user_ctx.get("request_id"),
        )
        raw_results = response.get("results", []) if isinstance(response, dict) else []
        rows = [
            self._project_memory(memory, user_id=user_id, tenant_id=tenant_id)
            for memory in raw_results
            if isinstance(memory, dict)
        ]
        filtered = [row for row in rows if self._passes_filters(row, filters)]
        self._memory_cache[f"{user_id}:{tenant_id}"] = filtered
        return filtered

    async def get_memory_grid_data(
        self,
        user_ctx: Dict[str, Any],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Project canonical recall results into AG-UI grid rows."""

        try:
            rows = await self._recall_rows(
                user_ctx,
                query="",
                limit=limit,
                filters=filters,
            )
            return [asdict(row) for row in rows]
        except ValueError as exc:
            logger.warning("AG-UI memory grid rejected invalid scope: %s", exc)
            return []
        except Exception:
            logger.exception("AG-UI memory grid projection failed")
            return []

    async def search_memories(
        self,
        user_ctx: Dict[str, Any],
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Display canonical recall results in backend-provided order."""

        try:
            rows = await self._recall_rows(
                user_ctx,
                query=query,
                limit=limit,
                filters=filters,
            )
            return [asdict(row) for row in rows]
        except ValueError as exc:
            logger.warning("AG-UI memory search rejected invalid scope: %s", exc)
            return []
        except Exception:
            logger.exception("AG-UI memory search projection failed")
            return []

    async def get_memory_network_data(
        self, user_ctx: Dict[str, Any], max_nodes: int = 50
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Render only relationships already supplied by canonical memory metadata."""

        grid = await self.get_memory_grid_data(user_ctx, limit=max_nodes)
        rows = [MemoryGridRow(**item) for item in grid]
        node_ids = {row.id for row in rows if row.id}
        cluster_indexes: Dict[str, int] = {}
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        for row in rows:
            cluster_key = row.semantic_cluster or "unclassified"
            if cluster_key not in cluster_indexes:
                cluster_indexes[cluster_key] = len(cluster_indexes)
            confidence = row.confidence
            size = 8 if confidence is None else max(5, int(confidence * 20) + 5)
            nodes.append(
                asdict(
                    MemoryNetworkNode(
                        id=row.id,
                        label=row.content[:50] + ("..." if len(row.content) > 50 else ""),
                        type=row.type,
                        confidence=confidence,
                        cluster=row.semantic_cluster,
                        size=size,
                        color=self._CLUSTER_COLORS[
                            cluster_indexes[cluster_key] % len(self._CLUSTER_COLORS)
                        ],
                    )
                )
            )

        for row in rows:
            if not row.id:
                continue
            for related_id in row.relationships:
                if related_id not in node_ids:
                    continue
                edges.append(
                    asdict(
                        MemoryNetworkEdge(
                            source=row.id,
                            target=related_id,
                            weight=1.0,
                            type="declared",
                            label="related",
                        )
                    )
                )

        return {"nodes": nodes, "edges": edges}

    async def get_memory_analytics(
        self, user_ctx: Dict[str, Any], timeframe_days: int = 30
    ) -> Dict[str, Any]:
        """Compute display aggregates without deriving cognitive labels."""

        grid = await self.get_memory_grid_data(user_ctx, limit=1000)
        rows = [MemoryGridRow(**item) for item in grid]
        cutoff = datetime.now() - timedelta(days=max(1, int(timeframe_days)))
        recent = [
            row
            for row in rows
            if row.timestamp is not None
            and datetime.fromtimestamp(row.timestamp) >= cutoff
        ]

        memories_by_type: Dict[str, int] = {}
        memories_by_cluster: Dict[str, int] = {}
        for row in recent:
            memories_by_type[row.type] = memories_by_type.get(row.type, 0) + 1
            cluster = row.semantic_cluster or "unclassified"
            memories_by_cluster[cluster] = memories_by_cluster.get(cluster, 0) + 1

        confidence_bins = {
            "0.0-0.2": 0,
            "0.2-0.4": 0,
            "0.4-0.6": 0,
            "0.6-0.8": 0,
            "0.8-1.0": 0,
        }
        for row in recent:
            if row.confidence is None:
                continue
            if row.confidence < 0.2:
                confidence_bins["0.0-0.2"] += 1
            elif row.confidence < 0.4:
                confidence_bins["0.2-0.4"] += 1
            elif row.confidence < 0.6:
                confidence_bins["0.4-0.6"] += 1
            elif row.confidence < 0.8:
                confidence_bins["0.6-0.8"] += 1
            else:
                confidence_bins["0.8-1.0"] += 1

        daily_counts: Dict[str, int] = {}
        for row in recent:
            if row.timestamp is None:
                continue
            date_key = datetime.fromtimestamp(row.timestamp).strftime("%Y-%m-%d")
            daily_counts[date_key] = daily_counts.get(date_key, 0) + 1

        total_relationships = sum(len(row.relationships) for row in recent)
        connected = sum(1 for row in recent if row.relationships)
        analytics = MemoryAnalytics(
            total_memories=len(recent),
            memories_by_type=memories_by_type,
            memories_by_cluster=memories_by_cluster,
            confidence_distribution=[
                {"range": key, "count": value}
                for key, value in confidence_bins.items()
            ],
            access_patterns=[
                {"date": key, "count": value}
                for key, value in sorted(daily_counts.items())
            ],
            relationship_stats={
                "total_relationships": total_relationships,
                "connected_memories": connected,
                "isolated_memories": len(recent) - connected,
                "avg_relationships": (
                    total_relationships / len(recent) if recent else 0.0
                ),
            },
            runtime_metrics=dict(get_metrics()),
        )
        return asdict(analytics)

    async def update_memory_with_metadata(
        self,
        user_ctx: Dict[str, Any],
        query: str,
        result: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Delegate mutation without adding UI-generated cognitive metadata."""

        try:
            user_id, tenant_id = self._scope(user_ctx)
            updates = {
                "result": result,
                "metadata": dict(metadata or {}),
                "tenant_id": tenant_id,
                "user_id": user_id,
            }
            response = await update_memory(
                memory_id=query,
                updates=updates,
                user_ctx=user_ctx,
            )
            success = bool(
                isinstance(response, dict)
                and (
                    response.get("success") is True
                    or response.get("status") in {"success", "updated", "ok"}
                )
            )
            if success:
                self._memory_cache.pop(f"{user_id}:{tenant_id}", None)
            return success
        except ValueError as exc:
            logger.warning("AG-UI memory update rejected invalid scope: %s", exc)
            return False
        except Exception:
            logger.exception("AG-UI delegated memory update failed")
            return False


__all__ = [
    "AGUIMemoryManager",
    "MemoryGridRow",
    "MemoryNetworkNode",
    "MemoryNetworkEdge",
    "MemoryAnalytics",
]
