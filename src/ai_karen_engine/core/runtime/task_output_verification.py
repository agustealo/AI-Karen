"""Runtime-owned deterministic verification of saved-task output contracts.

A passing result means the actual ChatRuntime structured_content conforms to a
creator-defined schema. It NEVER proves external work or authorizes completion.
Only the already-executed runtime result may be evaluated; no plugin is invoked.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class OutputVerificationContractError(ValueError):
    """Invalid or unsafe saved-task verification contract."""


MAX_SCHEMA_BYTES = 8192
MAX_OUTPUT_BYTES = 262144
MAX_DEPTH = 12
MAX_SCHEMA_NODES = 256
_ALLOWED = {
    "$schema", "type", "properties", "required", "items", "additionalProperties",
    "enum", "const", "minLength", "maxLength", "minimum", "maximum", "minItems",
    "maxItems", "minProperties", "maxProperties", "allOf", "anyOf", "oneOf",
    "not", "description", "title",
}
# $ref, pattern, remote retrieval, schema extensions and format checking are
# disallowed to keep evaluation deterministic, bounded and network-free.


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def validate_contract(value: Any) -> dict[str, Any]:
    """Validate the complete safe subset before saving a task definition."""
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict) or set(value) != {"version", "schema"}:
        raise OutputVerificationContractError("Expected version and schema only")
    if value["version"] != "structured-output.v1":
        raise OutputVerificationContractError("Unsupported output verification version")
    schema = value["schema"]
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise OutputVerificationContractError("Top-level schema must be an object")
    try:
        if len(_canonical(value).encode("utf-8")) > MAX_SCHEMA_BYTES:
            raise OutputVerificationContractError("Verification schema exceeds size limit")
    except (TypeError, ValueError, OverflowError) as exc:
        raise OutputVerificationContractError("Verification contract must be JSON") from exc

    count = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if count > MAX_SCHEMA_NODES or depth > MAX_DEPTH:
            raise OutputVerificationContractError("Verification schema exceeds complexity limit")
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            raise OutputVerificationContractError("Invalid nested verification schema")
        forbidden = set(node) - _ALLOWED
        if forbidden:
            raise OutputVerificationContractError("Unsupported verification schema keyword")
        if "$schema" in node and node["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise OutputVerificationContractError("Unsupported JSON Schema dialect")
        for key in ("properties",):
            if key in node:
                props = node[key]
                if not isinstance(props, dict) or len(props) > 64:
                    raise OutputVerificationContractError("Verification properties exceed limit")
                for child in props.values():
                    walk(child, depth + 1)
        for key in ("items", "additionalProperties", "not"):
            if key in node:
                walk(node[key], depth + 1)
        for key in ("allOf", "anyOf", "oneOf"):
            if key in node:
                options = node[key]
                if not isinstance(options, list) or len(options) > 12:
                    raise OutputVerificationContractError("Verification alternatives exceed limit")
                for child in options:
                    walk(child, depth + 1)
        for key in ("required", "enum"):
            if key in node and (not isinstance(node[key], list) or len(node[key]) > 64):
                raise OutputVerificationContractError("Verification schema list exceeds limit")

    walk(schema, 0)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise OutputVerificationContractError("Invalid output verification schema") from exc
    return {"version": value["version"], "schema": schema}


def assess_structured_output(
    contract: Mapping[str, Any] | None,
    content: Any,
    *,
    runtime_status: str,
    degraded: bool,
) -> dict[str, Any]:
    """Validate observed runtime output, not generated claims or artifact names."""
    verified_contract = validate_contract(contract)
    if not verified_contract:
        return {"status": "not_configured", "independently_verified": False}

    result: dict[str, Any] = {
        "status": "failed",
        "contract_version": "structured-output.v1",
        "contract_sha256": _hash(verified_contract),
        "independently_verified": False,
        "scope": "runtime_structured_content_only",
    }
    if runtime_status != "ok" or degraded:
        result["reason"] = "runtime_not_healthy"
        return result
    if not isinstance(content, dict) or not content:
        result["reason"] = "structured_output_missing"
        return result
    try:
        if len(_canonical(content).encode("utf-8")) > MAX_OUTPUT_BYTES:
            result["reason"] = "structured_output_oversized"
            return result
    except (TypeError, ValueError, OverflowError):
        result["reason"] = "structured_output_not_json"
        return result
    result["output_sha256"] = _hash(content)
    validator = Draft202012Validator(verified_contract["schema"])
    # Do not persist model-generated values or detailed field contents in
    # errors; schema path alone is sufficient for review.
    errors = list(validator.iter_errors(content))
    if errors:
        result["reason"] = "schema_mismatch"
        result["violation_count"] = min(len(errors), 1000)
        result["violation_paths"] = [
            "/".join(str(part) for part in err.absolute_path)[:160]
            for err in errors[:5]
        ]
    else:
        result["status"] = "passed"
        result["reason"] = "structured_output_conforms_to_schema"
    return result
