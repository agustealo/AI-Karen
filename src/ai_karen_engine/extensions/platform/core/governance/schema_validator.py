"""
Input/output schema validation for governed plugins.

Enforces the manifest-declared input_schema_version and output_schema_version
at runtime. Rejects undeclared input fields and output shapes that violate
the plugin's declared schema contract.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest

logger = logging.getLogger("kari.plugin_governance.schema")


class PluginSchemaValidator:
    """Validates plugin input and output against declared schemas."""

    def validate_input(self, manifest: ExtensionManifest, payload: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        schema = self._extract_schema(manifest, "input")
        if not schema:
            return errors

        if not isinstance(payload, dict):
            errors.append("Input payload must be an object")
            return errors

        required = schema.get("required", [])
        properties = schema.get("properties", {})
        allow_additional = schema.get("additionalProperties", True)

        for field_name in required:
            if field_name not in payload:
                errors.append(f"Missing required input field: {field_name}")

        for key in payload:
            if key not in properties:
                if not allow_additional:
                    errors.append(f"Unexpected input field: {key}")
                continue

            field_schema = properties[key]
            value = payload[key]
            field_errors = self._validate_value(key, value, field_schema)
            errors.extend(field_errors)

        return errors

    def validate_output(self, manifest: ExtensionManifest, payload: Any) -> List[str]:
        errors: List[str] = []
        schema = self._extract_schema(manifest, "output")
        if not schema:
            return errors

        if not isinstance(payload, dict):
            errors.append("Output payload must be an object")
            return errors

        required = schema.get("required", [])
        properties = schema.get("properties", {})
        allow_additional = schema.get("additionalProperties", True)

        for field_name in required:
            if field_name not in payload:
                errors.append(f"Missing required output field: {field_name}")

        for key in payload:
            if key not in properties:
                if not allow_additional:
                    errors.append(f"Unexpected output field: {key}")
                continue

            field_schema = properties[key]
            value = payload[key]
            field_errors = self._validate_value(key, value, field_schema)
            errors.extend(field_errors)

        return errors

    def _extract_schema(self, manifest: ExtensionManifest, direction: str) -> Dict[str, Any]:
        raw = manifest.model_dump()
        gov_raw = raw.get("governance") or {}
        if not isinstance(gov_raw, dict):
            return {}

        version_key = "input_schema_version" if direction == "input" else "output_schema_version"
        if not gov_raw.get(version_key):
            return {}

        config_schema = manifest.config_schema
        if config_schema is None:
            return {}

        if isinstance(config_schema, dict):
            schema = config_schema
        else:
            schema = config_schema.model_dump() if hasattr(config_schema, "model_dump") else {}

        if direction == "input":
            return schema.get("input", {})
        return schema.get("output", schema)

    def _validate_value(self, name: str, value: Any, schema: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        expected_type = schema.get("type")

        type_map = {
            "string": str,
            "str": str,
            "integer": int,
            "int": int,
            "number": (int, float),
            "float": float,
            "boolean": bool,
            "bool": bool,
            "array": list,
            "list": list,
            "object": dict,
            "dict": dict,
            "null": type(None),
        }

        if expected_type:
            expected = type_map.get(expected_type.lower())
            if expected and not isinstance(value, expected):
                errors.append(
                    f"Field '{name}' must be of type '{expected_type}', got {type(value).__name__}"
                )

        if "enum" in schema and value not in schema["enum"]:
            errors.append(
                f"Field '{name}' must be one of {schema['enum']}, got {value!r}"
            )

        if "minLength" in schema and isinstance(value, str) and len(value) < schema["minLength"]:
            errors.append(f"Field '{name}' is shorter than minLength {schema['minLength']}")

        if "maxLength" in schema and isinstance(value, str) and len(value) > schema["maxLength"]:
            errors.append(f"Field '{name}' exceeds maxLength {schema['maxLength']}")

        if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
            errors.append(f"Field '{name}' is less than minimum {schema['minimum']}")

        if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
            errors.append(f"Field '{name}' exceeds maximum {schema['maximum']}")

        return errors


__all__ = ["PluginSchemaValidator"]
