from __future__ import annotations

from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_karen_engine"
MEDUSA_ROOT = SRC_ROOT / "agent_medusa"
COORDINATOR_PATH = MEDUSA_ROOT / "coordinator" / "medusa_coordinator.py"
SUBAGENT_PATH = MEDUSA_ROOT / "contracts" / "subagent_contract.py"


def _python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def test_agent_medusa_is_independent_of_legacy_agents_package() -> None:
    assert MEDUSA_ROOT.exists(), "AgentMedusa canonical runtime must exist"

    offenders: list[str] = []
    for path in _python_sources(MEDUSA_ROOT):
        source = path.read_text(encoding="utf-8-sig")
        if "ai_karen_engine.agents" in source or "from ..agents" in source or "from ...agents" in source:
            offenders.append(str(path.relative_to(SRC_ROOT)))

    assert not offenders, (
        "AgentMedusa must not depend on the legacy agents package. "
        f"Found legacy dependencies: {offenders}"
    )


def test_medusa_coordinator_requires_runtime_policy_authorization() -> None:
    source = COORDINATOR_PATH.read_text(encoding="utf-8-sig")

    assert "requires an authorized_plan from RuntimePolicy" in source
    assert "Medusa must not synthesize its own authorization" in source
    assert "AuthorizedExecutionPlan" in source


def test_medusa_coordinator_does_not_own_provider_or_prompt_authority() -> None:
    source = COORDINATOR_PATH.read_text(encoding="utf-8-sig")

    forbidden = {
        "get_provider_registry(",
        "get_llm_router(",
        "ProviderRegistry(",
        "LLMRouter(",
        "PromptAssembler(",
        "get_prompt_assembler(",
        "system_prompt_template =",
    }
    found = sorted(pattern for pattern in forbidden if pattern in source)

    assert not found, (
        "MedusaCoordinator is a multi-agent topology coordinator, not provider/prompt authority. "
        f"Found forbidden ownership patterns: {found}"
    )


def test_subagent_action_validation_is_fail_closed() -> None:
    source = SUBAGENT_PATH.read_text(encoding="utf-8-sig")

    assert "return normalized in set(self.allowed_actions)" in source
    assert "if not normalized:" in source
    assert "return False" in source
