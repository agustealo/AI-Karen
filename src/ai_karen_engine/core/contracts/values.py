"""Shared structured-value contracts for cognitive domain boundaries.

These aliases replace unconstrained ``Any`` on semantic fields while keeping
metadata/adaptation bags free to use ``Any`` where interoperability requires it.
"""

from __future__ import annotations

from typing import TypeAlias, Union


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = Union[
    JsonScalar,
    list["JsonValue"],
    dict[str, "JsonValue"],
]
JsonMap: TypeAlias = dict[str, JsonValue]

__all__ = ["JsonMap", "JsonScalar", "JsonValue"]
