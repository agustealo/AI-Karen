from ai_karen_engine.extensions.unified.core.cortex_execution_registry import (
    CortexExecutionContext,
    CortexExecutionRegistry,
    CortexPluginRecord,
)


class _OkHandler:
    @staticmethod
    def run(user_ctx, query, context):
        return {"answer": query, "debug_internal": "remove-me"}


class _FailHandler:
    @staticmethod
    def run(user_ctx, query, context):
        raise RuntimeError("boom")


def _registry(record: CortexPluginRecord) -> CortexExecutionRegistry:
    registry = CortexExecutionRegistry()
    registry.register_plugins([record])
    return registry


def test_denied_permissions():
    registry = _registry(
        CortexPluginRecord("tool-a", _OkHandler, "core", {"entrypoint": "handler", "required_roles": ["admin"]})
    )
    try:
        registry.execute(CortexExecutionContext("tool-a", {"cortex_eligible": True, "roles": ["user"]}, "q"))
        assert False, "Expected RBAC denial"
    except PermissionError:
        pass


def test_manifest_validation_failure():
    registry = _registry(CortexPluginRecord("tool-a", _OkHandler, "core", {"required_roles": []}))
    try:
        registry.execute(CortexExecutionContext("tool-a", {"cortex_eligible": True, "roles": ["admin"]}, "q"))
        assert False, "Expected manifest validation failure"
    except ValueError:
        pass


def test_audited_success_and_safe_injection():
    events = []
    registry = _registry(CortexPluginRecord("tool-a", _OkHandler, "core", {"entrypoint": "handler"}))
    result = registry.execute(CortexExecutionContext("tool-a", {"cortex_eligible": True, "roles": []}, "hello", stream=events.append))

    assert result == {"answer": "hello"}
    assert registry.audit_events[-1].outcome == "success"
    assert any(evt["event"] == "tool.executed" for evt in events)


def test_audited_failure_and_stream_event():
    events = []
    registry = _registry(CortexPluginRecord("tool-a", _FailHandler, "core", {"entrypoint": "handler"}))
    try:
        registry.execute(CortexExecutionContext("tool-a", {"cortex_eligible": True, "roles": []}, "hello", stream=events.append))
        assert False, "Expected execution failure"
    except RuntimeError:
        pass

    assert registry.audit_events[-1].outcome == "failed"
    assert any(evt["event"] == "tool.execution_failed" for evt in events)
