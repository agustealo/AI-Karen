from __future__ import annotations

import json
import pytest

from ai_karen_engine.core.intelligence.ml.training.csv_adapter import convert_csv_to_jsonl
from ai_karen_engine.core.intelligence.ml.training.dataset_import import DatasetImportError


def test_csv_mapping_is_explicit_and_preserves_unicode():
    content = "input,class\ncafé,positive\ntea,negative\n".encode("utf-8")
    stream = convert_csv_to_jsonl(
        content, column_mapping={"input": "text", "class": "label"},
    )
    rows = [json.loads(line) for line in stream.read().splitlines()]
    assert rows == [{"text": "café", "label": "positive"}, {"text": "tea", "label": "negative"}]


@pytest.mark.parametrize("content", [
    b"input,class\none\n",
    b"input,class\none,positive,extra\n",
    b"input,input\none,two\n",
    b"input,class\n",
    b"input,class\n\"unterminated,positive\n",
])
def test_csv_rejects_malformed_records(content):
    with pytest.raises(DatasetImportError):
        convert_csv_to_jsonl(content, column_mapping={"input": "text"})


def test_csv_rejects_implicit_mapping():
    with pytest.raises(DatasetImportError, match="mapping"):
        convert_csv_to_jsonl(b"text\nsample\n", column_mapping={})


def test_csv_rejects_missing_column_and_duplicate_target():
    content = b"input,class\none,positive\n"
    with pytest.raises(DatasetImportError, match="missing headers"):
        convert_csv_to_jsonl(content, column_mapping={"missing": "text"})
    with pytest.raises(DatasetImportError, match="Duplicate destination"):
        convert_csv_to_jsonl(content, column_mapping={"input": "text", "class": "text"})
