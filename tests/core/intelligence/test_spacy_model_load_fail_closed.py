"""Model deserialization failures must not crash the API import path."""

from unittest.mock import patch

import pytest

from ai_karen_engine.core.intelligence.linguistic import spacy_analyzer
from ai_karen_engine.core.intelligence.linguistic.spacy_config import SpacyConfig


@pytest.mark.parametrize("exc", [OverflowError("invalid tokenizer"), ValueError("invalid model")])
def test_corrupt_spacy_model_enters_observable_degraded_mode(tmp_path, exc) -> None:
    config = SpacyConfig(local_model_root=str(tmp_path), download_missing=False)
    with patch.object(spacy_analyzer, "SPACY_AVAILABLE", True), patch.object(
        spacy_analyzer, "spacy"
    ) as fake_spacy:
        fake_spacy.load.side_effect = exc
        analyzer = spacy_analyzer.SpacyAnalyzer(config)
    assert analyzer.nlp is None
    assert analyzer.fallback_mode is True
    assert analyzer._error_count == 1
    assert type(exc).__name__ in (analyzer._last_error or "")
