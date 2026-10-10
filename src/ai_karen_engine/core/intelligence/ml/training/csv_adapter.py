"""Validated CSV-to-JSONL adapter for the canonical immutable dataset importer.

This adapter only converts structured records. The existing importer owns
tenant storage, immutable publication, size limits and content hashing.
"""
from __future__ import annotations

import csv
import io
import json

from ai_karen_engine.core.intelligence.ml.training.dataset_import import DatasetImportError

_MAX_CSV_BYTES = 16 * 1024 * 1024
_MAX_RECORDS = 100_000
_MAX_COLUMNS = 256


def convert_csv_to_jsonl(
    content: bytes, *, column_mapping: dict[str, str], delimiter: str = ","
) -> io.BytesIO:
    """Map CSV headers to the task's JSONL fields; never infer labels."""
    if not content or len(content) > _MAX_CSV_BYTES:
        raise DatasetImportError("CSV is empty or exceeds the import limit")
    if delimiter not in {",", ";", "\t"}:
        raise DatasetImportError("Unsupported CSV delimiter")
    if not column_mapping or len(column_mapping) > _MAX_COLUMNS:
        raise DatasetImportError("A bounded explicit column mapping is required")
    if any(not key or not value for key, value in column_mapping.items()):
        raise DatasetImportError("CSV mapping keys and destination fields are required")
    if len(set(column_mapping.values())) != len(column_mapping):
        raise DatasetImportError("Duplicate destination column mapping")
    try:
        decoded = content.decode("utf-8-sig")
        source = csv.DictReader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
        headers = source.fieldnames
        if not headers or len(headers) > _MAX_COLUMNS or len(headers) != len(set(headers)):
            raise DatasetImportError("CSV headers missing, duplicated or excessive")
        if any(column not in headers for column in column_mapping):
            raise DatasetImportError("CSV mapping references missing headers")
        output = io.BytesIO()
        count = 0
        for line in source:
            count += 1
            if count > _MAX_RECORDS:
                raise DatasetImportError("CSV record limit exceeded")
            if None in line or any(value is None for value in line.values()):
                raise DatasetImportError("CSV row does not match header structure")
            mapped = {destination: line[column] for column, destination in column_mapping.items()}
            output.write((json.dumps(mapped, ensure_ascii=False) + "\n").encode("utf-8"))
        if not count:
            raise DatasetImportError("CSV has no data rows")
        output.seek(0)
        return output
    except (UnicodeDecodeError, csv.Error) as exc:
        raise DatasetImportError("CSV encoding or quoting is invalid") from exc
