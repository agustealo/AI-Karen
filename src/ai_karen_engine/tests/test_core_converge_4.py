"""
CORE-CONVERGE-4: Architecture guard tests for guardrails, hooks, inference & infra convergence.

These tests verify that the four directories have been properly converged
into the canonical architecture:

- guardrails/ -> retired (auth validation to auth/, tool validation to extensions)
- hooks/ -> lifecycle extension mechanism only (resilience to RuntimeResilience)
- inference/ -> execution adapters only (selection to ProviderRouter)
- infra/ -> technology primitives only (query analysis to IntelligenceRuntime)
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import List, Tuple

import pytest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _run_rg(pattern: str, root: str = "src") -> List[Tuple[str, int]]:
    cmd = [
        "rg",
        "-n",
        "--no-heading",
        "--hidden",
        "--glob",
        "*.py",
        pattern,
        root,
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


# ---------------------------------------------------------------------------
# guardrails/ retirement
# ---------------------------------------------------------------------------


def test_guardrails_directory_retired() -> None:
    """guardrails/ directory must no longer exist."""
    guardrails_path = SRC_ROOT / "guardrails"
    assert not guardrails_path.exists(), (
        "guardrails/ directory should have been retired. "
        "Auth validation belongs to auth/, tool validation to extensions."
    )


def test_no_guardrails_imports_remain() -> None:
    """No code should import from the retired guardrails package."""
    matches = _run_rg("from ai_karen_engine\\.guardrails")
    assert not matches, f"guardrails imports remain: {matches}"

    matches = _run_rg("import ai_karen_engine\\.guardrails")
    assert not matches, f"guardrails imports remain: {matches}"


# ---------------------------------------------------------------------------
# hooks/ convergence
# ---------------------------------------------------------------------------


def test_hook_error_recovery_retired() -> None:
    """hooks/error_recovery.py must be retired. Resilience belongs to RuntimeResilience."""
    error_recovery = SRC_ROOT / "hooks" / "error_recovery.py"
    assert not error_recovery.exists(), (
        "hooks/error_recovery.py should have been retired. "
        "Resilience decisions belong to core/runtime/resilience."
    )


def test_hook_manager_does_not_import_error_recovery() -> None:
    """HookManager must not depend on the retired error_recovery module."""
    hook_manager = SRC_ROOT / "hooks" / "hook_manager.py"
    if hook_manager.exists():
        text = hook_manager.read_text(encoding="utf-8", errors="ignore")
        assert "error_recovery" not in text, (
            "HookManager should not import from retired error_recovery module"
        )


# ---------------------------------------------------------------------------
# inference/ convergence
# ---------------------------------------------------------------------------


def test_inference_dependencies_retired() -> None:
    """inference/dependencies.py must be retired. Routes should use canonical services."""
    deps = SRC_ROOT / "inference" / "dependencies.py"
    assert not deps.exists(), (
        "inference/dependencies.py should have been retired. "
        "Routes should depend on canonical services, not raw inference runtimes."
    )


def test_inference_factory_no_hardcoded_model_paths() -> None:
    """InferenceServiceFactory must not contain hardcoded model paths."""
    factory = SRC_ROOT / "inference" / "factory.py"
    if factory.exists():
        text = factory.read_text(encoding="utf-8", errors="ignore")
        assert "Qwen--Qwen3.5-0.8B" not in text, (
            "Factory contains hardcoded model path"
        )
        assert "DeepSeek-R1-Distill-Qwen-1.5B" not in text, (
            "Factory contains hardcoded model path"
        )


def test_inference_factory_select_optimal_runtime_deprecated() -> None:
    """select_optimal_runtime must be deprecated with warning."""
    factory = SRC_ROOT / "inference" / "factory.py"
    if factory.exists():
        text = factory.read_text(encoding="utf-8", errors="ignore")
        assert "select_optimal_runtime" in text
        assert "DEPRECATED" in text or "deprecated" in text, (
            "select_optimal_runtime must be marked deprecated"
        )
        assert "ProviderRouter" in text or "ModelManager" in text, (
            "Deprecation should point to canonical authority"
        )


def test_no_optimal_runtime_exports() -> None:
    """get_optimal_runtime and get_any_available_runtime must not be exported."""
    init = SRC_ROOT / "inference" / "__init__.py"
    if init.exists():
        text = init.read_text(encoding="utf-8", errors="ignore")
        assert "get_optimal_runtime" not in text, (
            "get_optimal_runtime should not be exported from inference package"
        )
        assert "get_any_available_runtime" not in text, (
            "get_any_available_runtime should not be exported from inference package"
        )


# ---------------------------------------------------------------------------
# infra/ convergence
# ---------------------------------------------------------------------------


def test_infra_query_analyzer_retired() -> None:
    """infra/internal/query_analyzer.py must be retired.
    Intelligence signals belong to IntelligenceRuntime."""
    analyzer = SRC_ROOT / "infra" / "internal" / "query_analyzer.py"
    assert not analyzer.exists(), (
        "infra/internal/query_analyzer.py should have been retired. "
        "Query analysis belongs to core/intelligence IntelligenceRuntime."
    )


def test_infra_legacy_cache_system_retired() -> None:
    """Legacy infra/integrated_cache_system.py must be retired.
    Canonical version lives in services/database/cache/."""
    cache = SRC_ROOT / "infra" / "integrated_cache_system.py"
    assert not cache.exists(), (
        "Legacy infra/integrated_cache_system.py should have been retired. "
        "Canonical version is in services/database/cache/."
    )


def test_infra_legacy_cache_backends_retired() -> None:
    """Legacy infra/internal/cache_backends.py must be retired."""
    backends = SRC_ROOT / "infra" / "internal" / "cache_backends.py"
    assert not backends.exists(), (
        "Legacy infra/internal/cache_backends.py should have been retired."
    )


def test_canonical_cache_system_exists() -> None:
    """Canonical cache system must exist in services/database/cache/."""
    canonical = SRC_ROOT / "services" / "database" / "cache" / "integrated_cache_system.py"
    assert canonical.exists(), (
        "Canonical cache system must exist at services/database/cache/"
    )


# ---------------------------------------------------------------------------
# Canonical ownership integrity
# ---------------------------------------------------------------------------


def test_intelligence_runtime_exists() -> None:
    """IntelligenceRuntime must exist as canonical intelligence authority."""
    rt = SRC_ROOT / "core" / "intelligence" / "intelligence_runtime.py"
    assert rt.exists(), "core/intelligence/intelligence_runtime.py must exist"


def test_runtime_resilience_exists() -> None:
    """RuntimeResilience circuit breaker must exist as canonical resilience authority."""
    cb = SRC_ROOT / "core" / "runtime" / "resilience" / "circuit_breaker.py"
    assert cb.exists(), "core/runtime/resilience/circuit_breaker.py must exist"


def test_runtime_policy_exists() -> None:
    """RuntimePolicy must exist as canonical authorization authority."""
    policy = SRC_ROOT / "core" / "runtime" / "policy" / "runtime_policy.py"
    assert policy.exists(), "core/runtime/policy/runtime_policy.py must exist"


def test_model_manager_exists() -> None:
    """ModelManager must exist as canonical model selection authority."""
    mm = SRC_ROOT / "core" / "model_runtime" / "model_manager.py"
    assert mm.exists(), "core/model_runtime/model_manager.py must exist"


# ---------------------------------------------------------------------------
# Dependency direction
# ---------------------------------------------------------------------------


def test_infra_does_not_import_domain_services() -> None:
    """infra/ must not import CORTEX, ChatRuntime, agent planner, or RuntimePolicy."""
    infra_root = SRC_ROOT / "infra"
    if not infra_root.exists():
        return

    forbidden_imports = [
        "from ai_karen_engine.core.cortex",
        "from ai_karen_engine.core.runtime.chat_runtime",
        "from ai_karen_engine.core.runtime.policy",
        "from ai_karen_engine.agents",
    ]

    for py_file in infra_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for forbidden in forbidden_imports:
            assert forbidden not in text, (
                f"{py_file} imports forbidden domain service: {forbidden}"
            )


def test_health_endpoints_use_canonical_redis_manager() -> None:
    """health_endpoints.py must import redis_connection_manager from canonical location."""
    health = SRC_ROOT / ".." / ".." / "server" / "health_endpoints.py"
    if health.exists():
        text = health.read_text(encoding="utf-8", errors="ignore")
        assert "ai_karen_engine.infra.redis_connection_manager" not in text, (
            "health_endpoints.py should import redis_connection_manager from "
            "core.memory, not from retired infra package"
        )


# ---------------------------------------------------------------------------
# Hook trust & criticality
# ---------------------------------------------------------------------------


def test_hook_trust_levels_defined() -> None:
    """HookTrustLevel enum must exist with all three levels."""
    from ai_karen_engine.hooks.hook_types import HookTrustLevel
    assert HookTrustLevel.OBSERVATIONAL.value == "observational"
    assert HookTrustLevel.TRANSFORMATIONAL.value == "transformational"
    assert HookTrustLevel.SIDE_EFFECTING.value == "side_effecting"


def test_hook_criticality_defined() -> None:
    """HookCriticality enum must exist with all three levels."""
    from ai_karen_engine.hooks.hook_types import HookCriticality
    assert HookCriticality.BEST_EFFORT.value == "best_effort"
    assert HookCriticality.IMPORTANT.value == "important"
    assert HookCriticality.CRITICAL.value == "critical"


def test_hook_registration_accepts_trust_and_criticality() -> None:
    """HookRegistration must accept trust_level and criticality parameters."""
    from ai_karen_engine.hooks.models import HookRegistration

    reg = HookRegistration(
        id="test_1",
        hook_type="pre_message",
        handler=lambda ctx: None,
        priority=50,
        conditions={},
        source_type="test",
        trust_level="side_effecting",
        criticality="important",
    )
    assert reg.trust_level == "side_effecting"
    assert reg.criticality == "important"


def test_hook_registration_validates_trust_level() -> None:
    """HookRegistration must reject invalid trust levels."""
    from ai_karen_engine.hooks.models import HookRegistration

    with pytest.raises(ValueError, match="trust_level"):
        HookRegistration(
            id="test_1",
            hook_type="pre_message",
            handler=lambda ctx: None,
            priority=50,
            conditions={},
            source_type="test",
            trust_level="invalid_value",
        )


def test_hook_recursion_protection() -> None:
    """HookManager must prevent infinite hook recursion."""
    import asyncio
    from ai_karen_engine.hooks.hook_manager import HookManager
    from ai_karen_engine.hooks.models import HookContext

    manager = HookManager()

    async def recursive_hook(context):
        # This would cause infinite recursion without protection
        await manager.trigger_hooks(context)

    import asyncio
    loop = asyncio.new_event_loop()
    try:
        hook_id = loop.run_until_complete(
            manager.register_hook(
                hook_type="pre_message",
                handler=recursive_hook,
                source_type="test",
            )
        )
        context = HookContext(hook_type="pre_message", data={})
        summary = loop.run_until_complete(manager.trigger_hooks(context))
        # Should complete without stack overflow — recursion is bounded
        assert summary is not None
    finally:
        loop.close()


def test_hook_deterministic_ordering() -> None:
    """Hooks with same priority must execute in registration order."""
    import asyncio
    from ai_karen_engine.hooks.hook_manager import HookManager
    from ai_karen_engine.hooks.models import HookContext

    manager = HookManager()
    execution_order = []

    def make_hook(name):
        def handler(ctx):
            execution_order.append(name)
        return handler

    loop = asyncio.new_event_loop()
    try:
        for name in ["first", "second", "third"]:
            loop.run_until_complete(
                manager.register_hook(
                    hook_type="post_message",
                    handler=make_hook(name),
                    priority=50,
                    source_type="test",
                )
            )

        context = HookContext(hook_type="post_message", data={})
        loop.run_until_complete(manager.trigger_hooks(context))

        assert execution_order == ["first", "second", "third"]
    finally:
        loop.close()
