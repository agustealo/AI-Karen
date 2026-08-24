from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ai_karen_engine.core.runtime.contracts import ExecutionTopology

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopologyTrainingExample:
    example_id: str
    feature_version: str
    features: dict[str, float | int | bool | str]
    target: str

    @staticmethod
    def from_execution_topology(
        example_id: str,
        feature_version: str,
        features: dict[str, float | int | bool | str],
        topology: ExecutionTopology,
    ) -> TopologyTrainingExample:
        return TopologyTrainingExample(
            example_id=example_id,
            feature_version=feature_version,
            features=features,
            target=topology.value,
        )

    def target_enum(self) -> ExecutionTopology:
        return ExecutionTopology(self.target)


class TrainingDatasetProvider(Protocol):
    def load(self, dataset_version: str) -> list[TopologyTrainingExample]:
        ...


class FixtureTrainingDatasetProvider:
    def __init__(self, examples: list[TopologyTrainingExample]) -> None:
        self._examples = examples

    def load(self, dataset_version: str) -> list[TopologyTrainingExample]:
        return list(self._examples)


class JsonlTrainingDatasetProvider:
    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir)

    def load(self, dataset_version: str) -> list[TopologyTrainingExample]:
        path = self._root_dir / f"{dataset_version}.jsonl"
        if not path.exists():
            logger.warning("Dataset file not found: %s", path)
            return []
        examples: list[TopologyTrainingExample] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                examples.append(TopologyTrainingExample(**data))
        return examples
