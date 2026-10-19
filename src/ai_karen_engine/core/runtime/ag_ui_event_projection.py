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
            activity = {
                "type": "ACTIVITY_SNAPSHOT",
                "messageId": activity_id,
                "activityType": "KAREN_AGENT_STEP",
                "content": {
                    "stepId": step_id,
                    "agentId": agent_id,
                    "status": status,
                    "eventType": event_type,
                    "description": content[:2000],
                },
            }
            return [activity, self._custom("karen.agent_step", {
                "step_id": step_id,
                "event_type": event_type,
                "status": status,
                "agent_id": agent_id,
                "description": content[:2000],
            })]

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
