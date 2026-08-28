from __future__ import annotations

from ai_karen_engine.core.context import (
    CognitiveContext,
    ContextRequirement,
    ContextRequirements,
    EvidenceSource,
)


def test_context_requirements_preserve_legacy_default_tenant_without_hiding_it() -> None:
    requirements = ContextRequirements(
        request_id="request-1",
        correlation_id="correlation-1",
        tenant_id="default",
        user_id="user-1",
        requirements=[
            ContextRequirement(
                source=EvidenceSource.MEMORY,
                capability="memory.read",
                scopes=["session"],
                max_items=5,
            )
        ],
    )

    assert requirements.uses_legacy_default_tenant is True
    assert requirements.to_dict()["legacy_default_tenant"] is True

    context = CognitiveContext(
        context_id="context-1",
        request_id="request-1",
        correlation_id="correlation-1",
        tenant_id="default",
        user_id="user-1",
        requirements=requirements,
        authorized_sources=["memory"],
        unresolved_sources=["memory"],
    )

    assert context.uses_legacy_default_tenant is True


def test_context_requirements_deduplicate_requested_capabilities() -> None:
    requirements = ContextRequirements(
        request_id="request-1",
        correlation_id="correlation-1",
        tenant_id="tenant-1",
        user_id="user-1",
        requirements=[
            ContextRequirement(
                source=EvidenceSource.MEMORY,
                capability="memory.read",
            ),
            ContextRequirement(
                source=EvidenceSource.USER_MODEL,
                capability="memory.read",
            ),
        ],
    )

    assert requirements.requested_capabilities == ["memory.read"]
