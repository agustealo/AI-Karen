"""Verified tenant-scoped spaCy inference for candidate evaluation and promoted models.

Text classification and NER have different output contracts. NER never fabricates
a single-class probability or enters the numeric-feature classifier path.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry


class RegistryBackedSpacyPredictor:
    def __init__(self, *, registry: MLModelRegistry | None = None) -> None:
        self.registry = registry or MLModelRegistry()

    def _verified(self, *, model_id: str, tenant_id: str, allow_candidate: bool) -> MLModelManifest:
        if not tenant_id or tenant_id == "default":
            raise PermissionError("Explicit tenant scope required")
        prefix = "tenant-" + hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16] + "-"
        if not model_id.startswith(prefix):
            raise PermissionError("Model is outside tenant scope")
        manifest = self.registry.get(model_id)
        allowed = {ModelStatus.ACTIVE.value}
        if allow_candidate:
            allowed.add(ModelStatus.CANDIDATE.value)
        if manifest is None or manifest.status not in allowed or manifest.architecture != "spacy":
            raise ValueError("Requested spaCy model is not eligible")
        if not manifest.artifact_hash or not self.registry.validate_artifact(manifest):
            raise ValueError("Model artifact integrity check failed")
        return manifest

    def predict_text(
        self, *, model_id: str, tenant_id: str, text: str,
        allow_candidate: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Nonempty text required")
        manifest = self._verified(
            model_id=model_id, tenant_id=tenant_id, allow_candidate=allow_candidate,
        )
        import spacy
        nlp = spacy.load(Path(manifest.artifact_path))
        expected_mode = manifest.metrics.get("mode")
        if expected_mode not in {"textcat", "ner"} or expected_mode not in nlp.pipe_names:
            raise ValueError("spaCy pipeline does not match signed manifest mode")
        doc = nlp(text)
        if expected_mode == "textcat":
            scores = {label: float(value) for label, value in doc.cats.items()}
            if not scores:
                raise ValueError("No classification scores returned")
            label = max(scores, key=scores.get)
            return {
                "mode": "textcat", "label": label, "confidence": scores[label],
                "scores": scores, "model_id": manifest.model_id,
                "model_version": manifest.model_version,
            }
        return {
            "mode": "ner", "entities": [
                {"start": ent.start_char, "end": ent.end_char,
                 "label": ent.label_, "text": ent.text}
                for ent in doc.ents
            ], "model_id": manifest.model_id, "model_version": manifest.model_version,
        }
