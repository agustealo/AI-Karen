"""Remainder of executor.py - helper methods and schema validator."""

    def _infer_side_effects(self, manifest: ExtensionManifest, capability: Optional[ExtensionCapability]) -> List[str]:
        """Infer side effects from manifest and capability declarations."""
        effects: List[str] = []
        if manifest.requires_network or (capability and getattr(capability, "requires_network", False)):
            effects.append("network")
        if manifest.requires_filesystem or (capability and getattr(capability, "requires_filesystem", False)):
            effects.append("filesystem")
        if manifest.requires_credentials or (capability and getattr(capability, "requires_credentials", False)):
            effects.append("credentials")
        if manifest.requires_external_api:
            effects.append("external_api")

        side_effect_level = getattr(capability, "side_effect_level", None) if capability else manifest.side_effect_level
        if side_effect_level == SideEffectLevel.WRITE:
            effects.append("write")
        elif side_effect_level == SideEffectLevel.EXTERNAL:
            effects.extend(["write", "external"])

        return effects

    def _audit(self, **kwargs: Any) -> None:
        """Emit a structured audit event."""
        event = kwargs.get("event")
        if event is None:
            return
        if self._audit_sink:
            try:
                self._audit_sink(kwargs)
            except Exception as exc:
                logger.warning("Audit sink failed: %s", exc)
        logger.info(
            "extension_audit event=%s request_id=%s correlation_id=%s user_id=%s tenant_id=%s plugin_id=%s plugin_version=%s capability=%s execution_id=%s policy_decision_id=%s trust_tier=%s isolation_mode=%s side_effect_level=%s latency_ms=%s status=%s error_code=%s",
            event,
            kwargs.get("request_id"),
            kwargs.get("correlation_id"),
            kwargs.get("user_id"),
            kwargs.get("tenant_id"),
            kwargs.get("plugin_id"),
            kwargs.get("plugin_version"),
            kwargs.get("capability"),
            kwargs.get("execution_id"),
            kwargs.get("policy_decision_id"),
            kwargs.get("trust_tier"),
            kwargs.get("isolation_mode"),
            kwargs.get("side_effect_level"),
            kwargs.get("latency_ms"),
            kwargs.get("status"),
            kwargs.get("error_code"),
        )


class _DefaultSchemaValidator:
    """Default schema validator for extension input/output validation."""

    def validate_input(self, manifest: ExtensionManifest, payload: Dict[str, Any], capability: Optional[ExtensionCapability] = None) -> List[str]:
        schema = None
        if capability and capability.input_schema:
            schema = capability.input_schema
        elif manifest.input_schema:
            schema = manifest.input_schema

        if not schema:
            return []
        return self._validate(payload, schema, "input")

    def validate_output(self, manifest: ExtensionManifest, payload: Any, capability: Optional[ExtensionCapability] = None) -> List[str]:
        schema = None
        if capability and capability.output_schema:
            schema = capability.output_schema
        elif manifest.output_schema:
            schema = manifest.output_schema

        if not schema:
            return []
        return self._validate(payload if isinstance(payload, dict) else {"value": payload}, schema, "output")

    def _validate(self, payload: Dict[str, Any], schema: Dict[str, Any], direction: str) -> List[str]:
        errors: List[str] = []
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        allow_additional = schema.get("additionalProperties", True)

        for field_name in required:
            if field_name not in payload:
                errors.append(f"Missing required {direction} field: {field_name}")

        for key in payload:
            if key not in properties:
                if not allow_additional:
                    errors.append(f"Unexpected {direction} field: {key}")
                continue
            field_schema = properties[key]
            value = payload[key]
            expected_type = field_schema.get("type")
            if expected_type:
                type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
                expected = type_map.get(expected_type)
                if expected and not isinstance(value, expected):
                    errors.append(f"Field '{key}' must be {expected_type}, got {type(value).__name__}")

        return errors


__all__ = ["ExtensionExecutionService"]