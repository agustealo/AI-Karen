"""Prove Content Intelligence owner-text admission is scoped and fail-closed."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import ExtensionExecutionContext
from ai_karen_engine.extensions.content_intelligence_sources import ContentSourceHost

TENANT = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
FILE_ID = "44444444-4444-4444-8444-000000000001"
TEXT = "Vendor delivery pending and budget approved."
DIGEST = hashlib.sha256(TEXT.encode()).hexdigest()
REFS = [{"source_id": FILE_ID, "revision": DIGEST}]


def context(**changes):
    return replace(ExtensionExecutionContext(
        request_id="req", correlation_id="corr", tenant_id=TENANT,
        user_id=OWNER, session_id="session", policy_decision_id="policy",
        allowed_capabilities=["content-intelligence", "data:read"],
        resource_scope={},
    ), **changes)


def plan(**changes):
    return replace(AuthorizedExecutionPlan(
        execution_id="exec", policy_decision_id="policy",
        authorized_tenant_id=TENANT, authorized_user_id=OWNER,
        authorized_session_id="session",
        allowed_plugins=["content-intelligence"],
        allowed_capabilities=["content-intelligence", "data:read"],
    ), **changes)


class Store:
    def __init__(self):
        self.calls = []
        self.available = True
        self.artifact = SimpleNamespace(
            artifact_id=FILE_ID, tenant_id=TENANT, user_id=OWNER,
            filename="notes.txt", text=TEXT, sha256=DIGEST,
        )

    async def read_owner_active_code(self, source_id, tenant_id, user_id):
        self.calls.append((source_id, tenant_id, user_id))
        return SimpleNamespace(success=self.available, data=self.artifact)


class Kernel:
    def __init__(self):
        self.calls = []
        self.enabled = True
        self.allowed_roles = {"user", "admin", "developer"}

    def get_record(self, name):
        assert name == "content-intelligence"
        return {"status": "enabled" if self.enabled else "disabled",
                "dependencies_resolved": True}

    async def admit(self, request):
        self.calls.append(("admit", request))
        roles = request.context.audit_context.get("user_roles", ["user"])
        if not self.allowed_roles.intersection(roles):
            return SimpleNamespace(status="denied", payload=None)
        return SimpleNamespace(status="admitted", payload=None)

    async def execute(self, request):
        self.calls.append(("execute", request))
        documents = request.payload["documents"]
        operation = request.payload["operation"]
        if operation == "analyze":
            output = {
                "operation": operation, "persisted": False,
                "documents": [{
                    "id": doc["id"], "name": doc["name"],
                    "sha256": hashlib.sha256(doc["text"].encode()).hexdigest(),
                    "characters": len(doc["text"]), "top_terms": [],
                } for doc in documents],
            }
        elif operation == "compare":
            by_id = {doc["id"]: doc for doc in documents}
            left = by_id[request.payload["left_id"]]
            right = by_id[request.payload["right_id"]]
            output = {
                "operation": operation, "persisted": False,
                "left_id": left["id"], "right_id": right["id"],
                "left_sha256": hashlib.sha256(left["text"].encode()).hexdigest(),
                "right_sha256": hashlib.sha256(right["text"].encode()).hexdigest(),
            }
        else:
            output = {
                "operation": operation, "persisted": False,
                "query": request.payload["query"], "matches": [],
            }
        return SimpleNamespace(status="success", payload=output)


@pytest.mark.asyncio
async def test_owner_text_only_reaches_kernel_after_verified_read():
    store, kernel = Store(), Kernel()
    answer = await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
        context=context(), plan=plan(), operation="analyze", references=REFS,
    )
    assert answer["operation"] == "analyze"
    assert answer["persisted"] is False
    assert answer["documents"][0]["sha256"] == DIGEST
    assert store.calls == [(FILE_ID, TENANT, OWNER)]
    assert len(kernel.calls) == 2
    assert kernel.calls[0][0] == "admit"
    assert kernel.calls[0][1].payload == {}
    assert kernel.calls[1][0] == "execute"
    assert kernel.calls[1][1].payload["documents"] == [{
        "id": FILE_ID, "name": "notes.txt", "text": TEXT,
    }]
    assert kernel.calls[1][1].authorized_plan.policy_decision_id == "policy"


@pytest.mark.asyncio
@pytest.mark.parametrize("ctx,auth", [
    (context(user_id=OTHER), plan()),
    (context(tenant_id=OTHER), plan()),
    (context(resource_scope={"override": "yes"}), plan()),
    (context(), plan(resource_scope={"attachment_references": REFS})),
    (context(), plan(resource_scope={"override": "yes"})),
    (context(allowed_capabilities=[]), plan()),
    (context(), plan(allowed_plugins=[])),
    (context(), plan(allowed_capabilities=["content-intelligence"])),
])
async def test_invalid_authorization_never_reads_storage(ctx, auth):
    store, kernel = Store(), Kernel()
    with pytest.raises(PermissionError, match="authorization_required"):
        await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
            context=ctx, plan=auth, operation="analyze", references=REFS,
        )
    assert not store.calls
    assert not kernel.calls


@pytest.mark.asyncio
async def test_stale_revision_revoked_owner_and_changed_bytes_denied():
    store, kernel = Store(), Kernel()
    host = ContentSourceHost(store=store, kernel=kernel)
    args = dict(
        context=context(), plan=plan(), operation="analyze", references=REFS,
    )
    store.available = False
    with pytest.raises(PermissionError, match="unavailable"):
        await host.execute_owner_text(**args)
    store.available = True
    store.artifact.sha256 = "b" * 64
    with pytest.raises(PermissionError, match="evidence_invalid"):
        await host.execute_owner_text(**args)
    store.artifact.sha256 = DIGEST
    store.artifact.text = "tampered"
    with pytest.raises(PermissionError, match="evidence_invalid"):
        await host.execute_owner_text(**args)
    store.artifact.text = TEXT
    store.artifact.user_id = OTHER
    with pytest.raises(PermissionError, match="evidence_invalid"):
        await host.execute_owner_text(**args)
    assert len(kernel.calls) == 4
    assert all(kind == "admit" for kind, request in kernel.calls)


@pytest.mark.asyncio
async def test_forged_sources_and_disabled_plugin_fail_before_storage():
    store, kernel = Store(), Kernel()
    kernel.enabled = False
    host = ContentSourceHost(store=store, kernel=kernel)
    with pytest.raises(PermissionError, match="plugin_disabled"):
        await host.execute_owner_text(
            context=context(), plan=plan(), operation="analyze", references=REFS,
        )
    kernel.enabled = True
    for invalid in [
        REFS * 2,
        [{"source_id": FILE_ID, "revision": DIGEST, "text": TEXT}],
        [{"source_id": "../../etc/passwd", "revision": DIGEST}],
    ]:
        with pytest.raises(PermissionError, match="reference_invalid"):
            await host.execute_owner_text(
                context=context(), plan=plan(), operation="analyze",
                references=invalid,
            )
    assert not store.calls


@pytest.mark.asyncio
async def test_guest_role_fails_canonical_kernel_admission_without_source_read():
    store, kernel = Store(), Kernel()
    with pytest.raises(PermissionError, match="kernel_admission_denied"):
        await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
            context=context(audit_context={"user_roles": ["guest"]}),
            plan=plan(), operation="analyze", references=REFS,
        )
    assert store.calls == []
    assert len(kernel.calls) == 1
    assert kernel.calls[0][0] == "admit"
    assert kernel.calls[0][1].payload == {}


class TamperingKernel(Kernel):
    def __init__(self, change):
        super().__init__()
        self.change = change

    async def execute(self, request):
        result = await super().execute(request)
        self.change(result.payload)
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    lambda payload: payload.update({"persisted": True}),
    lambda payload: payload["documents"][0].update({"id": OTHER}),
    lambda payload: payload["documents"][0].update({"sha256": "f" * 64}),
    lambda payload: payload["documents"][0].update({"characters": 1}),
    lambda payload: payload["documents"][0].update({"name": "foreign.txt"}),
    lambda payload: payload["documents"][0].update({"folder_id": "foreign-folder"}),
    lambda payload: payload["documents"].append(dict(payload["documents"][0])),
    lambda payload: payload["documents"][0].update({"top_terms": [{"term": "x", "count": -1}]}),
])
async def test_analysis_output_must_match_admitted_owner_source(change):
    store, kernel = Store(), TamperingKernel(change)
    with pytest.raises(RuntimeError, match="content_source_output_invalid"):
        await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
            context=context(), plan=plan(), operation="analyze", references=REFS,
        )
    assert store.calls == [(FILE_ID, TENANT, OWNER)]


@pytest.mark.asyncio
async def test_search_hits_cannot_claim_mismatched_source_bytes():
    store = Store()
    def forge(payload):
        payload["matches"] = [{
            "document_id": FILE_ID,
            "document_name": "notes.txt",
            "sha256": DIGEST,
            "offset": 0,
            "end_offset": 6,
            "excerpt": "UNTRUE",
        }]
    kernel = TamperingKernel(forge)
    with pytest.raises(RuntimeError, match="content_source_output_invalid"):
        await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
            context=context(), plan=plan(), operation="search", references=REFS,
            query="vendor",
        )


@pytest.mark.asyncio
async def test_authentic_search_hits_preserve_verified_owner_span():
    store = Store()
    def real_hit(payload):
        payload["matches"] = [{
            "document_id": FILE_ID, "document_name": "notes.txt",
            "sha256": DIGEST, "offset": 0, "end_offset": 6,
            "excerpt": TEXT[:6],
        }]
    kernel = TamperingKernel(real_hit)
    result = await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
        context=context(), plan=plan(), operation="search", references=REFS,
        query="vendor",
    )
    assert result["matches"][0]["excerpt"] == TEXT[:6]


@pytest.mark.asyncio
async def test_compare_rejects_substituted_revision():
    second_id = "44444444-4444-4444-8444-000000000002"

    class TwoSources(Store):
        async def read_owner_active_code(self, source_id, tenant_id, user_id):
            result = await super().read_owner_active_code(source_id, tenant_id, user_id)
            if source_id == second_id:
                result.data = SimpleNamespace(
                    artifact_id=second_id, tenant_id=TENANT, user_id=OWNER,
                    filename="second.txt", text=TEXT, sha256=DIGEST,
                )
            return result

    kernel = TamperingKernel(
        lambda payload: payload.update({"right_sha256": "f" * 64})
    )
    with pytest.raises(RuntimeError, match="content_source_output_invalid"):
        await ContentSourceHost(store=TwoSources(), kernel=kernel).execute_owner_text(
            context=context(), plan=plan(), operation="compare",
            references=REFS + [{"source_id": second_id, "revision": DIGEST}],
            left_id=FILE_ID, right_id=second_id,
        )


class InputMutatingKernel(Kernel):
    """Adversarial kernel changes the execution payload before making a receipt."""

    async def execute(self, request):
        assert request.payload["operation"] == "analyze"
        forged_id = OTHER
        mutated = request.payload["documents"][0]
        mutated["id"] = forged_id
        mutated["name"] = "forged.txt"
        mutated["text"] = "completely different unapproved source"
        return await super().execute(request)


@pytest.mark.asyncio
async def test_kernel_mutation_cannot_redefine_authorized_source_evidence():
    """Returned values matching forged plugin input remain unauthorized."""
    store, kernel = Store(), InputMutatingKernel()
    with pytest.raises(RuntimeError, match="content_source_output_invalid"):
        await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
            context=context(), plan=plan(), operation="analyze", references=REFS,
        )
    assert store.calls == [(FILE_ID, TENANT, OWNER)]
    assert len(kernel.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("relationship", [
    {"left_id": FILE_ID, "right_id": OTHER},
    {"left_id": OTHER, "right_id": FILE_ID},
    {"left_id": FILE_ID, "right_id": FILE_ID},
    {"left_id": FILE_ID, "right_id": 42},
])
async def test_analysis_relationship_cannot_reference_unauthorized_source(relationship):
    """Plugin success cannot endorse a foreign or invalid source pair."""
    kernel = TamperingKernel(
        lambda payload: payload.update({"relationships": [relationship]})
    )
    with pytest.raises(RuntimeError, match="content_source_output_invalid"):
        await ContentSourceHost(store=Store(), kernel=kernel).execute_owner_text(
            context=context(), plan=plan(), operation="analyze", references=REFS,
        )


@pytest.mark.asyncio
async def test_analysis_relationship_between_verified_sources_is_preserved():
    """Authorized pair relationships remain usable by clients."""
    second_id = "44444444-4444-4444-8444-000000000002"

    class TwoSources(Store):
        async def read_owner_active_code(self, source_id, tenant_id, user_id):
            result = await super().read_owner_active_code(
                source_id, tenant_id, user_id
            )
            if source_id == second_id:
                result.data = SimpleNamespace(
                    artifact_id=second_id, tenant_id=TENANT, user_id=OWNER,
                    filename="second.txt", text=TEXT, sha256=DIGEST,
                )
            return result

    pair = {"left_id": FILE_ID, "right_id": second_id}
    kernel = TamperingKernel(
        lambda payload: payload.update({"relationships": [pair]})
    )
    result = await ContentSourceHost(
        store=TwoSources(), kernel=kernel
    ).execute_owner_text(
        context=context(), plan=plan(), operation="analyze",
        references=REFS + [{"source_id": second_id, "revision": DIGEST}],
    )
    assert result["relationships"] == [pair]


@pytest.mark.asyncio
async def test_search_result_rejects_unverified_folder_label():
    """A search hit cannot claim folder membership the host never admitted."""
    def inject_foreign_folder(payload):
        payload["matches"] = [{
            "document_id": FILE_ID,
            "document_name": "notes.txt",
            "folder_id": "foreign-folder",
            "sha256": DIGEST,
            "offset": 0,
            "end_offset": 6,
            "excerpt": TEXT[:6],
        }]

    with pytest.raises(RuntimeError, match="content_source_output_invalid"):
        await ContentSourceHost(
            store=Store(), kernel=TamperingKernel(inject_foreign_folder)
        ).execute_owner_text(
            context=context(), plan=plan(), operation="search", references=REFS,
            query="vendor",
        )


@pytest.mark.asyncio
async def test_canonical_null_folder_labels_remain_valid():
    """The real plugin schema uses null when no folder was authorized."""
    kernel = TamperingKernel(lambda payload: payload["documents"][0].update(
        {"folder_id": None}
    ))
    result = await ContentSourceHost(store=Store(), kernel=kernel).execute_owner_text(
        context=context(), plan=plan(), operation="analyze", references=REFS,
    )
    assert result["documents"][0]["folder_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["replace", "append", "clear", "revision"])
async def test_owner_selection_is_pinned_before_kernel_admission(mutation):
    store = Store()
    references = [dict(REFS[0])]

    class MutatingAdmissionKernel(Kernel):
        async def admit(self, request):
            result = await super().admit(request)
            if mutation == "replace":
                references[0]["source_id"] = OTHER
            elif mutation == "append":
                references.append({"source_id": OTHER, "revision": DIGEST})
            elif mutation == "clear":
                references.clear()
            else:
                references[0]["revision"] = "b" * 64
            return result

    kernel = MutatingAdmissionKernel()
    answer = await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
        context=context(), plan=plan(), operation="analyze", references=references,
    )
    assert store.calls == [(FILE_ID, TENANT, OWNER)]
    assert len(answer["documents"]) == 1
    assert answer["documents"][0]["id"] == FILE_ID
    assert answer["documents"][0]["sha256"] == DIGEST
    assert kernel.calls[1][1].payload["documents"][0]["id"] == FILE_ID


@pytest.mark.asyncio
async def test_owner_selection_remains_pinned_during_storage_read():
    second_id = "44444444-4444-4444-8444-000000000002"
    references = [dict(REFS[0]), {"source_id": second_id, "revision": DIGEST}]

    class MutatingStore(Store):
        async def read_owner_active_code(self, source_id, tenant_id, user_id):
            result = await super().read_owner_active_code(source_id, tenant_id, user_id)
            if source_id == FILE_ID:
                references[0]["revision"] = "c" * 64
                references[1]["source_id"] = OTHER
            return SimpleNamespace(
                success=result.success,
                data=SimpleNamespace(**{**vars(result.data), "artifact_id": source_id}),
            )

    store, kernel = MutatingStore(), Kernel()
    answer = await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
        context=context(), plan=plan(), operation="compare", references=references,
        left_id=FILE_ID, right_id=second_id,
    )
    assert store.calls == [(FILE_ID, TENANT, OWNER), (second_id, TENANT, OWNER)]
    assert answer["left_id"] == FILE_ID
    assert answer["right_id"] == second_id
    assert answer["left_sha256"] == answer["right_sha256"] == DIGEST


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["admission", "read", "execution"])
@pytest.mark.parametrize("scope_owner", ["plan", "context"])
async def test_standalone_scope_change_cannot_continue_owner_access(boundary, scope_owner):
    ctx, auth = context(), plan()

    def mutate_scope():
        target = auth if scope_owner == "plan" else ctx
        target.resource_scope["attachment_references"] = REFS

    class ScopeChangingStore(Store):
        async def read_owner_active_code(self, *args):
            response = await super().read_owner_active_code(*args)
            if boundary == "read":
                mutate_scope()
            return response

    class ScopeChangingKernel(Kernel):
        async def admit(self, request):
            result = await super().admit(request)
            if boundary == "admission":
                mutate_scope()
            return result

        async def execute(self, request):
            result = await super().execute(request)
            if boundary == "execution":
                mutate_scope()
            return result

    store, kernel = ScopeChangingStore(), ScopeChangingKernel()
    with pytest.raises(PermissionError, match="content_source_authorization_required"):
        await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
            context=ctx, plan=auth, operation="analyze", references=REFS,
        )
    assert len(store.calls) == (0 if boundary == "admission" else 1)
    assert [kind for kind, _ in kernel.calls] == (
        ["admit", "execute"] if boundary == "execution" else ["admit"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,options,error", [
    ("unknown", {}, "operation_invalid"),
    ("search", {}, "query_invalid"),
    ("search", {"query": " "}, "query_invalid"),
    ("search", {"query": "x" * 513}, "query_invalid"),
    ("analyze", {"query": "vendor"}, "unused_query"),
    ("compare", {"left_id": FILE_ID, "right_id": FILE_ID}, "comparison_invalid"),
    ("analyze", {"left_id": FILE_ID}, "unused_selection"),
])
async def test_invalid_operation_shape_denied_before_admission(operation, options, error):
    store, kernel = Store(), Kernel()
    with pytest.raises(ValueError, match=error):
        await ContentSourceHost(store=store, kernel=kernel).execute_owner_text(
            context=context(), plan=plan(), operation=operation, references=REFS,
            **options,
        )
    assert not store.calls
    assert not kernel.calls
