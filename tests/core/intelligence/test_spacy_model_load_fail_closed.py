"""Model deserialization failures must not crash the API import path."""

from unittest.mock import Mock, patch

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


def _mock_spacy_with_pipeline(pipeline):
    # Keep the actual compatibility parser: the test must exercise real
    # version constraints, not an always-true mocked model health result.
    from spacy.util import is_compatible_version

    fake = Mock()
    fake.__version__ = "3.8.16"
    fake.util.is_compatible_version = is_compatible_version
    fake.load.return_value = pipeline
    return fake


def test_stale_bind_mounted_spacy_pipeline_is_skipped_without_overwrite(tmp_path) -> None:
    from json import dumps

    config = SpacyConfig(local_model_root=str(tmp_path), download_missing=False)
    local = tmp_path / config.model_name
    local.mkdir()
    (local / "meta.json").write_text(
        dumps({"spacy_version": ">=3.7.0,<3.8.0"}), encoding="utf-8"
    )
    old_metadata = (local / "meta.json").read_bytes()
    pipeline = Mock()
    pipeline.meta = {"spacy_version": ">=3.8.0,<3.9.0"}
    fake = _mock_spacy_with_pipeline(pipeline)

    with patch.object(spacy_analyzer, "SPACY_AVAILABLE", True), patch.object(
        spacy_analyzer, "spacy", fake
    ):
        analyzer = spacy_analyzer.SpacyAnalyzer(config)

    fake.load.assert_called_once_with(config.model_name, disable=config.disabled_components)
    pipeline.to_disk.assert_not_called()
    assert (local / "meta.json").read_bytes() == old_metadata
    assert analyzer.nlp is pipeline
    assert analyzer.fallback_mode is False


def test_compatible_local_spacy_pipeline_is_preferred(tmp_path) -> None:
    from json import dumps

    config = SpacyConfig(local_model_root=str(tmp_path), download_missing=False)
    local = tmp_path / config.model_name
    local.mkdir()
    (local / "meta.json").write_text(
        dumps({"spacy_version": ">=3.8.0,<3.9.0"}), encoding="utf-8"
    )
    pipeline = Mock()
    pipeline.meta = {"spacy_version": ">=3.8.0,<3.9.0"}
    fake = _mock_spacy_with_pipeline(pipeline)

    with patch.object(spacy_analyzer, "SPACY_AVAILABLE", True), patch.object(
        spacy_analyzer, "spacy", fake
    ):
        analyzer = spacy_analyzer.SpacyAnalyzer(config)

    fake.load.assert_called_once_with(local, disable=config.disabled_components)
    pipeline.to_disk.assert_not_called()
    assert analyzer.nlp is pipeline
    assert analyzer.fallback_mode is False


def test_incompatible_packaged_spacy_pipeline_fails_closed(tmp_path) -> None:
    config = SpacyConfig(local_model_root=str(tmp_path), download_missing=False)
    pipeline = Mock()
    pipeline.meta = {"spacy_version": ">=3.7.0,<3.8.0"}
    fake = _mock_spacy_with_pipeline(pipeline)

    with patch.object(spacy_analyzer, "SPACY_AVAILABLE", True), patch.object(
        spacy_analyzer, "spacy", fake
    ):
        analyzer = spacy_analyzer.SpacyAnalyzer(config)

    assert analyzer.nlp is None
    assert analyzer.fallback_mode is True
    assert analyzer._last_error == "incompatible_spacy_pipeline"
    pipeline.to_disk.assert_not_called()
