from __future__ import annotations

import logging
import math
import time
from typing import Any

from .circuit_breakers import ExpressionCircuitBreakers
from .contracts import ExpressionResult, ExpressionTask
from .errors import EngineUnavailableError
from .observability import emit_expression_event
from .registry import get_engine
from ai_karen_engine.core.errors.response_validation import validate_response_text
from ai_karen_engine.core.expression.settings import get_expression_settings
from ai_karen_engine.core.logging.events import RoutingEvents
from ..model_runtime.provider_policy import evaluate_provider_policy

logger = logging.getLogger(__name__)


def _emit_routing_event(event_name: str, **kwargs: Any) -> None:
    """Emit a routing observability event using structured logging."""
    logger.info("%s %s", event_name, kwargs)


class ExpressionGateway:
    """Route expression tasks to configured model engines.

    Conversational generation is provider-agnostic. The gateway selects the
    local or cloud OpenAI-compatible execution surface, while the provider
    registry owns concrete endpoint selection. It never manufactures an
    assistant answer. If every eligible model engine is exhausted, the runtime
    receives ``EngineUnavailableError`` and owns degraded/error handling.
    """

    def __init__(self, settings: Any | None = None):
        self.settings = settings or get_expression_settings()
        self.circuits = ExpressionCircuitBreakers()

    def availability(self) -> tuple[bool, str | None]:
        """Return operational gateway availability without generating model text.

        Availability here means at least one configured expression engine is
        enabled and not blocked by its circuit breaker. Concrete provider
        registration/credentials remain the provider registry probe's concern.
        """
        engine_ids: list[str] = []
        active_engine = (
            "local"
            if self.settings.active_engine == "builtin"
            else self.settings.active_engine
        )
        if active_engine != "disabled":
            engine_ids.append(active_engine)

        for configured_engine_id in self.settings.engine_fallback_order:
            if configured_engine_id == "disabled":
                continue
            engine_id = (
                "local" if configured_engine_id == "builtin" else configured_engine_id
            )
            if engine_id not in engine_ids:
                engine_ids.append(engine_id)

        if not engine_ids:
            return False, "No expression engines configured"

        blocked: list[str] = []
        for engine_id in engine_ids[:5]:
            cfg = self.settings.engines.get(engine_id)
            if not cfg or not cfg.enabled:
                blocked.append(f"{engine_id}:disabled")
                continue
            if self.circuits.is_open(f"expression.engine.{engine_id}"):
                blocked.append(f"{engine_id}:circuit_open")
                continue
            return True, None

        reason = ", ".join(blocked) if blocked else "No enabled expression engines"
        return False, reason

    def _event_payload(self, task: ExpressionTask, **extra: Any) -> dict[str, Any]:
        return {
            "correlation_id": task.correlation_id,
            "request_id": task.request_id,
            "response_mode": task.response_mode,
            "capabilities": task.required_capabilities,
            **extra,
        }

    @staticmethod
    def _observe_verified_model_success(result: ExpressionResult) -> None:
        """Report an actual executor's verified model result to the health owner.

        The result is already validated for usable, model-sourced text by the
        gateway. A configured preference, disabled engine, static fallback or
        empty model identity is not execution evidence. Health observability
        must never turn a successful model answer into an HTTP failure.
        """
        provider = result.provider
        model = result.model
        if (
            not isinstance(provider, str)
            or not provider.strip()
            or not isinstance(model, str)
            or not model.strip()
            or result.response_source in {
                "model_unavailable",
                "emergency_static",
                "deterministic_fallback",
                "persisted_history",
            }
        ):
            return

        try:
            from ai_karen_engine.core.model_runtime.provider_health_monitor import (
                record_provider_success,
            )

            seconds = float(result.latency_ms) / 1000.0
            latency_seconds = seconds if math.isfinite(seconds) and seconds >= 0 else None
            record_provider_success(provider.strip(), response_time=latency_seconds)
        except Exception as exc:
            # Health reporting is observability, not an inference dependency.
            # Never turn a verified completed answer into a transport error.
            logger.warning(
                "expression.provider_health_observation_unavailable",
                extra={
                    "provider": provider,
                    "error_type": type(exc).__name__,
                },
            )

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        active_engine = (
            "local" if self.settings.active_engine == "builtin" else self.settings.active_engine
        )
        emit_expression_event(
            "expression.task.started",
            self._event_payload(task, engine_id=active_engine),
        )

        _emit_routing_event(
            RoutingEvents.REQUESTED,
            correlation_id=task.correlation_id,
            request_id=task.request_id,
            preferred_provider=task.preferred_provider,
            preferred_model=task.preferred_model,
            response_mode=task.response_mode,
        )

        sequence: list[str] = []
        preferred_id = str(task.preferred_provider or "").strip().lower()
        if preferred_id and preferred_id != "auto":
            decision = evaluate_provider_policy(
                preferred_id,
                local_enabled=True,
                external_enabled=self.settings.policies.allow_external_engines,
            )
            target_engine: str | None = None
            if decision.classification == "local_openai_endpoint":
                target_engine = "local"
            elif decision.classification == "cloud_provider":
                target_engine = "cloud"
            elif decision.classification == "deprecated_provider_alias" and decision.replacement:
                replacement = evaluate_provider_policy(
                    decision.replacement,
                    local_enabled=True,
                    external_enabled=self.settings.policies.allow_external_engines,
                )
                if decision.replacement == "local" or replacement.classification == "local_openai_endpoint":
                    target_engine = "local"
                elif replacement.classification == "cloud_provider":
                    target_engine = "cloud"

            if target_engine:
                sequence.append(target_engine)

        if active_engine not in sequence:
            sequence.append(active_engine)

        for configured_engine_id in self.settings.engine_fallback_order:
            if configured_engine_id == "disabled":
                continue
            engine_id = "local" if configured_engine_id == "builtin" else configured_engine_id
            if engine_id not in sequence and len(sequence) < 5:
                sequence.append(engine_id)

        sequence = sequence[:5]

        _emit_routing_event(
            RoutingEvents.EVALUATED,
            correlation_id=task.correlation_id,
            request_id=task.request_id,
            sequence=sequence,
            active_engine=active_engine,
            preferred_provider=task.preferred_provider,
        )
        logger.info(
            "Expression gateway sequence: %s (preferred: %s)",
            sequence,
            task.preferred_provider,
        )

        last_error: str | None = None
        skipped_engines: list[dict[str, Any]] = []
        # Monotonic measurements of actual selected engine calls only. This is
        # not provider cold-start time: engines may initialize internally.
        attempt_timings: list[dict[str, Any]] = []
        # A provider may fail and allow another eligible engine only until
        # the first delta has reached the consumer. After that, the response
        # belongs to one model and must end as an explicit incomplete stream.
        task.stream_started = False

        for level, engine_id in enumerate(sequence):
            cfg = self.settings.engines.get(engine_id)
            logger.debug("Gateway evaluating configured engine %s", engine_id)

            if not cfg or not cfg.enabled:
                skipped_engines.append(
                    {"engine_id": engine_id, "reason": "disabled"}
                )
                _emit_routing_event(
                    RoutingEvents.REJECTED,
                    correlation_id=task.correlation_id,
                    request_id=task.request_id,
                    engine_id=engine_id,
                    reason="disabled",
                )
                continue

            if self.circuits.is_open(f"expression.engine.{engine_id}"):
                skipped_engines.append(
                    {"engine_id": engine_id, "reason": "circuit_open"}
                )
                _emit_routing_event(
                    RoutingEvents.REJECTED,
                    correlation_id=task.correlation_id,
                    request_id=task.request_id,
                    engine_id=engine_id,
                    reason="circuit_open",
                )
                continue

            _emit_routing_event(
                RoutingEvents.SELECTED,
                correlation_id=task.correlation_id,
                request_id=task.request_id,
                engine_id=engine_id,
                engine_type=cfg.type,
                fallback_level=level,
            )
            emit_expression_event(
                "expression.engine.selected",
                self._event_payload(
                    task,
                    engine_id=engine_id,
                    engine_type=cfg.type,
                    fallback_level=level,
                ),
            )

            engine = get_engine(engine_id, cfg.type)
            original_provider = task.preferred_provider
            original_model = task.preferred_model

            if engine_id not in {"local", "cloud"}:
                decision = evaluate_provider_policy(engine_id)
                if decision.classification not in {
                    "unknown",
                    "removed_internal_provider",
                    "deprecated_provider_alias",
                }:
                    task.preferred_provider = engine_id

            # Configured engine defaults must not silently replace an explicit
            # user-selected provider/model on the primary attempt. A later
            # fallback engine may apply its own configured target.
            if cfg.metadata:
                if (level > 0 or not original_provider) and cfg.metadata.get("preferred_provider"):
                    task.preferred_provider = cfg.metadata["preferred_provider"]
                if (level > 0 or not original_model) and cfg.metadata.get("preferred_model"):
                    task.preferred_model = cfg.metadata["preferred_model"]

            emit_expression_event(
                "expression.engine.request.started",
                self._event_payload(
                    task,
                    engine_id=engine_id,
                    engine_type=cfg.type,
                    provider=task.preferred_provider,
                    model=task.preferred_model,
                ),
            )

            attempt_started = time.perf_counter()
            attempt_recorded = False
            attempt_outcome = "exception"
            try:
                result = await engine.generate(task)
                # Generated text can contain private user facts or tool evidence.
                # Keep payloads out of runtime logs, even at DEBUG level.

                has_text = bool(result.text and result.text.strip())
                is_valid = validate_response_text(result.text) if has_text else False
                has_model_source = (
                    bool(result.provider)
                    and result.response_source != "model_unavailable"
                )

                if has_text and is_valid and has_model_source:
                    # A token-limited answer is usable partial output, not a
                    # normally completed model response or a fallback trigger.
                    if (result.metadata or {}).get("output_truncated") is True:
                        result.degraded = True
                        result.degradation_reason = "output_token_limit"
                    self.circuits.mark_success(f"expression.engine.{engine_id}")
                    # Only observed, validated model execution may advance the
                    # canonical health catalog. Do not mark the selected alias
                    # healthy merely because an engine was configured.
                    self._observe_verified_model_success(result)
                    observed_attempt_ms = (time.perf_counter() - attempt_started) * 1000.0
                    attempt_timings.append({
                        "engine_id": engine_id,
                        "fallback_level": level,
                        "duration_ms": observed_attempt_ms,
                        "outcome": "verified_model",
                    })
                    attempt_recorded = True
                    result.metadata = {
                        **(result.metadata or {}),
                        "fallback_level": level,
                        "skipped_engines": skipped_engines,
                        "engine_attempt_timings": list(attempt_timings),
                    }
                    emit_expression_event(
                        "expression.engine.request.completed",
                        self._event_payload(
                            task,
                            engine_id=result.engine_id,
                            engine_type=cfg.type,
                            provider=result.provider,
                            model=result.model,
                            latency_ms=result.latency_ms,
                            gateway_attempt_ms=observed_attempt_ms,
                            degraded=result.degraded,
                            fallback_level=level,
                        ),
                    )
                    return result

                if task.stream_started:
                    raise EngineUnavailableError("partial_provider_stream_unverified")

                if not has_text:
                    reason = result.degradation_reason or "empty_output"
                elif not has_model_source:
                    reason = result.degradation_reason or "non_model_output_rejected"
                else:
                    reason = "invalid_output"

                emit_expression_event(
                    "expression.output.invalid",
                    self._event_payload(
                        task,
                        engine_id=result.engine_id,
                        provider=result.provider,
                        model=result.model,
                        degraded=True,
                        degradation_reason=reason,
                    ),
                )
                self.circuits.mark_failure(
                    f"validation.{result.model or engine_id or 'unknown'}"
                )
                skipped_engines.append(
                    {"engine_id": engine_id, "reason": reason}
                )
                attempt_outcome = "invalid_output"
                last_error = reason
            except Exception as exc:
                self.circuits.mark_failure(f"expression.engine.{engine_id}")
                if task.stream_started:
                    # Never append a second model's output after visible text.
                    # This is an unrecoverable turn failure, not a fallback
                    # opportunity or a completed model execution receipt.
                    emit_expression_event(
                        "expression.stream.incomplete",
                        self._event_payload(
                            task, engine_id=engine_id, degraded=True,
                            degradation_reason="partial_provider_stream_unverified",
                        ),
                    )
                    raise EngineUnavailableError(
                        "partial_provider_stream_unverified"
                    ) from exc
                # Log/emit bounded codes, never upstream HTTP exception text
                # that might embed private URLs, headers, or provider content.
                last_error = (
                    str(exc)
                    if isinstance(exc, EngineUnavailableError)
                    and str(exc).isascii()
                    and len(str(exc)) <= 100
                    and all(c.isalnum() or c in "._:-" for c in str(exc))
                    else type(exc).__name__
                )
                emit_expression_event(
                    "expression.engine.request.failed",
                    self._event_payload(
                        task,
                        engine_id=engine_id,
                        engine_type=cfg.type,
                        degraded=True,
                        degradation_reason=last_error,
                    ),
                )
                skipped_engines.append(
                    {
                        "engine_id": engine_id,
                        "reason": "exception",
                        "error": last_error,
                    }
                )
            finally:
                if not attempt_recorded:
                    observed_attempt_ms = (time.perf_counter() - attempt_started) * 1000.0
                    attempt_timings.append({
                        "engine_id": engine_id,
                        "fallback_level": level,
                        "duration_ms": observed_attempt_ms,
                        "outcome": attempt_outcome,
                    })
                    emit_expression_event(
                        "expression.engine.attempt.observed",
                        self._event_payload(
                            task,
                            engine_id=engine_id,
                            fallback_level=level,
                            gateway_attempt_ms=observed_attempt_ms,
                            outcome=attempt_outcome,
                        ),
                    )
                task.preferred_provider = original_provider
                task.preferred_model = original_model

            if not cfg.fallback_eligible and level == 0:
                break

        emit_expression_event(
            "expression.engines.exhausted",
            self._event_payload(
                task,
                skipped_engines=skipped_engines,
                degradation_reason=last_error or "all_model_engines_failed",
            ),
        )
        raise EngineUnavailableError(
            "No model engine produced a valid response: "
            f"{last_error or 'all_model_engines_failed'}"
        )
