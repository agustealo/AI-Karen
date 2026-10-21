"""Opt-in AG-UI event projection of canonical Karen chat execution.

This module is a transport projection only. It does not select models, invoke
tools, construct prompts, authorize actions, or persist messages. All events
come from the authoritative ChatRuntime stream.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _text(value: Any, limit: int = 1000) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _event_type(chunk: Any) -> str:
    value = getattr(chunk, "type", "")
    return str(getattr(value, "value", value))


def _validated_presentation(raw: Any) -> dict[str, Any] | None:
    """Allow only bounded, JSON-native, evidence-referenced UI envelopes.

    The owning runtime must supply trusted evidence; this transport check is
    defense in depth and never confers provenance or execution authority.
    """
    import json

    if not isinstance(raw, Mapping):
        return None
    allowed = {
        "schema_version", "presentation_id", "component_type",
        "data", "evidence_ref", "correlation_id",
    }
    if set(raw) - allowed or raw.get("schema_version") != 1 or type(raw.get("schema_version")) is not int:
        return None
    component_type = raw.get("component_type")
    if not isinstance(component_type, str) or component_type not in {"weather.observation", "weather.comparison"}:
        return None
    for key in ("presentation_id", "evidence_ref"):
        value = raw.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= 160:
            return None
    correlation = raw.get("correlation_id")
    if correlation is not None and (not isinstance(correlation, str) or len(correlation) > 160):
        return None
    data = raw.get("data")
    if not isinstance(data, (dict, list)):
        return None
    if raw["component_type"] == "weather.comparison" and (
        not isinstance(data, list) or not 2 <= len(data) <= 5
    ):
        return None
    if raw["component_type"] == "weather.observation" and not isinstance(data, dict):
        return None
    def weather_observation(item: Any) -> bool:
        if not isinstance(item, Mapping):
            return False
        location = item.get("location")
        if not isinstance(location, str) or not 1 <= len(location.strip()) <= 160:
            return False
        temperatures = [
            item.get(key) for key in ("temperature_f", "temperatureF")
            if key in item
        ]
        # A unitless generic temperature must not be relabeled Fahrenheit.
        if not temperatures:
            generic = item.get("temperature")
            if not (isinstance(generic, str) and generic.strip().lower().endswith("f")):
                return False
            temperatures = [generic]
        import re
        values: list[float] = []
        for temperature in temperatures:
            if type(temperature) in (int, float):
                value = float(temperature)
            elif isinstance(temperature, str) and re.fullmatch(
                r"-?\\d+(?:\\.\\d+)?\\s*(?:°\\s*F)?", temperature.strip(),
                flags=re.IGNORECASE,
            ):
                value = float(re.match(r"-?\\d+(?:\\.\\d+)?", temperature.strip()).group())
            else:
                return False
            if not -150 <= value <= 150:
                return False
            values.append(value)
        return bool(values) and max(values) - min(values) <= 0.15

    observations = data if isinstance(data, list) else [data]
    if not all(weather_observation(item) for item in observations):
        return None
    try:
        encoded = json.dumps(raw, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError):
        return None
    if len(encoded.encode("utf-8")) > 32768:
        return None
    return dict(raw)


class AGUIEventProjection:
    """Map one canonical runtime stream to one AG-UI run lifecycle.

    Runtime-provided event types are projected, never guessed. The frontend
    receives an explicit RUN_ERROR for interrupted streams, and a terminal
    RUN_FINISHED only after canonical COMPLETE. Internal metadata is not
    forwarded wholesale because it may contain credentials or tool arguments.
    """

    def __init__(self, *, thread_id: str, run_id: str) -> None:
        if not thread_id or not run_id:
            raise ValueError("AG-UI thread and run identity are required")
        self.thread_id = thread_id
        self.run_id = run_id
        self.message_id = f"assistant-{run_id}"
        self._started = False
        self._message_started = False
        self._terminal = False
        self._tool_calls: set[str] = set()
        self._subagent_runs: set[str] = set()
        self._learning_reported = False

    @property
    def terminal(self) -> bool:
        return self._terminal

    def begin(self) -> dict[str, Any]:
        if self._started:
            raise RuntimeError("AG-UI run already started")
        self._started = True
        return {
            "type": "RUN_STARTED",
            "threadId": self.thread_id,
            "runId": self.run_id,
        }

    def _finish_message(self) -> list[dict[str, Any]]:
        if not self._message_started:
            return []
        self._message_started = False
        return [{"type": "TEXT_MESSAGE_END", "messageId": self.message_id}]

    @staticmethod
    def _custom(name: str, value: dict[str, Any]) -> dict[str, Any]:
        return {"type": "CUSTOM", "name": name, "value": value}

    def project(self, chunk: Any) -> list[dict[str, Any]]:
        if not self._started:
            raise RuntimeError("AG-UI run must begin before projecting events")
        if self._terminal:
            return []

        kind = _event_type(chunk)
        content = _text(getattr(chunk, "content", ""), 100000)
        raw = getattr(chunk, "metadata", None)
        meta: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}

        if kind == "content":
            if not content:
                return []
            events: list[dict[str, Any]] = []
            if not self._message_started:
                self._message_started = True
                events.append({
                    "type": "TEXT_MESSAGE_START",
                    "messageId": self.message_id,
                    "role": "assistant",
                })
            events.append({
                "type": "TEXT_MESSAGE_CONTENT",
                "messageId": self.message_id,
                "delta": content,
            })
            # The UI may disclose *why* Karen picked a model, not raw
            # remembered facts or invented quality/performance scores.
            # Only Runtime-origin evidence is serialized here.
            if (
                not self._learning_reported
                and meta.get("execution_engine") == "deepagents"
                and meta.get("learning_signal_status") in {
                    "ready", "cold_start", "unavailable", "disabled",
                    "not_consulted",
                }
            ):
                selection = _text(meta.get("model_selection_source"), 64)
                source_status = _text(meta.get("learning_signal_status"), 32)
                context_status = _text(meta.get("learned_context_status"), 32)
                if selection in {
                    "learning_operational_reliability_v1",
                    "canonical_registry",
                    "explicit_runtime_or_user",
                    "baseline_no_learning",
                    "baseline_learning_disabled",
                    "baseline_scope_mismatch",
                    "baseline_insufficient_evidence",
                    "baseline_reliable",
                    "baseline_no_verified_alternative",
                    "shadow_operational_recommendation",
                }:
                    self._learning_reported = True
                    count = meta.get("learned_memory_refs_included")
                    events.append(self._custom("karen.learning_decision", {
                        "selection_source": selection,
                        "learning_signal_status": source_status,
                        "learning_signal_version": _text(
                            meta.get("learning_signal_version"), 64
                        ),
                        "learned_context_status": (
                            context_status if context_status in {
                                "resolved", "not_requested", "not_supplied",
                                "unavailable",
                            } else "unavailable"
                        ),
                        "included_memory_refs": (
                            min(100, count)
                            if isinstance(count, int) and not isinstance(count, bool)
                            and count >= 0 else 0
                        ),
                        "claim": "operational_evidence_only",
                    }))
            return events

        if kind == "agent_step":
            step_id = _text(meta.get("step_id"), 128)
            agent_id = _text(meta.get("agent_id"), 128)
            status = _text(meta.get("status"), 32)
            event_type = _text(meta.get("event_type"), 64)
            if not step_id or not agent_id or status not in {
                "running", "completed", "failed", "cancelled", "skipped",
            }:
                return []
            # Stable activity identity is scoped by the AG-UI run. A new run
            # cannot overwrite another run's activity message.
            activity_id = f"activity-{self.run_id}-{step_id}"
            source = _text(meta.get("source"), 32)
            activity_kind = _text(meta.get("activity_kind"), 32)
            internal = source == "deepagents" and activity_kind in {
                "plan", "subagent",
            }
            # Canonical Deep Agents activity is structured runtime truth.
            # Even a malformed upstream description must not become raw
            # reasoning, tool arguments or provider-error text in the UI.
            description = (
                f"Deep Agents {activity_kind} {status}."
                if internal else content[:2000]
            )
            activity = {
                "type": "ACTIVITY_SNAPSHOT",
                "messageId": activity_id,
                "activityType": (
                    f"KAREN_DEEPAGENTS_{activity_kind.upper()}"
                    if internal else "KAREN_AGENT_STEP"
                ),
                "content": {
                    # This AG-UI run ID is transport correlation, not a
                    # verified durable runtime-ledger identifier.
                    "runId": self.run_id,
                    "stepId": step_id,
                    "agentId": agent_id,
                    "status": status,
                    "eventType": event_type,
                    "description": description,
                },
            }
            events = [activity, self._custom("karen.agent_step", {
                "step_id": step_id,
                "event_type": event_type,
                "status": status,
                "agent_id": agent_id,
                "description": description,
            })]
            # SUBAGENT events represent *observed* Deep Agents task-tool
            # invocations, not a guessed Medusa team or agent plan.
            if internal and activity_kind == "subagent":
                sub_run_id = _text(meta.get("subagent_run_id"), 128)
                if sub_run_id and event_type == f"deepagents_subagent_{status}":
                    if status == "running" and sub_run_id not in self._subagent_runs:
                        self._subagent_runs.add(sub_run_id)
                        events.append({
                            "type": "SUBAGENT_STARTED",
                            "subagentRunId": sub_run_id,
                            "name": "task",
                        })
                    elif sub_run_id in self._subagent_runs and status in {
                        "completed", "failed",
                    }:
                        self._subagent_runs.remove(sub_run_id)
                        if status == "completed":
                            events.append({
                                "type": "SUBAGENT_FINISHED",
                                "subagentRunId": sub_run_id,
                            })
                        else:
                            events.append({
                                "type": "SUBAGENT_ERROR",
                                "subagentRunId": sub_run_id,
                                "message": "Delegated task failed.",
                            })
            return events

        if kind == "tool":
            phase = _text(meta.get("phase") or meta.get("status"), 32).lower()
            # An agent step is not a tool-call identity. Never invent one.
            tool_id = _text(meta.get("tool_call_id"), 128)
            tool_name = _text(meta.get("tool_name"), 128)
            if not tool_id or not tool_name or phase not in {
                "started", "completed", "failed", "cancelled",
            }:
                return []
            events = [self._custom("karen.tool_activity", {
                "tool_call_id": tool_id,
                "name": tool_name,
                "phase": phase,
            })]
            if phase == "started" and tool_id not in self._tool_calls:
                self._tool_calls.add(tool_id)
                events.append({
                    "type": "TOOL_CALL_START",
                    "toolCallId": tool_id,
                    "toolCallName": tool_name,
                })
            elif tool_id in self._tool_calls and phase in {
                "completed", "failed", "cancelled",
            }:
                self._tool_calls.remove(tool_id)
                events.append({"type": "TOOL_CALL_END", "toolCallId": tool_id})
            # CUSTOM retains the observed failed/cancelled outcome; AG-UI
            # TOOL_CALL_END means only that the invocation is no longer active.
            return events

        if kind == "presentation":
            # Only explicitly runtime-origin, evidence-backed projections.
            if meta.get("presentation_verified") is not True:
                return []
            validated = _validated_presentation(meta.get("presentation"))
            if validated is None:
                return []
            return [self._custom("karen.presentation.v1", validated)]

        if kind == "citation":
            raw_citations = meta.get("citations")
            citations = []
            if isinstance(raw_citations, list):
                for value in raw_citations[:50]:
                    if not isinstance(value, Mapping):
                        continue
                    citations.append({
                        "id": _text(value.get("id"), 128),
                        "title": _text(value.get("title"), 300),
                        "url": _text(value.get("url"), 2000),
                        "snippet": _text(value.get("snippet"), 1000),
                    })
            return [self._custom("karen.citations", {"citations": citations})]

        if kind == "approval":
            return [self._custom("karen.approval_required", {
                "message": content[:2000],
                "approval_id": _text(meta.get("approval_id"), 128),
            })]

        if kind in {"status", "warning"}:
            if (
                kind == "status"
                and meta.get("source") == "deepagents"
                and meta.get("checkpoint_verified") is True
                and meta.get("resumable") is False
            ):
                step_id = _text(meta.get("step_id"), 128)
                if step_id:
                    # Read-back was verified upstream by Karen's saver.
                    # Never expose the checkpoint bytes or a fake resume
                    # button, and never infer resumability from persistence.
                    return [self._custom("karen.checkpoint", {
                        "step_id": step_id,
                        "checkpoint_verified": True,
                        "resumable": False,
                        "message": "Agent checkpoint persisted. Resume is not available.",
                    })]
            return [self._custom(f"karen.{kind}", {
                "message": content[:2000],
                "degraded_mode": meta.get("degraded_mode") is True,
            })]

        if kind == "complete":
            self._terminal = True
            return self._finish_message() + [{
                "type": "RUN_FINISHED",
                "threadId": self.thread_id,
                "runId": self.run_id,
            }]

        if kind == "error":
            self._terminal = True
            return self._finish_message() + [{
                "type": "RUN_ERROR",
                "message": content[:2000] or "Chat execution failed.",
                "code": _text(meta.get("error_code"), 128) or "CHAT_RUNTIME_ERROR",
            }]

        return []

    def fail_incomplete(self) -> list[dict[str, Any]]:
        """Fail closed when runtime ends without canonical completion."""
        if not self._started or self._terminal:
            return []
        self._terminal = True
        return self._finish_message() + [{
            "type": "RUN_ERROR",
            "message": "The chat stream ended before runtime completion.",
            "code": "CHAT_SSE_MISSING_TERMINAL",
        }]
