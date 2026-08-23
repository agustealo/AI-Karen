from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import (
    Prediction,
    Predictor,
)

logger = logging.getLogger(__name__)


class BasePredictor(Predictor):
    def __init__(self, ml_runtime: Any = None) -> None:
        self._ml_runtime = ml_runtime

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        raise NotImplementedError

    async def predict_batch(self, features_list: list[IntelligenceFeatures]) -> list[Prediction]:
        return [await self.predict(f) for f in features_list]

    async def health(self) -> dict[str, Any]:
        return {"status": "ready"}

    async def metadata(self) -> dict[str, Any]:
        return {"predictor": self.__class__.__name__}
