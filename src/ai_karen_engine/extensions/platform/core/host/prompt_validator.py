"""
Prompt Validation System - Comprehensive validation for prompt templates.

Provides validation for:
- Jinja2 syntax errors
- Variable consistency
- Security vulnerabilities (prompt injection)
- Best practices compliance
- Length and complexity checks
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum

from jinja2 import (
    Environment,
    StrictUndefined,
    Template,
    TemplateSyntaxError,
    meta,
)


logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Represents a single validation issue."""

    code: str
    message: str
    severity: ValidationSeverity
    line_number: Optional[int] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "line_number": self.line_number,
            "suggestion": self.suggestion,
        }


class PromptValidator:
    """
    Comprehensive prompt template validator.

    Checks for:
    - Jinja2 syntax errors
    - Variable consistency
    - Security vulnerabilities
    - Best practices
    - Length and complexity
    """

    # Security patterns to detect
    SECURITY_PATTERNS = {
        "prompt_injection": r"(system|admin|developer|debug|bypass|override|ignore).*:",
        "path_traversal": r"\.\.[\\/]",
        "code_injection": r"(__import__|eval|exec|compile|open)",
    }

    # Best practice rules
    BEST_PRACTICE_RULES = {
        "max_length": 10000,  # Max characters per prompt
        "max_variables": 50,  # Max unique variables per template
        "max_nesting_depth": 10,  # Maximum if/for nesting depth
        "require_description": True,  # Require template documentation
    }

    def __init__(self):
        """Initialize the prompt validator."""
        self.env = Environment(undefined=StrictUndefined)

    def validate(
        self, template_content: str, config: Optional[Dict[str, Any]] = None
    ) -> List[ValidationIssue]:
        """
        Validate a prompt template comprehensively.

        Args:
            template_content: The prompt template content
            config: Optional template configuration

        Returns:
            List of validation issues
        """
        issues = []

        # 1. Syntax validation
        issues.extend(self._validate_syntax(template_content))

        # 2. Variable validation
        issues.extend(self._validate_variables(template_content, config))

        # 3. Security validation
        issues.extend(self._validate_security(template_content))

        # 4. Best practices validation
        issues.extend(self._validate_best_practices(template_content))

        # 5. Complexity validation
        issues.extend(self._validate_complexity(template_content))

        return issues

    def _validate_syntax(self, content: str) -> List[ValidationIssue]:
        """Validate Jinja2 syntax."""
        issues = []

        try:
            # Try to parse the template
            template = self.env.from_string(content)
            logger.debug("Jinja2 syntax is valid")
        except TemplateSyntaxError as e:
            issues.append(
                ValidationIssue(
                    code="SYNTAX_ERROR",
                    message=f"Jinja2 syntax error: {e.message}",
                    severity=ValidationSeverity.ERROR,
                    line_number=e.lineno,
                    suggestion="Check Jinja2 syntax documentation",
                )
            )
        except Exception as e:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_ERROR",
                    message=f"Unexpected error parsing template: {e}",
                    severity=ValidationSeverity.ERROR,
                    suggestion="Ensure template is valid text",
                )
            )

        return issues

    def _validate_variables(
        self, content: str, config: Optional[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """Validate variable usage and consistency."""
        issues = []

        try:
            # Extract variables from template
            template = self.env.from_string(content)
            variables = meta.find_undeclared_variables(template)
        except Exception:
            # If we can't parse, skip variable validation
            return issues

        # Check for too many variables
        if len(variables) > self.BEST_PRACTICE_RULES["max_variables"]:
            issues.append(
                ValidationIssue(
                    code="TOO_MANY_VARIABLES",
                    message=f"Template has {len(variables)} variables, "
                    f"maximum recommended is {self.BEST_PRACTICE_RULES['max_variables']}",
                    severity=ValidationSeverity.WARNING,
                    suggestion="Consider simplifying the template or reducing variables",
                )
            )

        # Check for variable naming consistency
        for var in variables:
            if not re.match(r"^[a-z][a-z0-9_]*$", var):
                issues.append(
                    ValidationIssue(
                        code="INVALID_VARIABLE_NAME",
                        message=f"Variable '{var}' doesn't follow naming convention "
                        f"(lowercase, underscores, alphanumeric)",
                        severity=ValidationSeverity.WARNING,
                        suggestion="Rename variable to lowercase with underscores",
                    )
                )

        # Check against config if provided
        if config:
            required_vars = config.get("required_variables", [])
            all_vars = config.get("variables", [])

            # Check for variables in required but not in template
            missing_in_template = set(required_vars) - set(variables)
            if missing_in_template:
                issues.append(
                    ValidationIssue(
                        code="REQUIRED_VAR_NOT_USED",
                        message=f"Required variables not used in template: {missing_in_template}",
                        severity=ValidationSeverity.WARNING,
                        suggestion="Remove from required_variables or use in template",
                    )
                )

            # Check for variables used but not declared
            undeclared = set(variables) - set(all_vars)
            if undeclared:
                issues.append(
                    ValidationIssue(
                        code="UNDECLARED_VARIABLE",
                        message=f"Variables used but not declared: {undeclared}",
                        severity=ValidationSeverity.INFO,
                        suggestion="Add to templates_config.variables",
                    )
                )

        return issues

    def _validate_security(self, content: str) -> List[ValidationIssue]:
        """Validate for security vulnerabilities."""
        issues = []
        lines = content.split("\n")

        # Check for suspicious patterns
        for pattern_name, pattern in self.SECURITY_PATTERNS.items():
            for line_num, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append(
                        ValidationIssue(
                            code=f"SECURITY_{pattern_name.upper()}",
                            message=f"Potential security issue detected: {pattern_name}",
                            severity=ValidationSeverity.ERROR,
                            line_number=line_num,
                            suggestion="Review and remove suspicious content",
                        )
                    )

        # Check for unescaped user input
        if "{{ user_" in content.lower() or "{{ query" in content.lower():
            issues.append(
                ValidationIssue(
                    code="UNESCAPED_USER_INPUT",
                    message="Unescaped user input may lead to prompt injection",
                    severity=ValidationSeverity.WARNING,
                    suggestion="Use filters or validation on user input",
                )
            )

        # Check for hardcoded secrets
        secret_patterns = [
            r'(api[_-]?key\s*[=:]\s*["\'][\w]+["\'])',
            r'(password\s*[=:]\s*["\'][\w]+["\'])',
            r'(token\s*[=:]\s*["\'][\w]+["\'])',
        ]

        for line_num, line in enumerate(lines, 1):
            for pattern in secret_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append(
                        ValidationIssue(
                            code="HARDCODED_SECRET",
                            message="Potential hardcoded secret detected",
                            severity=ValidationSeverity.ERROR,
                            line_number=line_num,
                            suggestion="Remove hardcoded secrets and use environment variables",
                        )
                    )

        return issues

    def _validate_best_practices(self, content: str) -> List[ValidationIssue]:
        """Validate against best practices."""
        issues = []

        # Check for missing documentation
        if not re.search(
            r"{#\s*(?:description|purpose|usage|required)", content, re.IGNORECASE
        ):
            issues.append(
                ValidationIssue(
                    code="MISSING_DOCUMENTATION",
                    message="Template lacks documentation comments",
                    severity=ValidationSeverity.INFO,
                    suggestion="Add {# description: ... #} comment at top",
                )
            )

        # Check for template without variables
        try:
            template = self.env.from_string(content)
            variables = meta.find_undeclared_variables(template)
            if not variables and "{{" not in content:
                issues.append(
                    ValidationIssue(
                        code="NO_VARIABLES",
                        message="Template has no variables - consider if static content is needed",
                        severity=ValidationSeverity.INFO,
                        suggestion="Add variables or use as static text",
                    )
                )
        except Exception:
            pass

        # Check for inconsistent spacing
        if re.search(r"\{\{\s*\w+\s*\}\}", content):
            issues.append(
                ValidationIssue(
                    code="INCONSISTENT_SPACING",
                    message="Variables have inconsistent spacing (use {{ variable }} or {{variable}})",
                    severity=ValidationSeverity.INFO,
                    suggestion="Use consistent spacing: {{ variable }}",
                )
            )

        # Check for deprecated syntax
        if "{% else %}" in content:
            issues.append(
                ValidationIssue(
                    code="DEPRECATED_SYNTAX",
                    message="Deprecated {% else %} syntax found",
                    severity=ValidationSeverity.WARNING,
                    suggestion="Use {% else %} (without surrounding braces)",
                )
            )

        # Check for missing closing tags
        opening_blocks = len(re.findall(r"{%\s*(if|for)", content))
        closing_blocks = len(re.findall(r"{%\s*(endif|endfor)", content))

        if opening_blocks != closing_blocks:
            issues.append(
                ValidationIssue(
                    code="UNCLOSED_BLOCKS",
                    message=f"Mismatched block tags: {opening_blocks} opening, {closing_blocks} closing",
                    severity=ValidationSeverity.ERROR,
                    suggestion="Add missing {% endif %} or {% endfor %} tags",
                )
            )

        return issues

    def _validate_complexity(self, content: str) -> List[ValidationIssue]:
        """Validate template complexity."""
        issues = []

        # Check length
        if len(content) > self.BEST_PRACTICE_RULES["max_length"]:
            issues.append(
                ValidationIssue(
                    code="TOO_LONG",
                    message=f"Template is {len(content)} characters, "
                    f"maximum recommended is {self.BEST_PRACTICE_RULES['max_length']}",
                    severity=ValidationSeverity.WARNING,
                    suggestion="Consider splitting into smaller templates",
                )
            )

        # Check nesting depth
        depth = self._calculate_nesting_depth(content)
        if depth > self.BEST_PRACTICE_RULES["max_nesting_depth"]:
            issues.append(
                ValidationIssue(
                    code="EXCESSIVE_NESTING",
                    message=f"Template nesting depth is {depth}, "
                    f"maximum recommended is {self.BEST_PRACTICE_RULES['max_nesting_depth']}",
                    severity=ValidationSeverity.WARNING,
                    suggestion="Reduce nesting or extract to sub-templates",
                )
            )

        # Check for empty conditionals
        if re.search(r"{%\s*if\s+\w+\s*%}\s*{%\s*endif\s*%}", content):
            issues.append(
                ValidationIssue(
                    code="EMPTY_CONDITIONAL",
                    message="Empty conditional block detected",
                    severity=ValidationSeverity.WARNING,
                    suggestion="Add content or remove conditional",
                )
            )

        # Check for redundant loops
        if re.search(r"{%\s*for\s+\w+\s*in\s*\[\s*\]\s*%}", content):
            issues.append(
                ValidationIssue(
                    code="EMPTY_LOOP",
                    message="Loop over empty list detected",
                    severity=ValidationSeverity.INFO,
                    suggestion="Check if loop is needed or add fallback",
                )
            )

        return issues

    def _calculate_nesting_depth(self, content: str) -> int:
        """Calculate maximum nesting depth of control structures."""
        depth = 0
        max_depth = 0

        # Simple stack-based depth calculation
        for line in content.split("\n"):
            # Count opening blocks
            opening = len(re.findall(r"{%\s*(if|for|elif)", line))
            depth += opening
            max_depth = max(max_depth, depth)

            # Count closing blocks
            closing = len(re.findall(r"{%\s*(endif|endfor|else)", line))
            depth -= closing

        return max_depth


# Validator instance
_validator_instance: Optional[PromptValidator] = None


def get_prompt_validator() -> PromptValidator:
    """Get the singleton prompt validator instance."""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = PromptValidator()
    return _validator_instance


def validate_prompt_template(
    template_content: str, config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convenience function to validate a prompt template.

    Args:
        template_content: The prompt template content
        config: Optional template configuration

    Returns:
        Dictionary with validation results
    """
    validator = get_prompt_validator()
    issues = validator.validate(template_content, config)

    error_count = sum(1 for i in issues if i.severity == ValidationSeverity.ERROR)
    warning_count = sum(1 for i in issues if i.severity == ValidationSeverity.WARNING)
    info_count = sum(1 for i in issues if i.severity == ValidationSeverity.INFO)

    return {
        "is_valid": error_count == 0,
        "issues": [issue.to_dict() for issue in issues],
        "summary": {
            "total_issues": len(issues),
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count,
        },
    }


__all__ = [
    "PromptValidator",
    "ValidationIssue",
    "ValidationSeverity",
    "get_prompt_validator",
    "validate_prompt_template",
]
