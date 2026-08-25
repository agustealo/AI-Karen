from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any


@dataclass(slots=True)
class CognitivePolicySnapshot:
    """Read-only semantic snapshot of cognitive policy values.

    Core consumers should depend on this surface only.  It decouples
    Core from config-loader and environment infrastructure.
    """
    schema_version: str = "1"
    policy_version: str = "cognitive-v1"
    scoring_version: str = "weighted-v1"
    updated_at: str = ""

    meta: dict[str, Any] = field(default_factory=dict)
    belief: dict[str, Any] = field(default_factory=dict)
    salience: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    behavior: dict[str, Any] = field(default_factory=dict)
    learning: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        section_data = getattr(self, section, None)
        if isinstance(section_data, dict):
            return section_data.get(key, default)
        return default

    def meta_get(self, key: str, default: Any = None) -> Any:
        return self.meta.get(key, default)

    def belief_get(self, key: str, default: Any = None) -> Any:
        return self.belief.get(key, default)

    def salience_get(self, key: str, default: Any = None) -> Any:
        return self.salience.get(key, default)

    def context_get(self, key: str, default: Any = None) -> Any:
        return self.context.get(key, default)

    def behavior_get(self, key: str, default: Any = None) -> Any:
        return self.behavior.get(key, default)

    def learning_get(self, key: str, default: Any = None) -> Any:
        return self.learning.get(key, default)

    def memory_get(self, key: str, default: Any = None) -> Any:
        return self.memory.get(key, default)


def _dataclass_to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        result = {}
        for f in fields(obj):
            val = getattr(obj, f.name)
            result[f.name] = _dataclass_to_dict(val)
        return result
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dataclass_to_dict(v) for v in obj]
    return obj


def build_snapshot(config: Any) -> CognitivePolicySnapshot:
    data = _dataclass_to_dict(config)
    return CognitivePolicySnapshot(
        schema_version=data.get("schema_version", "1"),
        policy_version=data.get("policy_version", "cognitive-v1"),
        scoring_version=data.get("scoring_version", "weighted-v1"),
        updated_at=data.get("updated_at", ""),
        meta=data.get("meta", {}),
        belief=data.get("belief", {}),
        salience=data.get("salience", {}),
        context=data.get("context", {}),
        behavior=data.get("behavior", {}),
        learning=data.get("learning", {}),
        memory=data.get("memory", {}),
    )
