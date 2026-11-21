"""File Explorer trusted host reference verification tests."""
from dataclasses import replace

import pytest

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import ExtensionExecutionContext
from ai_karen_engine.extensions.file_explorer_inventory import FileExplorerInventoryHost

TENANT = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
SOURCE_ID = "44444444-4444-4444-8444-000000000001"
REVISION = "a" * 64


def context(**kwargs):
    return replace(ExtensionExecutionContext(
        request_id="r", correlation_id="c", user_id=OWNER,
        tenant_id=TENANT, session_id="s", policy_decision_id="policy",
        allowed_capabilities=["file-explorer"], resource_scope={},
    ), **kwargs)


def plan(**kwargs):
    return replace(AuthorizedExecutionPlan(
        execution_id="e", policy_decision_id="policy",
        authorized_user_id=OWNER, authorized_tenant_id=TENANT,
        authorized_session_id="s", allowed_plugins=["file-explorer"],
        allowed_capabilities=["file-explorer"],
    ), **kwargs)


class Source:
    def __init__(self):
        self.calls = []
        self.evidence = {
            "source_id": SOURCE_ID, "revision": REVISION,
            "owner_scope_verified": True,
            "access_semantics": "owner_only_at_lookup_time_not_transferable_grant",
        }

    async def revalidate_owner_reference(self, **kwargs):
        self.calls.append(kwargs)
        return self.evidence


class Kernel:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls = []

    def get_record(self, plugin_id):
        assert plugin_id == "file-explorer"
        return {"status": "enabled" if self.enabled else "disabled",
                "dependencies_resolved": True}

    async def execute(self, request):
        from types import SimpleNamespace

        self.calls.append(request)
        roles = request.context.audit_context.get("user_roles", ["user"])
        if not any(role in {"user", "admin", "developer"} for role in roles):
            return SimpleNamespace(status="denied", payload=None)
        if request.context.resource_scope.get("file_explorer_entries") != []:
            return SimpleNamespace(status="denied", payload=None)
        return SimpleNamespace(status="success", payload={"operation": "list", "items": []})


@pytest.mark.asyncio
async def test_revalidation_keeps_metadata_owner_scoped_and_nontransferable():
    owner = Source()
    host = FileExplorerInventoryHost(kernel=Kernel(), source=owner)
    result = await host.revalidate_owner_selection(
        context=context(), plan=plan(), source_id=SOURCE_ID,
        expected_revision=REVISION.upper(),
    )
    assert owner.calls == [{
        "tenant_id": TENANT, "user_id": OWNER,
        "source_id": SOURCE_ID, "expected_revision": REVISION.upper(),
    }]
    assert result["revision"] == REVISION
    assert result["owner_scope_verified"] is True
    assert "bytes" not in result
    assert "storage_key" not in result
    assert "access_token" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("ctx,authorization", [
    (context(user_id=OTHER), plan()),
    (context(tenant_id=OTHER), plan()),
    (context(resource_scope={"file_explorer_grant": "host_verified"}), plan()),
    (context(allowed_capabilities=[]), plan()),
    (context(), plan(allowed_plugins=[])),
    (context(), plan(authorized_user_id=OTHER)),
])
async def test_invalid_scope_never_reaches_source(ctx, authorization):
    owner = Source()
    host = FileExplorerInventoryHost(kernel=Kernel(), source=owner)
    with pytest.raises(PermissionError):
        await host.revalidate_owner_selection(
            context=ctx, plan=authorization, source_id=SOURCE_ID,
            expected_revision=REVISION,
        )
    assert owner.calls == []


@pytest.mark.asyncio
async def test_invalid_source_or_disabled_plugin_fails_closed():
    for identifier, revision, enabled in [
        (SOURCE_ID, REVISION, False),
        ("../../private", REVISION, True),
        (SOURCE_ID, "invalid", True),
    ]:
        owner = Source()
        with pytest.raises(PermissionError):
            await FileExplorerInventoryHost(
                kernel=Kernel(enabled), source=owner,
            ).revalidate_owner_selection(
                context=context(), plan=plan(),
                source_id=identifier, expected_revision=revision,
            )
        assert owner.calls == []


@pytest.mark.asyncio
async def test_repository_must_confirm_verified_owner():
    owner = Source()
    owner.evidence["owner_scope_verified"] = False
    with pytest.raises(PermissionError, match="revalidation_invalid"):
        await FileExplorerInventoryHost(
            kernel=Kernel(), source=owner,
        ).revalidate_owner_selection(
            context=context(), plan=plan(),
            source_id=SOURCE_ID, expected_revision=REVISION,
        )


