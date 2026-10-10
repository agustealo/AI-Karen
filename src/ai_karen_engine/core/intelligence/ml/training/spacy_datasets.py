"""Strict, engine-specific spaCy dataset contracts.

Text categorization rows: {"example_id": "...", "text": "...", "label": "..."}
NER rows: {"example_id": "...", "text": "...", "entities": [[start, end, label], ...]}
These are input contracts only. No training executor is implied.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def validate_spacy_jsonl(path: Path, *, max_samples: int = 10000) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Dataset must be a regular versioned JSONL file")
    if max_samples < 1:
        raise ValueError("Sample limit must be positive")
    counts: Counter[str] = Counter()
    examples = 0
    mode: str | None = None
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            if examples >= max_samples:
                break
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("row must be an object")
                if not isinstance(record.get("example_id"), str) or not record["example_id"]:
                    raise ValueError("example_id must be nonempty")
                value = record.get("text")
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("text must be nonempty")
                row_mode = "ner" if "entities" in record else "textcat"
                if mode is not None and row_mode != mode:
                    raise ValueError("Cannot mix NER and text categorization records")
                mode = row_mode
                if mode == "textcat":
                    label = record.get("label")
                    if not isinstance(label, str) or not label.strip():
                        raise ValueError("label must be nonempty")
                    counts[label] += 1
                else:
                    spans = record["entities"]
                    if not isinstance(spans, list):
                        raise ValueError("entities must be a list")
                    prior_end = -1
                    for span in sorted(spans, key=lambda item: item[0] if isinstance(item, list) and item else -1):
                        if not isinstance(span, list) or len(span) != 3:
                            raise ValueError("entity spans require [start,end,label]")
                        start, end, label = span
                        if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(value)):
                            raise ValueError("entity offsets must fit inside the text")
                        if not isinstance(label, str) or not label.strip():
                            raise ValueError("entity label must be nonempty")
                        if start < prior_end:
                            raise ValueError("overlapping entity spans are not supported")
                        prior_end = end
                        counts[label] += 1
                examples += 1
            except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid spaCy row {line_number}: {exc}") from exc
    if examples < 10:
        raise ValueError("At least ten labeled examples are required")
    if mode == "textcat" and (len(counts) < 2 or min(counts.values()) < 2):
        raise ValueError("Text categorization requires at least two examples per class and two classes")
    if mode == "ner" and not counts:
        raise ValueError("NER needs at least one labeled entity")
    return {"mode": mode, "examples_scanned": examples, "class_counts": dict(counts)}
