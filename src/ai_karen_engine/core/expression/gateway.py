from __future__ import annotations
import logging
from .contracts import ExpressionResult, ExpressionTask
from .circuit_breakers import ExpressionCircuitBreakers
from .observability import emit_expression_event
from .registry import get_engine
from ai_karen_engine.core.expression.settings import get_expression_settings, EngineConfig
from ..response.response_validator import validate_response_text
from ..model_runtime.provider_policy import evaluate_provider_policy
from ai_karen_engine.core.logging.events import RoutingEvents, ProviderEvents

logger = logging.getLogger(__name__)


def _emit_routing_event(event_name: str, **kwargs):
    """Emit a routing observability event using structured logging."""
    logger.info("%s %s", event_name, kwargs)

class ExpressionGateway:
    def __init__(self, settings: Any | None = None):
        self.settings = settings or get_expression_settings()
        self.circuits = ExpressionCircuitBreakers()

    def _event_payload(self, task: ExpressionTask, **extra):
        return {
            "correlation_id": task.correlation_id,
            "request_id": task.request_id,
            "response_mode": task.response_mode,
            "capabilities": task.required_capabilities,
            **extra,
        }

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        emit_expression_event("expression.task.started", self._event_payload(task, engine_id=self.settings.active_engine))

        # Emit routing.requested event
        _emit_routing_event(
            RoutingEvents.REQUESTED,
            correlation_id=task.correlation_id,
            request_id=task.request_id,
            preferred_provider=task.preferred_provider,
            preferred_model=task.preferred_model,
            response_mode=task.response_mode
        )

        # Build the actual execution sequence (max 5 steps)
        # 0. Start with user's preferred provider if explicitly requested and different from active engine
        # 1. Then add the configured active engine
        # 2. Then follows the fallback order.
        # Fixed 5th step is always 'disabled' (Emergency Static).
        fallback_order = self.settings.engine_fallback_order
        sequence = []

        pref_id = str(task.preferred_provider or "").strip().lower()
        if pref_id and pref_id != "auto":
             # Use policy to map provider to engine category
             decision = evaluate_provider_policy(
                 pref_id,
                 local_enabled=True,
                 external_enabled=self.settings.policies.allow_external_engines
             )
             target_engine = None
             if decision.classification == "builtin_engine":
                  target_engine = decision.provider
             elif decision.classification == "local_openai_endpoint":
                  target_engine = "local"
             elif decision.classification == "cloud_provider":
                  target_engine = "cloud"

             if target_engine:
                  if target_engine not in sequence:
                       sequence.insert(0, target_engine)
                  else:
                       # Move to front if already present
                       sequence.remove(target_engine)
                       sequence.insert(0, target_engine)

        # Then add the configured active engine
        if self.settings.active_engine not in sequence:
             sequence.append(self.settings.active_engine)

        for engine_id in fallback_order:
            if engine_id not in sequence and len(sequence) < 5:
                sequence.append(engine_id)

        # Step 5: Always Emergency Static
        if "disabled" not in sequence:
            sequence.append("disabled")

        # Limit to 6 steps total to ensure 'disabled' is always included
        sequence = sequence[:6]

        # Emit routing.evaluated event with the full sequence
        _emit_routing_event(
            RoutingEvents.EVALUATED,
            correlation_id=task.correlation_id,
            request_id=task.request_id,
            sequence=sequence,
            active_engine=self.settings.active_engine,
            preferred_provider=task.preferred_provider
        )

        logger.info(f"Expression gateway sequence: {sequence} (preferred: {task.preferred_provider})")

        last_error = None
        skipped_engines = []

        for level, engine_id in enumerate(sequence):
            # Resolve config
            cfg = self.settings.engines.get(engine_id)
            logger.debug("Gateway trying %s, cfg: %s", engine_id, cfg)

            if engine_id == "disabled":
                # Emergency static is always enabled and fallback-eligible
                cfg = EngineConfig(enabled=True, type="disabled_engine", fallback_eligible=True)

            if not cfg or not cfg.enabled:
                skipped_engines.append({"engine_id": engine_id, "reason": "disabled"})
                _emit_routing_event(
                    RoutingEvents.REJECTED,
                    correlation_id=task.correlation_id,
                    request_id=task.request_id,
                    engine_id=engine_id,
                    reason="disabled"
                )
                continue

            if engine_id != "disabled" and self.circuits.is_open(f"expression.engine.{engine_id}"):
                skipped_engines.append({"engine_id": engine_id, "reason": "circuit_open"})
                _emit_routing_event(
                    RoutingEvents.REJECTED,
                    correlation_id=task.correlation_id,
                    request_id=task.request_id,
                    engine_id=engine_id,
                    reason="circuit_open"
                )
                continue

            # Emit routing.selected event
            _emit_routing_event(
                RoutingEvents.SELECTED,
                correlation_id=task.correlation_id,
                request_id=task.request_id,
                engine_id=engine_id,
                engine_type=cfg.type,
                fallback_level=level
            )

            emit_expression_event("expression.engine.selected", self._event_payload(task, engine_id=engine_id, engine_type=cfg.type, fallback_level=level))
            engine = get_engine(engine_id, cfg.type)
            
            # If engine_id is a specific provider, override preference for this attempt
            original_provider = task.preferred_provider
            original_model = task.preferred_model
            
            # Only override if engine_id is a recognized provider, but NOT 'local' or 'cloud'
            if engine_id not in {"local", "cloud", "builtin"}:
                decision = evaluate_provider_policy(engine_id)
                if decision.classification != "unknown" and decision.classification != "removed_internal_provider":
                     task.preferred_provider = engine_id
            
            # Inject engine-specific overrides from config metadata
            if cfg and cfg.metadata:
                 if "preferred_provider" in cfg.metadata:
                      task.preferred_provider = cfg.metadata["preferred_provider"]
                 if "preferred_model" in cfg.metadata:
                      task.preferred_model = cfg.metadata["preferred_model"]

            emit_expression_event("expression.engine.request.started", self._event_payload(task, engine_id=engine_id, engine_type=cfg.type, provider=task.preferred_provider, model=task.preferred_model))
            
            try:
                result = await engine.generate(task)
                logger.debug("Engine %s returned text: '%s'", engine_id, result.text)
                
                # Validate the generated output
                has_text = bool(result.text and result.text.strip())
                is_valid = validate_response_text(result.text) if has_text else False
                
                if has_text and is_valid:
                    if engine_id != "disabled":
                        self.circuits.mark_success(f"expression.engine.{engine_id}")
                    
                    # Update metadata with execution details
                    if level > 0:
                        result.metadata = {**(result.metadata or {}), "fallback_level": level, "skipped_engines": skipped_engines}
                    
                    emit_expression_event("expression.engine.request.completed", self._event_payload(task, engine_id=result.engine_id, engine_type=cfg.type, provider=result.provider, model=result.model, latency_ms=result.latency_ms, degraded=result.degraded, fallback_level=level))
                    return result
                else:
                    # Determine reason for failure
                    if not has_text:
                        reason = result.degradation_reason or "empty_output"
                    else:
                        reason = "invalid_output"
                        
                    emit_expression_event("expression.output.invalid", self._event_payload(task, engine_id=result.engine_id, provider=result.provider, model=result.model, degraded=True, degradation_reason=reason))
                    if engine_id != "disabled":
                        self.circuits.mark_failure(f"validation.{result.model or 'unknown'}")
                    skipped_engines.append({"engine_id": engine_id, "reason": reason})

            except Exception as exc:
                if engine_id != "disabled":
                    self.circuits.mark_failure(f"expression.engine.{engine_id}")
                last_error = str(exc)
                emit_expression_event("expression.engine.request.failed", self._event_payload(task, engine_id=engine_id, engine_type=cfg.type, degraded=True, degradation_reason=last_error))
                skipped_engines.append({"engine_id": engine_id, "reason": "exception", "error": last_error})
            finally:
                # Restore original preference
                task.preferred_provider = original_provider
                task.preferred_model = original_model
                
            if engine_id != "disabled" and not cfg.fallback_eligible and level == 0:
                # If active engine is not fallback eligible and it was the first attempt, we stop early
                # unless it's the fixed emergency step.
                break

        # If we reached here, even Emergency Static failed (extremely unlikely)
        return ExpressionResult(
            task_id=task.task_id,
            text="System is operating in restricted mode. Expression engine unavailable.",
            provider="system",
            model="static",
            engine_id="disabled",
            engine_mode="emergency",
            runtime_engine=None,
            response_source="system_failure",
            latency_ms=0,
            degraded=True,
            degradation_reason="all_engines_failed"
        )