class ArtifactRepository:
    """Controlled repository exercising the real canonical artifact adapter."""

    def __init__(self):
        self.metadata_calls = []
        self.artifact = {
            "id": SOURCE_ID,
            "tenant_id": TENANT,
            "user_id": OWNER,
            "filename": "notes.txt",
            "size_bytes": 16,
            "sha256": REVISION,
            "deleted_at": None,
        }

    async def list_owner_artifacts_page(self, *args, **kwargs):
        raise AssertionError("Reference revalidation must not use list results")

    async def get_metadata(self, artifact_id, tenant_id):
        from types import SimpleNamespace

        self.metadata_calls.append((artifact_id, tenant_id))
        return SimpleNamespace(
            success=True,
            data=SimpleNamespace(**self.artifact),
        )


@pytest.mark.asyncio
async def test_real_artifact_adapter_denies_revision_change_and_owner_revocation():
    from importlib import import_module

    adapter_module = import_module(
        "ai_karen_engine.extensions.plugins.file-explorer.artifact_source"
    )
    repository = ArtifactRepository()
    host = FileExplorerInventoryHost(
        kernel=Kernel(),
        source=adapter_module.ArtifactSourceAdapter(repository),
    )
    kwargs = dict(
        context=context(), plan=plan(), source_id=SOURCE_ID,
        expected_revision=REVISION,
    )
    first = await host.revalidate_owner_selection(**kwargs)
    assert first["source_id"] == SOURCE_ID
    assert "storage_key" not in first
    repository.artifact["sha256"] = "b" * 64
    with pytest.raises(PermissionError, match="source_revision_changed"):
        await host.revalidate_owner_selection(**kwargs)
    repository.artifact["sha256"] = REVISION
    repository.artifact["user_id"] = OTHER
    with pytest.raises(PermissionError, match="source_unavailable"):
        await host.revalidate_owner_selection(**kwargs)
    repository.artifact["user_id"] = OWNER
    from datetime import datetime, timezone

    repository.artifact["deleted_at"] = datetime.now(timezone.utc)
    with pytest.raises(PermissionError, match="source_unavailable"):
        await host.revalidate_owner_selection(**kwargs)
    assert repository.metadata_calls == [(SOURCE_ID, TENANT)] * 4


@pytest.mark.asyncio
async def test_real_artifact_adapter_rejects_cross_tenant_metadata():
    from importlib import import_module

    adapter_module = import_module(
        "ai_karen_engine.extensions.plugins.file-explorer.artifact_source"
    )
    repository = ArtifactRepository()
    repository.artifact["tenant_id"] = OTHER
    host = FileExplorerInventoryHost(
        kernel=Kernel(),
        source=adapter_module.ArtifactSourceAdapter(repository),
    )
    with pytest.raises(PermissionError, match="source_unavailable"):
        await host.revalidate_owner_selection(
            context=context(), plan=plan(),
            source_id=SOURCE_ID, expected_revision=REVISION,
        )
    assert repository.metadata_calls == [(SOURCE_ID, TENANT)]


@pytest.mark.asyncio
async def test_guest_role_denied_by_kernel_before_repository_access():
    owner = Source()
    kernel = Kernel()
    host = FileExplorerInventoryHost(kernel=kernel, source=owner)
    with pytest.raises(PermissionError, match="file_explorer_kernel_denied"):
        await host.revalidate_owner_selection(
            context=context(audit_context={"user_roles": ["guest"]}),
            plan=plan(), source_id=SOURCE_ID, expected_revision=REVISION,
        )
    assert owner.calls == []
    assert len(kernel.calls) == 1
    assert kernel.calls[0].context.resource_scope["file_explorer_entries"] == []


@pytest.mark.asyncio
async def test_canonical_admission_uses_empty_host_snapshot_and_plan():
    owner = Source()
    kernel = Kernel()
    await FileExplorerInventoryHost(kernel=kernel, source=owner).revalidate_owner_selection(
        context=context(), plan=plan(), source_id=SOURCE_ID,
        expected_revision=REVISION,
    )
    assert len(kernel.calls) == 1
    assert kernel.calls[0].authorized_plan.policy_decision_id == "policy"
    assert kernel.calls[0].payload == {"operation": "list"}
    assert kernel.calls[0].context.resource_scope == {
        "file_explorer_grant": "host_verified",
        "file_explorer_entries": [],
    }
