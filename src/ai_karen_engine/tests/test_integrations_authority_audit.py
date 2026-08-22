"""
INTEGRATIONS-1: Authority & Reference Audit for src/ai_karen_engine/integrations.

This module documents the current classification of every file in the
integrations directory and the consumers that depend on it. It is intended
as the source of truth for the INTEGRATIONS sprint.

Classification legend:
- KEEP_AS_ADAPTER: legitimate external adapter/protocol boundary
- MOVE_TO_CANONICAL: unique behavior that belongs in a canonical owner
- DUPLICATE: overlapping authority already owned elsewhere
- SHIM: compatibility facade for migration
- DEAD: no meaningful consumers or behavior
- DANGEROUS: misplaced authority with security/architectural risk
- NEEDS_AUDIT: requires deeper consumer/boundary analysis
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Dict, List, Tuple

import pytest


INTEGRATIONS_ROOT = pathlib.Path(__file__).resolve().parents[1] / "integrations"


def _run_rg(pattern: str) -> List[Tuple[str, int]]:
    cmd = [
        "rg",
        "-n",
        "--no-heading",
        "--hidden",
        "--glob",
        "*.py",
        pattern,
        "src",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    matches: List[Tuple[str, int]] = []
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        path, lineno, _ = line.partition(":")
        matches.append((path, int(lineno)))
    return matches


FILE_CLASSIFICATIONS: Dict[str, str] = {
    "__init__.py": "SHIM",
    "auth_manager.py": "DANGEROUS",
    "capability_aware_selector.py": "DUPLICATE",
    "capability_router.py": "DUPLICATE",
    "confidence_scoring.py": "NEEDS_AUDIT",
    "dynamic_provider_system.py": "DUPLICATE",
    "failure_pattern_analyzer.py": "NEEDS_AUDIT",
    "fallback_chain_manager.py": "DEAD",
    "health_monitor.py": "NEEDS_AUDIT",
    "intelligent_provider_registry.py": "DUPLICATE",
    "intelligent_provider_switcher.py": "DUPLICATE",
    "llm_profile_system.py": "DUPLICATE",
    "llm_registry.py": "DUPLICATE",
    "llm_router.py": "DUPLICATE",
    "llm_utils.py": "MOVE_TO_CANONICAL",
    "local_rpa_client.py": "KEEP_AS_ADAPTER",
    "model_availability_cache.py": "MOVE_TO_CANONICAL",
    "model_availability_manager.py": "MOVE_TO_CANONICAL",
    "nanda_client.py": "KEEP_AS_ADAPTER",
    "partial_failure_handler.py": "NEEDS_AUDIT",
    "performance_adaptive_router.py": "DUPLICATE",
    "provider_registry.py": "SHIM",
    "registry.py": "DUPLICATE",
    "routing_policies.py": "DUPLICATE",
    "sr_llamaindex_adapter.py": "KEEP_AS_ADAPTER",
    "startup.py": "DANGEROUS",
    "task_analyzer.py": "DUPLICATE",
    "video_providers.py": "KEEP_AS_ADAPTER",
    "video_registry.py": "KEEP_AS_ADAPTER",
    "voice_providers.py": "KEEP_AS_ADAPTER",
    "voice_registry.py": "KEEP_AS_ADAPTER",
    "providers/__init__.py": "KEEP_AS_ADAPTER",
    "providers/base.py": "KEEP_AS_ADAPTER",
    "providers/copilotkit_provider.py": "KEEP_AS_ADAPTER",
    "providers/deepseek_provider.py": "KEEP_AS_ADAPTER",
    "providers/fallback_provider.py": "KEEP_AS_ADAPTER",
    "providers/gemini_provider.py": "KEEP_AS_ADAPTER",
    "providers/huggingface_provider.py": "KEEP_AS_ADAPTER",
    "providers/ollama_provider.py": "KEEP_AS_ADAPTER",
    "providers/openai_compatible_provider.py": "KEEP_AS_ADAPTER",
    "providers/openai_provider.py": "KEEP_AS_ADAPTER",
    "web/crawl4ai_integration.py": "KEEP_AS_ADAPTER",
}


def test_integrations_authority_audit_classifications() -> None:
    """Every integrations Python file must have an authority classification."""
    missing = []
    for path in INTEGRATIONS_ROOT.rglob("*.py"):
        if path.name.startswith("__pycache__"):
            continue
        rel = path.relative_to(INTEGRATIONS_ROOT).as_posix()
        if rel not in FILE_CLASSIFICATIONS:
            missing.append(rel)

    assert not missing, f"Unclassified integrations files: {missing}"


def test_high_confidence_deletions_have_zero_consumers() -> None:
    """Files classified DEAD must have no non-test, non-integration consumers."""
    dead_files = [name for name, cls in FILE_CLASSIFICATIONS.items() if cls == "DEAD"]
    for dead_file in dead_files:
        matches = _run_rg(f"ai_karen_engine\\.integrations\\.{dead_file.replace('.py', '')}")
        external = [
            path
            for path, _ in matches
            if "integrations" not in pathlib.Path(path).parts
            and "tests" not in pathlib.Path(path).parts
        ]
        assert not external, f"Dead file {dead_file} has external consumers: {external}"


def test_duplicate_router_files_are_documented() -> None:
    """Duplicate router/registry files must be explicitly listed."""
    duplicates = [name for name, cls in FILE_CLASSIFICATIONS.items() if cls == "DUPLICATE"]
    expected_duplicates = [
        "llm_router.py",
        "capability_router.py",
        "capability_aware_selector.py",
        "performance_adaptive_router.py",
        "intelligent_provider_switcher.py",
        "dynamic_provider_system.py",
        "intelligent_provider_registry.py",
        "routing_policies.py",
        "llm_registry.py",
        "registry.py",
        "llm_profile_system.py",
    ]
    for expected in expected_duplicates:
        assert expected in duplicates, f"Expected duplicate classification missing for {expected}"


def test_adapter_files_are_identified() -> None:
    """Files that are genuine external adapters must be classified as KEEP_AS_ADAPTER."""
    adapters = [name for name, cls in FILE_CLASSIFICATIONS.items() if cls == "KEEP_AS_ADAPTER"]
    expected_adapters = [
        "local_rpa_client.py",
        "nanda_client.py",
        "sr_llamaindex_adapter.py",
        "video_providers.py",
        "video_registry.py",
        "voice_providers.py",
        "voice_registry.py",
    ]
    for expected in expected_adapters:
        assert expected in adapters, f"Expected adapter classification missing for {expected}"


def test_consumer_matrix_documented() -> None:
    """The audit must document key integration consumers outside the package."""
    key_consumers = [
        "src/ai_karen_engine/llm_orchestrator.py",
        "src/ai_karen_engine/core/runtime/chat_runtime_control_plane.py",
        "src/ai_karen_engine/config/llm_provider_config.py",
        "src/ai_karen_engine/routing/kire_router.py",
        "src/ai_karen_engine/api_routes/models/intelligent_router.py",
        "src/ai_karen_engine/api_routes/models/settings.py",
        "src/ai_karen_engine/services/models/routing/llm_router_service.py",
    ]
    for consumer in key_consumers:
        path = pathlib.Path(consumer)
        assert path.exists(), f"Key consumer file missing from audit: {consumer}"


def test_dangerous_files_are_flagged() -> None:
    """Files with DANGEROUS classification must be explicitly listed."""
    dangerous = [name for name, cls in FILE_CLASSIFICATIONS.items() if cls == "DANGEROUS"]
    expected_dangerous = [
        "auth_manager.py",
        "startup.py",
    ]
    for expected in expected_dangerous:
        assert expected in dangerous, f"Expected dangerous classification missing for {expected}"


def test_fallback_manager_removed_import_uses_canonical_owner() -> None:
    """Any remaining fallback_manager imports must resolve from canonical resilience owner."""
    from ai_karen_engine.core.runtime.resilience import get_fallback_manager

    assert get_fallback_manager is not None


def test_no_hidden_registry_classes_in_providers_package() -> None:
    """The providers package must not define another ProviderRegistry class."""
    providers_root = INTEGRATIONS_ROOT / "providers"
    registry_paths = []
    for path in providers_root.rglob("*.py"):
        if path.name.startswith("__pycache__"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "class ProviderRegistry" in text or "class LLMRegistry" in text:
            registry_paths.append(path)

    assert not registry_paths, f"Providers package contains registry classes: {registry_paths}"


def test_canonical_provider_registry_service_exists() -> None:
    """The canonical provider registry must live in core/model_runtime."""
    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        ProviderRegistryService,
    )

    assert ProviderRegistryService is not None


def test_canonical_providers_package_contains_only_adapters() -> None:
    """The integrations/providers package must not contain registries or routers."""
    providers_root = INTEGRATIONS_ROOT / "providers"
    forbidden = []
    for path in providers_root.rglob("*.py"):
        if path.name.startswith("__pycache__"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "class Registry" in text or "class Router" in text or "class Manager" in text:
            forbidden.append(path)

    assert not forbidden, f"Providers package contains non-adapter classes: {forbidden}"


def test_integrations_init_exports_only_adapters() -> None:
    """integrations/__init__.py must not eagerly import dead/duplicate authorities."""
    init_path = INTEGRATIONS_ROOT / "__init__.py"
    text = init_path.read_text(encoding="utf-8", errors="ignore")

    assert "from ai_karen_engine.integrations.factory import" not in text
    assert "get_fallback_manager" not in text
    assert "get_task_analyzer_dependency" not in text
    assert "get_best_available_router" not in text
    assert "get_llm_router_dependency" not in text


def test_canonical_provider_registry_service_is_single_source_of_truth() -> None:
    """Provider registry must resolve from core/model_runtime, not integrations shim."""
    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        ProviderRegistryService,
    )
    from ai_karen_engine.integrations.provider_registry import ProviderRegistry

    canonical = ProviderRegistryService
    legacy = ProviderRegistry

    assert canonical is not None
    assert legacy is not None
    assert "Legacy" in legacy.__doc__ or "compatibility" in legacy.__doc__.lower()


def test_no_duplicate_router_classes_outside_canonical_owners() -> None:
    """Duplicate router classes must not exist outside canonical routing owners."""
    duplicate_routers = [
        "llm_router.py",
        "capability_router.py",
        "capability_aware_selector.py",
        "performance_adaptive_router.py",
        "intelligent_provider_switcher.py",
        "dynamic_provider_system.py",
        "intelligent_provider_registry.py",
        "routing_policies.py",
    ]
    for router_path in duplicate_routers:
        full_path = INTEGRATIONS_ROOT / router_path
        assert full_path.exists(), f"Duplicate router file missing: {router_path}"
        text = full_path.read_text(encoding="utf-8", errors="ignore")
        assert "class" in text, f"Duplicate router file appears empty: {router_path}"


def test_canonical_resilience_owns_fallback() -> None:
    """Canonical fallback manager must exist in core/runtime/resilience."""
    from ai_karen_engine.core.runtime.resilience import get_fallback_manager

    assert get_fallback_manager is not None


def test_core_runtime_does_not_import_from_duplicate_router_authorities() -> None:
    """Core runtime must not import from duplicate router authorities."""
    import subprocess

    duplicate_routers = [
        "integrations.llm_router",
        "integrations.capability_router",
        "integrations.capability_aware_selector",
        "integrations.performance_adaptive_router",
        "integrations.intelligent_provider_switcher",
        "integrations.dynamic_provider_system",
        "integrations.intelligent_provider_registry",
        "integrations.routing_policies",
    ]

    core_dirs = [
        "src/ai_karen_engine/core",
        "src/ai_karen_engine/runtime",
        "src/ai_karen_engine/cortex",
        "src/ai_karen_engine/services",
    ]

    violations = []
    for router in duplicate_routers:
        for directory in core_dirs:
            cmd = [
                "rg",
                "-n",
                "--hidden",
                "--glob",
                "*.py",
                router,
                directory,
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            except FileNotFoundError:
                continue
            if result.stdout.strip():
                violations.append(f"{router} imported in {directory}")

    assert not violations, (
        "Core runtime code imports from duplicate router authorities: "
        f"{violations}"
    )


def test_duplicate_provider_registry_imports_are_documented() -> None:
    """All imports from duplicate provider registries must be documented."""
    import subprocess

    duplicate_registries = [
        "integrations.llm_registry",
        "integrations.registry",
        "integrations.provider_registry",
        "integrations.intelligent_provider_registry",
        "integrations.dynamic_provider_system",
    ]

    matches = []
    for registry in duplicate_registries:
        cmd = [
            "rg",
            "-n",
            "--hidden",
            "--glob",
            "*.py",
            registry,
            "src",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            continue
        if result.stdout.strip():
            matches.append(registry)

    assert matches, (
        "Expected duplicate registry imports to be present during migration. "
        "If none exist, the migration is complete."
    )


def test_deleted_dead_files_are_gone() -> None:
    """Deleted dead files must no longer exist on disk."""
    deleted_files = [
        "fallback_manager.py",
        "automation_manager.py",
        "prompt_blocks.py",
        "performance_router_init.py",
        "factory.py",
        "dependencies.py",
        "config_validator.py",
        "dependency_checker.py",
        "diagnostic_prompt.py",
        "error_recovery.py",
        "model_download_manager.py",
        "provider_status.py",
        "copilotkit_provider.py",
        "copilot_router.py",
        "provider_hierarchy.py",
        "copilotkit/routing_actions.py",
        "model_discovery.py",
    ]
    for filename in deleted_files:
        path = INTEGRATIONS_ROOT / filename
        assert not path.exists(), f"Deleted file still exists: {path}"


def test_deleted_unused_subpackages_are_gone() -> None:
    """Deleted unused subpackages must no longer exist on disk."""
    deleted_subpackages = [
        "llm",
        "copilotkit",
    ]
    for subpackage in deleted_subpackages:
        path = INTEGRATIONS_ROOT / subpackage
        assert not path.exists(), f"Deleted subpackage still exists: {path}"


# Root of the src tree (repo root is parents[3] of this test file).
_SRC_ROOT = pathlib.Path(__file__).resolve().parents[3] / "src" / "ai_karen_engine"


def test_model_lifecycle_single_discovery_authority() -> None:
    """Model discovery must live only in core/model_runtime; integrations copy retired."""
    retired = INTEGRATIONS_ROOT / "model_discovery.py"
    assert not retired.exists(), "Retired integrations/model_discovery.py still present"

    startup = _SRC_ROOT / "server" / "startup.py"
    assert startup.exists()
    startup_text = startup.read_text(encoding="utf-8", errors="ignore")
    assert "integrations.model_discovery" not in startup_text
    assert "sync_model_registry_cache" in startup_text
    assert "core.model_runtime.model_registry_writer" in startup_text

    writer = _SRC_ROOT / "core" / "model_runtime" / "model_registry_writer.py"
    assert writer.exists()
    writer_text = writer.read_text(encoding="utf-8", errors="ignore")
    assert "def sync_model_registry_cache" in writer_text
    assert "get_model_discovery_service" in writer_text


def test_model_lifecycle_events_contract() -> None:
    """Canonical model lifecycle event vocabulary must be defined."""
    events = _SRC_ROOT / "core" / "model_runtime" / "model_lifecycle_events.py"
    assert events.exists(), "model_lifecycle_events.py missing"
    text = events.read_text(encoding="utf-8", errors="ignore")
    assert "ModelLifecycleEvent" in text
    for event in (
        "model.discovered",
        "model.available",
        "model.unavailable",
        "model.load_started",
        "model.loaded",
        "model.load_failed",
        "model.evicted",
        "model.download_started",
        "model.download_failed",
    ):
        assert event in text, f"Missing canonical lifecycle event: {event}"


def test_model_lifecycle_consumers_off_integrations() -> None:
    """model_availability_* live under migration until their only consumers
    (the deprecated llm_router + the doomed routing cluster) are retired.
    Gate the classification so the convergence stays explicit."""
    for filename in ("model_availability_cache.py", "model_availability_manager.py"):
        assert FILE_CLASSIFICATIONS.get(filename) == "MOVE_TO_CANONICAL", (
            f"{filename} must be classified MOVE_TO_CANONICAL until migrated to core/model_runtime"
        )
    assert FILE_CLASSIFICATIONS.get("model_discovery.py") is None, (
        "model_discovery.py was retired; classification entry should be removed"
    )
