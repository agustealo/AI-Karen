from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class LeanGraphConfig:
    graph_relationships_enabled: bool = True
    graph_backend: str = "kuzu"
    graph_db_path: str = "./data/memory/leangraph"
    graph_uri: str | None = None
    graph_user: str | None = None
    graph_password: str | None = None
    graph_projection_timeout_ms: int = 1500
    graph_max_entities_per_event: int = 50
    graph_max_edges_per_event: int = 200
    graph_enable_contradiction_edges: bool = True
    graph_enable_reinforcement_edges: bool = True
    graph_enable_supersedes_edges: bool = True
    graph_enable_entity_mentions: bool = True

    @classmethod
    def from_env(cls) -> LeanGraphConfig:
        return cls(
            graph_relationships_enabled=_bool("KARI_GRAPH_RELATIONSHIPS_ENABLED", True),
            graph_backend=os.getenv("KARI_GRAPH_BACKEND", "kuzu"),
            graph_db_path=os.getenv("KARI_GRAPH_DB_PATH", "./data/memory/leangraph"),
            graph_uri=os.getenv("KARI_GRAPH_URI"),
            graph_user=os.getenv("KARI_GRAPH_USER"),
            graph_password=os.getenv("KARI_GRAPH_PASSWORD"),
            graph_projection_timeout_ms=_int("KARI_GRAPH_PROJECTION_TIMEOUT_MS", 1500),
            graph_max_entities_per_event=_int("KARI_GRAPH_MAX_ENTITIES_PER_EVENT", 50),
            graph_max_edges_per_event=_int("KARI_GRAPH_MAX_EDGES_PER_EVENT", 200),
            graph_enable_contradiction_edges=_bool("KARI_GRAPH_ENABLE_CONTRADICTION_EDGES", True),
            graph_enable_reinforcement_edges=_bool("KARI_GRAPH_ENABLE_REINFORCEMENT_EDGES", True),
            graph_enable_supersedes_edges=_bool("KARI_GRAPH_ENABLE_SUPERSEDES_EDGES", True),
            graph_enable_entity_mentions=_bool("KARI_GRAPH_ENABLE_ENTITY_MENTIONS", True),
        )


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
