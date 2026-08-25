"""Tests for privacy and redaction specification.

Validates that forbidden raw values are documented, sensitivity classes
are defined, and the attribute allowance matrix is complete.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "architecture" / "cognitive-observability"
PRIVACY_REDACTION = DOCS_ROOT / "PRIVACY_REDACTION.md"


class TestForbiddenRawValues:
    """Verify forbidden raw values are documented."""

    @pytest.mark.parametrize("forbidden", [
        "password",
        "api key",
        "oauth token",
        "credential",
        "private memory text",
        "full conversation contents",
        "tool secret",
        "authorization header",
        "sensitive document",
        "provider raw payload",
    ])
    def test_forbidden_value_documented(self, forbidden: str) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert forbidden in content, f"Forbidden value '{forbidden}' not documented"


class TestReferenceOnlyRule:
    """Verify reference-only rule is documented."""

    def test_spec_requires_references_not_content(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert "reference" in content
        assert "content" in content

    def test_spec_shows_reference_examples(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8")
        assert "memory_ref=" in content or "memory_ref" in content


class TestSensitivityClasses:
    """Verify all sensitivity classes are defined."""

    @pytest.mark.parametrize("sensitivity_class", [
        "PUBLIC_SAFE",
        "INTERNAL",
        "USER_PRIVATE",
        "SECURITY_SENSITIVE",
        "SECRET",
    ])
    def test_sensitivity_class_documented(self, sensitivity_class: str) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8")
        assert sensitivity_class in content, f"Sensitivity class '{sensitivity_class}' not documented"


class TestAttributeAllowanceMatrix:
    """Verify attribute allowance matrix is documented."""

    @pytest.mark.parametrize("attribute", [
        "memory_ref",
        "memory plaintext",
        "belief confidence",
        "reason code",
        "api key",
        "provider name",
        "tenant id",
        "password",
    ])
    def test_attribute_in_matrix(self, attribute: str) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert attribute in content, f"Attribute '{attribute}' not in allowance matrix"


class TestAttributeAllowanceValues:
    """Verify specific attribute allowance values."""

    def test_memory_id_allowed(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8")
        # memory_ref or memory_id should be allowed (yes)
        assert "memory_ref" in content or "memory_id" in content

    def test_memory_plaintext_forbidden(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert "memory_text" in content or "memory plaintext" in content
        # Should be marked as not allowed
        assert "✗" in content or "no" in content or "never" in content

    def test_api_key_never(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert "api_key" in content or "api key" in content
        assert "never" in content

    def test_password_never(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert "password" in content
        assert "never" in content


class TestRedactionRules:
    """Verify redaction rules are documented."""

    @pytest.mark.parametrize("rule_context", [
        "emission",
        "rest",
        "query",
    ])
    def test_redaction_context_documented(self, rule_context: str) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert rule_context in content, f"Redaction context '{rule_context}' not documented"


class TestDeletionAwareTracing:
    """Verify deletion-aware tracing rules are documented."""

    def test_spec_documents_reference_survival(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert "reference" in content
        assert "surviv" in content or "retain" in content

    def test_spec_documents_content_deletion(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert "content" in content
        assert "delet" in content or "purge" in content

    def test_spec_prohibits_shadow_database(self) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8").lower()
        assert "shadow" in content, "Spec must prohibit observability becoming shadow memory database"


class TestCognitiveSensitiveKeys:
    """Verify cognitive-specific sensitive keys are documented."""

    @pytest.mark.parametrize("key", [
        "memory_text",
        "claim_text",
        "reasoning_trace",
        "private_reasoning",
        "conversation_content",
    ])
    def test_cognitive_sensitive_key_documented(self, key: str) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8")
        assert key in content, f"Cognitive sensitive key '{key}' not documented"


class TestRelationshipToExistingRedaction:
    """Verify relationship to existing redaction is documented."""

    @pytest.mark.parametrize("existing", [
        "redact_text",
        "redact_data",
        "sanitize_secrets",
    ])
    def test_existing_redaction_referenced(self, existing: str) -> None:
        content = PRIVACY_REDACTION.read_text(encoding="utf-8")
        assert existing in content, f"Existing redaction '{existing}' not referenced"
