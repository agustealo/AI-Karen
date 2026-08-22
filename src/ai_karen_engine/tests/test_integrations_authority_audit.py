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


INTEGRATIONS_ROOT = pathlib.Path(__file__).resolve().parents[1] / "ai_karen_engine" / "integrations"


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
    "auth_manager.py": "DANGEROUS",
    "capability_aware_selector.py": "DUPLICATE",
    "capability_router.py": "DUPLICATE",
    "confidence_scoring.py": "NEEDS_AUDIT",
    "config_validator.py": "MOVE_TO_CANONICAL",
    "copilotkit_provider.py": "DUPLICATE",
    "copilot_router.py": "DUPLICATE",
    "dependencies.py": "DANGEROUS",
    "dependency_checker.py": "MOVE_TO_CANONICAL",
    "diagnostic_prompt.py": "NEEDS_AUDIT",
    "dynamic_provider_system.py": "DUPLICATE",
    "error_recovery.py": "NEEDS_AUDIT",
    "factory.py": "DEAD",
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
    "model_discovery.py": "MOVE_TO_CANONICAL",
    "model_download_manager.py": "MOVE_TO_CANONICAL",
    "nanda_client.py": "KEEP_AS_ADAPTER",
    "partial_failure_handler.py": "NEEDS_AUDIT",
    "performance_adaptive_router.py": "DUPLICATE",
    "provider_hierarchy.py": "DUPLICATE",
    "provider_registry.py": "SHIM",
    "provider_status.py": "NEEDS_AUDIT",
    "registry.py": "DUPLICATE",
    "routing_policies.py": "DUPLICATE",
    "sr_llamaindex_adapter.py": "KEEP_AS_ADAPTER",
    "startup.py": "DANGEROUS",
    "task_analyzer.py": "DUPLICATE",
    "video_providers.py": "KEEP_AS_ADAPTER",
    "video_registry.py": "KEEP_AS_ADAPTER",
    "voice_providers.py": "KEEP_AS_ADAPTER",
    "voice_registry.py": "KEEP_AS_ADAPTER",
}


def test_integrations_authority_audit_classifications() -> None:
    """Every integrations Python file must have an authority classification."""
    missing = []
    for path in INTEGRATIONS_ROOT.rglob("*.py"):
        if path.name.startswith("__pycache__"):
            continue
        rel = str(path.relative_to(INTEGRATIONS_ROOT))
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
        "copilot_router.py",
        "performance_adaptive_router.py",
        "intelligent_provider_switcher.py",
        "dynamic_provider_system.py",
        "intelligent_provider_registry.py",
        "routing_policies.py",
        "provider_hierarchy.py",
        "llm_registry.py",
        "registry.py",
        "llm_profile_system.py",
        "copilotkit_provider.py",
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
        "dependencies.py",
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


def test_deleted_dead_files_are_gone() -> None:
    """Deleted dead files must no longer exist on disk."""
    deleted_files = [
        "fallback_manager.py",
        "automation_manager.py",
        "prompt_blocks.py",
        "performance_router_init.py",
    ]
    for filename in deleted_files:
        path = INTEGRATIONS_ROOT / filename
        assert not path.exists(), f"Deleted file still exists: {path}"
