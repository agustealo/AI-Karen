"""
Import-boundary architecture tests (CORE-MAP-1 + SERVICE-CLOSE-1).

These tests enforce dependency-direction rules so that the architecture
remains clean as the codebase evolves. They use AST-based import scanning
to avoid import-time side effects.

Forbidden import directions are defined in:
  src/ai_karen_engine/core/ARCHITECTURE.md
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
AI_KEREN_ROOT = SRC_ROOT / "ai_karen_engine"


def _collect_python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if p.is_file()]


def _parse_module(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None


class ImportCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imported: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imported.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imported.append(node.module)
        self.generic_visit(node)


def _imports_from_file(path: Path) -> list[str]:
    mod = _parse_module(path)
    if mod is None:
        return []
    collector = ImportCollector()
    collector.visit(mod)
    return collector.imported


def _normalize_import(imp: str) -> str:
    """Normalize an import path: strip package prefix and leading dots."""
    result = imp.lstrip(".")
    if result.startswith("ai_karen_engine.core."):
        result = result[len("ai_karen_engine.core."):]
    elif result.startswith("ai_karen_engine."):
        result = result[len("ai_karen_engine."):]
    return "core." + result if not result.startswith("core.") else result


# ---------------------------------------------------------------------------
# Hard-blocked imports: consumer may NEVER import these
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORTS: list[tuple[str, str]] = [
    # Cortex decides but does not execute providers/models
    ("core.cortex", "core.model_runtime"),
    ("core.cortex", "core.langgraph_orchestrator"),

    # Reasoning strategies may not reach into API routes
    ("core.reasoning", "api_routes"),

    # LangGraph executes graphs only; must not do provider selection
    ("core.langgraph_orchestrator", "core.model_runtime.provider_registry"),

    # model_runtime runs inference only; must not import ChatRuntime
    ("core.model_runtime", "core.runtime.chat_runtime"),
    ("core.model_runtime", "core.runtime.chat_runtime_service"),
    ("core.model_runtime", "core.runtime.chat_runtime_control_plane"),

    # Memory stores data but does not import cortex execution
    ("core.memory", "core.cortex"),

    # Observability observes only — no business logic
    ("core.observability", "core.cortex"),
    ("core.observability", "core.adaptive"),
    ("core.observability", "core.personalization"),
]


# ---------------------------------------------------------------------------
# CORE-SPLIT-2: Core must not import Platform/Provider/Extension infra
# These are currently xfail with owner/sprint/sunset/expiry metadata.
# ---------------------------------------------------------------------------

CORE_SPLIT_2_FORBIDDEN_IMPORTS: list[tuple[str, str, str, str, str, str]] = [
    # (consumer, forbidden, owner, sprint, sunset_condition, expiry)
    ("core", "services", "Core Team", "CORE-SPLIT-2 Phase 3", "All core modules use runtime/ service ports", "2026-09-30"),
    ("core", "tools", "Core Team", "CORE-SPLIT-2 Phase 3", "All tool execution routes through extensions/", "2026-09-30"),
    ("core", "database", "Platform Team", "CORE-SPLIT-2 Phase 2", "All DB access routes through platform/memory/", "2026-09-30"),
    ("core", "persistence", "Platform Team", "CORE-SPLIT-2 Phase 5", "All persistence routes through platform/", "2026-09-30"),
    ("core", "storage", "Platform Team", "CORE-SPLIT-2 Phase 2", "All storage routes through platform/", "2026-09-30"),
    ("core", "integrations", "Platform Team", "CORE-SPLIT-2 Phase 11", "All integrations route through extensions/", "2026-09-30"),
    ("core", "mcp", "Extensions Team", "CORE-SPLIT-2 Phase 11", "MCP is an extension adapter, not core", "2026-09-30"),
    ("core", "middleware", "Runtime Team", "CORE-SPLIT-2 Phase 9", "HTTP middleware lives in api_routes/", "2026-09-30"),
    ("core", "error_handling", "Core Team", "CORE-SPLIT-2 Phase 9", "Error types split to core/contracts/errors.py", "2026-09-30"),
    ("core", "error_tracking", "Platform Team", "CORE-SPLIT-2 Phase 9", "Error tracking is platform infrastructure", "2026-09-30"),
    ("core", "inference", "Runtime Team", "CORE-SPLIT-2 Phase 8", "Inference routes through runtime/inference/", "2026-09-30"),
    ("core", "extensions", "Extensions Team", "CORE-SPLIT-2 Phase 3", "Core imports extension contracts, not implementations", "2026-09-30"),
    ("core.memory", "core.model_runtime", "Memory Team", "CORE-SPLIT-2 Phase 2", "Memory uses EmbeddingPort, not EmbeddingManager", "2026-09-30"),
    ("core.personalization", "services", "Personalization Team", "CORE-SPLIT-2 Phase 5", "Personalization uses platform/personalization/", "2026-09-30"),
]


# ---------------------------------------------------------------------------
# Blocked-with-exceptions: consumer may import data contracts but not
# execution infrastructure. The exception list contains allowed sub-paths
# (data contracts, contracts modules) that are safe to consume.
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORTS_WITH_EXCEPTIONS: list[tuple[str, str, set[str]]] = [
    # Personalization may consume outcome data contracts
    ("core.personalization", "core.runtime", {"core.runtime.outcome.contracts"}),
    # Adaptive may consume outcome/user-state data contracts
    ("core.adaptive", "core.runtime", {"core.runtime.outcome.contracts"}),
    # Security may consume auth/config data but not runtime execution
    ("core.security", "core.runtime", set()),
    # Intelligence may consume runtime data contracts for training datasets
    ("core.intelligence", "core.runtime", {"core.runtime.contracts"}),
]


def _imports_violate_hard_rule(file_path: Path, forbidden: str) -> list[str]:
    violations: list[str] = []
    for imp in _imports_from_file(file_path):
        if forbidden in imp:
            violations.append(imp)
    return violations


def _imports_violate_except_rule(
    file_path: Path, pattern: str, allowed: set[str]
) -> list[str]:
    violations: list[str] = []
    for imp in _imports_from_file(file_path):
        normalized = _normalize_import(imp)
        if pattern in normalized:
            is_allowed = any(
                normalized == a or normalized.startswith(a + ".") for a in allowed
            )
            if not is_allowed:
                violations.append(imp)
    return violations


@pytest.mark.parametrize("consumer,forbidden", FORBIDDEN_IMPORTS)
def test_no_forbidden_imports(consumer: str, forbidden: str) -> None:
    """Ensure consumer domain does not import forbidden dependency."""
    consumer_dir = AI_KEREN_ROOT / consumer.replace(".", "/")
    files = _collect_python_files(consumer_dir)
    assert files, f"Consumer domain {consumer} does not resolve to a directory"

    all_violations: list[tuple[str, str]] = []
    for f in files:
        for v in _imports_violate_hard_rule(f, forbidden):
            all_violations.append((str(f), v))

    if all_violations:
        details = "\n".join(f"  {f}: {v}" for f, v in all_violations)
        pytest.fail(
            f"Forbidden import: {consumer} must not import {forbidden}.\n"
            f"Violations:\n{details}"
        )


@pytest.mark.parametrize(
    "consumer,pattern,allowed", FORBIDDEN_IMPORTS_WITH_EXCEPTIONS
)
def test_no_forbidden_imports_with_exceptions(
    consumer: str, pattern: str, allowed: set[str]
) -> None:
    """Ensure consumer domain only imports allowed sub-modules of pattern."""
    consumer_dir = AI_KEREN_ROOT / consumer.replace(".", "/")
    files = _collect_python_files(consumer_dir)
    assert files, f"Consumer domain {consumer} does not resolve to a directory"

    all_violations: list[tuple[str, str]] = []
    for f in files:
        for v in _imports_violate_except_rule(f, pattern, allowed):
            all_violations.append((str(f), v))

    if all_violations:
        details = "\n".join(f"  {f}: {v}" for f, v in all_violations)
        pytest.fail(
            f"Forbidden import: {consumer} must not import {pattern} "
            f"except for allowed data contracts: {allowed}.\n"
            f"Violations:\n{details}"
        )


# ---------------------------------------------------------------------------
# Dead domain removal tests (CORE-PRUNE-1)
#
# These domains have been classified as Generation A / prototype / fossil
# and must not exist or be importable from src/ai_karen_engine/core/.
# ---------------------------------------------------------------------------

DEAD_DOMAINS = [
    "core.echo_core",
    "core.response",
    "core.data_models",
    "core.operations",
]


@pytest.mark.parametrize("dead_domain", DEAD_DOMAINS)
def test_dead_domain_removed(dead_domain: str) -> None:
    """Verify that dead/compatibility domains have been deleted."""
    domain_dir = AI_KEREN_ROOT / dead_domain.replace(".", "/")
    assert not domain_dir.exists(), (
        f"Dead domain '{dead_domain}' still exists at {domain_dir}. "
        f"It should have been deleted during CORE-PRUNE-1."
    )


@pytest.mark.parametrize("dead_domain", DEAD_DOMAINS)
def test_no_imports_of_dead_domain(dead_domain: str) -> None:
    """No Python file in src/ should import from a deleted domain."""
    all_src_files = _collect_python_files(SRC_ROOT)
    violations: list[tuple[str, str]] = []
    for f in all_src_files:
        for imp in _imports_from_file(f):
            if dead_domain in imp:
                violations.append((str(f), imp))

    if violations:
        details = "\n".join(f"  {f}: {v}" for f, v in violations)
        pytest.fail(
            f"Source files still import from deleted domain '{dead_domain}'.\n"
            f"Violations:\n{details}"
        )


# ---------------------------------------------------------------------------
# Services layer authority boundary tests (SERVICE-CLOSE-1)
#
# services/ must remain a thin application/use-case layer. It must not
# duplicate canonical domain owners under core/ or grow parallel
# infrastructure subsystems beside the canonical architecture.
# ---------------------------------------------------------------------------

SERVICES_DIR = AI_KEREN_ROOT / "services"

FORBIDDEN_SERVICES_IMPORTS: list[tuple[str, str]] = [
    ("services", "core.model_runtime"),
    ("services", "core.runtime"),
    ("services", "core.cortex"),
    ("services", "core.langgraph_orchestrator"),
    ("services", "core.reasoning"),
    ("services", "core.memory"),
    ("services", "core.persona"),
    ("services", "core.personalization"),
    ("services", "core.observability"),
]

FORBIDDEN_PARALLEL_SERVICES_IMPORTS: list[tuple[str, str]] = [
    ("services", "services.orchestration"),
    ("services", "services.memory"),
    ("services", "services.plugin_"),
    ("services", "services.tooling"),
    ("services", "services.search"),
    ("services", "services.streaming"),
    ("services", "services.response"),
    ("services", "services.response_formatting"),
    ("services", "services.formatting"),
    ("services", "services.monitoring"),
    ("services", "services.caching"),
]


def _collect_services_files() -> list[Path]:
    if not SERVICES_DIR.exists():
        return []
    return [p for p in SERVICES_DIR.rglob("*.py") if p.is_file()]


@pytest.mark.parametrize(
    "consumer,forbidden", FORBIDDEN_SERVICES_IMPORTS
)
@pytest.mark.xfail(
    reason="[SERVICE-CLOSE-1] owner=Platform Team sprint=SERVICE-CLOSE-1 "
           "sunset=services/ imports only runtime/ ports expiry=2026-09-30. "
           "services/ currently imports forbidden core domains. "
           "These violations are tracked for convergence sprints "
           "(SERVICE-MODEL-1, SERVICE-ORCH-1, SERVICE-PLUGIN-1, etc.).",
    strict=False,
)
def test_services_must_not_import_core_domain(
    consumer: str, forbidden: str
) -> None:
    """services/ must not import canonical core domain infrastructure."""
    files = _collect_services_files()
    assert files, f"{consumer} directory does not resolve to files"

    all_violations: list[tuple[str, str]] = []
    for f in files:
        for v in _imports_violate_hard_rule(f, forbidden):
            all_violations.append((str(f), v))

    if all_violations:
        details = "\n".join(f"  {f}: {v}" for f, v in all_violations)
        pytest.fail(
            f"Forbidden import: {consumer} must not import {forbidden}.\n"
            f"Violations:\n{details}"
        )


@pytest.mark.parametrize(
    "consumer,forbidden", FORBIDDEN_PARALLEL_SERVICES_IMPORTS
)
@pytest.mark.xfail(
    reason="[SERVICE-CLOSE-1] owner=Platform Team sprint=SERVICE-CLOSE-1 "
           "sunset=services/ uses canonical owners only expiry=2026-09-30. "
           "services/ contains parallel infrastructure subsystems. "
           "These violations are tracked for convergence sprints.",
    strict=False,
)
def test_services_must_not_grow_parallel_subsystems(
    consumer: str, forbidden: str
) -> None:
    """services/ must not contain parallel infrastructure subsystems."""
    files = _collect_services_files()
    assert files, f"{consumer} directory does not resolve to files"

    all_violations: list[tuple[str, str]] = []
    for f in files:
        for v in _imports_violate_hard_rule(f, forbidden):
            all_violations.append((str(f), v))

    if all_violations:
        details = "\n".join(f"  {f}: {v}" for f, v in all_violations)
        pytest.fail(
            f"Parallel subsystem: {consumer} must not import {forbidden}.\n"
            f"These imports indicate duplicate authority beside the canonical domain.\n"
            f"Violations:\n{details}"
        )


def test_services_tests_moved_out_of_production_package() -> None:
    """Production tests must not live inside services/."""
    assert not (SERVICES_DIR / "tests").exists(), (
        "tests/ directory found inside services/. "
        "Production tests must live under the top-level tests/ directory."
    )
    assert not (SERVICES_DIR / "test_unified_execution_flow.py").exists(), (
        "test_unified_execution_flow.py found inside services/. "
        "Move it to tests/."
    )


def test_no_root_level_database_shims() -> None:
    """Root-level database shims must be removed."""
    shims = [
        "database_config.py",
        "database_connection_manager.py",
        "database_consistency_validator.py",
        "database_health_monitor.py",
        "enhanced_database_health_monitor.py",
        "migration_validator.py",
    ]
    for shim in shims:
        assert not (SERVICES_DIR / shim).exists(), (
            f"Compatibility shim {shim} still exists at services/ root. "
            f"Remove it and update importers to the canonical path."
        )


def test_models_subtree_migrated_to_core() -> None:
    """services/models/ and services/provider_runtime.py must be removed."""
    assert not (SERVICES_DIR / "models").exists(), (
        "services/models/ still exists. "
        "Migrate to core/model_runtime/ and update importers."
    )
    assert not (SERVICES_DIR / "provider_runtime.py").exists(), (
        "services/provider_runtime.py still exists. "
        "Migrate to core/runtime/provider_runtime.py and update importers."
    )


# ---------------------------------------------------------------------------
# CORE-SPLIT-2: Core must not import Platform/Provider/Extension infra
# These violations are tracked with owner, sprint, sunset, and expiry.
# ---------------------------------------------------------------------------

CORE_SPLIT_2_FORBIDDEN_IMPORTS: list[tuple[str, str, str, str, str, str]] = [
    ("core", "services", "Core Team", "CORE-SPLIT-2 Phase 3", "All core modules use runtime/ service ports", "2026-09-30"),
    ("core", "tools", "Core Team", "CORE-SPLIT-2 Phase 3", "All tool execution routes through extensions/", "2026-09-30"),
    ("core", "database", "Platform Team", "CORE-SPLIT-2 Phase 2", "All DB access routes through platform/memory/", "2026-09-30"),
    ("core", "persistence", "Platform Team", "CORE-SPLIT-2 Phase 5", "All persistence routes through platform/", "2026-09-30"),
    ("core", "storage", "Platform Team", "CORE-SPLIT-2 Phase 2", "All storage routes through platform/", "2026-09-30"),
    ("core", "integrations", "Platform Team", "CORE-SPLIT-2 Phase 11", "All integrations route through extensions/", "2026-09-30"),
    ("core", "mcp", "Extensions Team", "CORE-SPLIT-2 Phase 11", "MCP is an extension adapter, not core", "2026-09-30"),
    ("core", "middleware", "Runtime Team", "CORE-SPLIT-2 Phase 9", "HTTP middleware lives in api_routes/", "2026-09-30"),
    ("core", "error_handling", "Core Team", "CORE-SPLIT-2 Phase 9", "Error types split to core/contracts/errors.py", "2026-09-30"),
    ("core", "error_tracking", "Platform Team", "CORE-SPLIT-2 Phase 9", "Error tracking is platform infrastructure", "2026-09-30"),
    ("core", "inference", "Runtime Team", "CORE-SPLIT-2 Phase 8", "Inference routes through runtime/inference/", "2026-09-30"),
    ("core", "extensions", "Extensions Team", "CORE-SPLIT-2 Phase 3", "Core imports extension contracts, not implementations", "2026-09-30"),
    ("core.memory", "core.model_runtime", "Memory Team", "CORE-SPLIT-2 Phase 2", "Memory uses EmbeddingPort, not EmbeddingManager", "2026-09-30"),
    ("core.personalization", "services", "Personalization Team", "CORE-SPLIT-2 Phase 5", "Personalization uses platform/personalization/", "2026-09-30"),
]


def test_core_split_2_no_platform_provider_extension_imports() -> None:
    """CORE-SPLIT-2: Core must not import Platform/Provider/Extension infrastructure."""
    for consumer, forbidden, owner, sprint, sunset, expiry in CORE_SPLIT_2_FORBIDDEN_IMPORTS:
        consumer_dir = AI_KEREN_ROOT / consumer.replace(".", "/")
        if not consumer_dir.exists():
            continue
        files = [p for p in consumer_dir.rglob("*.py") if p.is_file()]
        if not files:
            continue

        all_violations: list[tuple[str, str]] = []
        for f in files:
            for v in _imports_violate_hard_rule(f, forbidden):
                all_violations.append((str(f), v))

        if all_violations:
            details = "\n".join(f"  {f}: {v}" for f, v in all_violations)
            pytest.xfail(
                f"[CORE-SPLIT-2] owner={owner} sprint={sprint} "
                f"sunset={sunset} expiry={expiry}\n"
                f"Forbidden import: {consumer} must not import {forbidden}.\n"
                f"Violations:\n{details}"
            )


# ---------------------------------------------------------------------------
# Transport architecture tests (CHAT-FIRST-1E)
#
# Transport modules must not import provider selection, fallback chains,
# prompt builders, memory recall orchestration, or CORTEX execution logic.
# They must delegate to ChatRuntime.execute_stream() exclusively.
# ---------------------------------------------------------------------------

CHAT_TRANSPORT_DIR = AI_KEREN_ROOT / "api_routes" / "chat"

TRANSPORT_FORBIDDEN_IMPORTS: list[tuple[str, str]] = [
    ("api_routes.chat", "core.model_runtime"),
    ("api_routes.chat", "core.langgraph_orchestrator"),
    ("api_routes.chat", "core.reasoning"),
    ("api_routes.chat", "core.memory"),
    ("api_routes.chat", "core.runtime.runtime_fallback"),
]


def _collect_chat_transport_files() -> list[Path]:
    if not CHAT_TRANSPORT_DIR.exists():
        return []
    return [p for p in CHAT_TRANSPORT_DIR.rglob("*.py") if p.is_file()]


@pytest.mark.parametrize("consumer,forbidden", TRANSPORT_FORBIDDEN_IMPORTS)
def test_chat_transports_must_not_import_forbidden_domains(
    consumer: str, forbidden: str
) -> None:
    """Chat transport routes must not import provider selection or execution logic."""
    files = _collect_chat_transport_files()
    assert files, f"{consumer} directory does not resolve to files"

    all_violations: list[tuple[str, str]] = []
    for f in files:
        for v in _imports_violate_hard_rule(f, forbidden):
            all_violations.append((str(f), v))

    if all_violations:
        details = "\n".join(f"  {f}: {v}" for f, v in all_violations)
        pytest.fail(
            f"Forbidden import: {consumer} must not import {forbidden}.\n"
            f"Transport modules must delegate to ChatRuntime and remain thin.\n"
            f"Violations:\n{details}"
        )
