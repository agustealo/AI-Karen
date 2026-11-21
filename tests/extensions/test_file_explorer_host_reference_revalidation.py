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

    def get_record(self, plugin_id):
        assert plugin_id == "file-explorer"
        return {"status": "enabled" if self.enabled else "disabled",
                "dependencies_resolved": True}


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
