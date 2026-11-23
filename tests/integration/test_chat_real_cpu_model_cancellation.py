"""KCHAT-SEC-03: actual CPU Transformer worker termination over canonical chat provider SSE.

This acceptance runs randomly initialized local test-only PyTorch Transformer
forward passes in real OS child processes. It does not download pretrained
weights, claim semantic model quality, use real PostgreSQL or a production model
host, or replace Karen's provider selection/authorization/runtime authorities.
KCHAT-SEC-02 separately certifies authenticated ChatRuntime SSE + PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import socket
import time
from dataclasses import replace
from typing import Any
from uuid import uuid4

import psutil
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.expression.gateway import ExpressionGateway
from ai_karen_engine.core.expression.settings import ExpressionSettings
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_registry_service import (
    ProviderRegistryService,
)
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatStreamEventType,
    PersonaExecutionSnapshot,
)
from ai_karen_engine.core.runtime.composition import get_runtime_composition
from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)

MODEL_ID = "kchat-locally-initialized-torch-transformer"
PROVIDER_ID = "kchat-ci-local-inference"
WORDS = (
    "amber", "cedar", "river", "cloud", "stone", "orchid",
    "silver", "dawn", "willow", "field", "copper", "saffron",
    "forest", "harbor", "meadow", "night",
)


def _cpu_transformer_forward_worker(pipe: Any, token_count: int) -> None:
    """Execute actual PyTorch attention forward passes, never static token playback."""
    try:
        import torch

        torch.set_num_threads(1)
        torch.manual_seed(1903)
        embedding = torch.nn.Embedding(len(WORDS), 16)
        attention = torch.nn.TransformerEncoderLayer(
            d_model=16, nhead=2, dim_feedforward=32,
            dropout=0.0, batch_first=True,
        )
        output = torch.nn.Linear(16, len(WORDS))
        attention.eval()
        embedding.eval()
        output.eval()
        context_ids = [1, 3, 5]
        with torch.inference_mode():
            for step in range(token_count):
                indices = torch.tensor([context_ids[-12:]], dtype=torch.long)
                activations = attention(embedding(indices))
                prediction = int(output(activations[:, -1, :]).argmax().item())
                context_ids.append(prediction)
                pipe.send(("token", WORDS[prediction] + " ", step + 1))
                # Make ongoing CPU work observable after the first token.
                # These are actual model-forward steps, not invented output.
                time.sleep(0.02)
        pipe.send(("done", "", token_count))
    except BaseException as error:
        # Only a fixed error class is returned; never raw model/prompt contents.
        try:
            pipe.send(("error", type(error).__name__, 0))
        except (OSError, EOFError, BrokenPipeError):
            pass
    finally:
        pipe.close()


@pytest.mark.asyncio
@pytest.mark.timeout(110)
async def test_real_cpu_transformer_worker_stops_on_chat_runtime_stream_close_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    torch = pytest.importorskip("torch")
    assert torch.__version__

    # Isolate locally constructed test weights to a subprocess per request.
    # Neither production inference nor tenant data is routed through this app.
    ctx = multiprocessing.get_context("spawn")
    app = FastAPI()
    started: list[dict[str, Any]] = []
    stopped: list[dict[str, Any]] = []
    stop_observed = asyncio.Event()
    inference_requests: list[str] = []

    @app.post("/v1/chat/completions")
    async def local_inference(request: Request):
        body = await request.json()
        assert body["stream"] is True
        assert body["model"] == MODEL_ID
        assert isinstance(body["max_tokens"], int)
        assert 1 <= body["max_tokens"] <= 128
        assert isinstance(body["messages"], list)
        user_messages = [
            str(msg.get("content") or "")
            for msg in body["messages"]
            if msg.get("role") == "user"
        ]
        assert user_messages
        user_text = user_messages[-1]
        inference_requests.append(user_text)
        token_count = min(4, body["max_tokens"]) if "retry" in user_text else body["max_tokens"]
        receiver, sender = ctx.Pipe(duplex=False)
        worker = ctx.Process(
            target=_cpu_transformer_forward_worker,
            args=(sender, token_count),
            daemon=True,
        )
        worker.start()
        sender.close()
        record = {
            "pid": worker.pid,
            "requested_tokens": token_count,
            "observed_forward_passes": 0,
            "exit_code": None,
            "aborted": None,
            "release_ms": None,
        }
        started.append(record)

        async def events():
            complete = False
            try:
                while True:
                    if receiver.poll():
                        try:
                            kind, value, forward_count = receiver.recv()
                        except EOFError:
                            raise RuntimeError("cpu_inference_worker_exited_without_receipt")
                        if kind == "error":
                            raise RuntimeError("cpu_inference_worker_failed")
                        if kind == "token":
                            assert forward_count > record["observed_forward_passes"]
                            record["observed_forward_passes"] = forward_count
                            frame = {
                                "model": MODEL_ID,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": value},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(frame)}\n\n"
                        elif kind == "done":
                            assert forward_count == record["observed_forward_passes"]
                            complete = True
                            frame = {
                                "model": MODEL_ID,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {},
                                        "finish_reason": "stop",
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(frame)}\n\n"
                            yield "data: [DONE]\n\n"
                            return
                    elif not worker.is_alive():
                        raise RuntimeError("cpu_inference_worker_died_without_terminal")
                    await asyncio.sleep(0.005)
            finally:
                cleanup_started = time.perf_counter()
                if worker.is_alive():
                    worker.terminate()
                worker.join(timeout=3.0)
                if worker.is_alive():
                    worker.kill()
                    worker.join(timeout=3.0)
                record["exit_code"] = worker.exitcode
                record["aborted"] = not complete
                record["release_ms"] = round(
                    (time.perf_counter() - cleanup_started) * 1000.0, 3,
                )
                receiver.close()
                stopped.append(record)
                stop_observed.set()

        return StreamingResponse(events(), media_type="text/event-stream")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    listener.setblocking(False)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", lifespan="off", access_log=False),
    )
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(250):
            if server.started:
                break
            if server_task.done():
                await server_task
                raise AssertionError("Local inference server did not start")
            await asyncio.sleep(0.02)
        assert server.started

        endpoint = ProviderEndpoint(
            provider_id=PROVIDER_ID,
            display_name="CI locally initialized model worker",
            endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
            base_url=f"http://127.0.0.1:{listener.getsockname()[1]}/v1",
            timeout_seconds=45,
            supports_streaming=True,
            capabilities=("chat_completion", "text_generation", "streaming"),
            default_model=MODEL_ID,
        )
        registry = ProviderRegistryService()
        registry.register_provider_endpoint(endpoint)
        assert registry.get_provider_endpoint(PROVIDER_ID) == endpoint
        assert registry.get_provider_status(PROVIDER_ID).is_available
        monkeypatch.setattr(
            "ai_karen_engine.core.model_runtime.provider_registry_service."
            "get_provider_registry_service",
            lambda: registry,
        )

        settings = ExpressionSettings(
            active_engine="local", engine_fallback_order=["local"],
        )
        settings.engines["cloud"].enabled = False
        expression_gateway = ExpressionGateway(settings)
        composition = replace(
            get_runtime_composition(), expression_gateway=expression_gateway,
        )
        runtime = ChatRuntime(composition=composition)
        policy = RuntimePolicyEnforcer()

        async def authorized_stream(prompt: str, max_tokens: int):
            tenant_id = str(uuid4())
            user_id = str(uuid4())
            session_id = "kchat-real-worker-ci"
            ctx_request = ChatExecutionContext(
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                conversation_id=str(uuid4()),
                request_id=str(uuid4()),
                correlation_id=str(uuid4()),
                authenticated_user=UserData(
                    user_id=user_id, tenant_id=tenant_id,
                ),
            )
            issued = await policy.evaluate(PolicyEvaluationRequest(
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                correlation_id=ctx_request.correlation_id,
                action="general_assist",
                max_model_calls=1,
            ))
            assert issued.allowed is True
            policy.bind_chat_model_policy(context=ctx_request, decision=issued)
            request = ChatExecutionRequest(
                messages=[{"role": "user", "content": prompt}],
                context=ctx_request,
                preferred_provider=PROVIDER_ID,
                preferred_model=MODEL_ID,
                max_tokens=max_tokens,
                stream=True,
            )
            request.persona_snapshot = PersonaExecutionSnapshot(
                user_id=user_id, tenant_id=tenant_id, status="none",
            )
            decision = ExecutionDecision(
                intent="general_assist",
                policy_decision_id=issued.decision_id,
                policy_version=issued.policy_version,
                max_model_calls=1,
                time_budget_ms=45000,
                memory_recall_required=False,
                memory_write_allowed=False,
            )
            plan = runtime._build_authorized_plan(request, decision)
            meter = ExecutionBudgetMeter(plan.budget)
            request.context.bind_runtime_model_authority(plan, meter)
            meter.start()
            return runtime._run_simple_stream(
                request, decision, plan, meter, _meta={},
            )

        interrupted_stream = await authorized_stream("cancel ongoing generation", 128)
        first_token = await asyncio.wait_for(anext(interrupted_stream), timeout=40)
        assert first_token.type == ChatStreamEventType.CONTENT
        assert first_token.content.strip() in WORDS
        assert len(started) == 1
        assert started[0]["observed_forward_passes"] >= 1
        assert started[0]["requested_tokens"] == 128

        cancelled_at = time.perf_counter()
        await asyncio.wait_for(interrupted_stream.aclose(), timeout=10)
        await asyncio.wait_for(stop_observed.wait(), timeout=10)
        wire_to_release_ms = round((time.perf_counter() - cancelled_at) * 1000.0, 3)
        assert stopped[0]["aborted"] is True
        assert stopped[0]["exit_code"] is not None
        assert stopped[0]["exit_code"] != 0
        assert stopped[0]["release_ms"] >= 0
        assert not psutil.pid_exists(stopped[0]["pid"])

        stop_observed.clear()
        recovered_stream = await authorized_stream("retry complete generation", 16)
        recovered = [
            chunk async for chunk in recovered_stream
        ]
        await asyncio.wait_for(stop_observed.wait(), timeout=10)
        assert len(started) == len(stopped) == 2
        assert started[1]["pid"] != started[0]["pid"]
        assert stopped[1]["aborted"] is False
        assert stopped[1]["exit_code"] == 0
        assert stopped[1]["observed_forward_passes"] == 4
        assert not psutil.pid_exists(stopped[1]["pid"])
        assert all(chunk.type == ChatStreamEventType.CONTENT for chunk in recovered)
        assert len(recovered) == 4
        assert all(chunk.content.strip() in WORDS for chunk in recovered)
        assert inference_requests == [
            "cancel ongoing generation", "retry complete generation",
        ]

        evidence = {
            "schema_version": 1,
            "worker": "real_torch_transformer_cpu_forward_process",
            "weights": "locally_initialized_untrained_test_weights",
            "remote_model_execution": False,
            "chat_runtime_provider_path": "ChatRuntime._run_simple_stream_to_ExpressionGateway",
            "provider_transport": "canonical_openai_compatible_http_sse",
            "policy": "real_runtime_policy_issued_and_bound",
            "aborted_worker_exit_code": stopped[0]["exit_code"],
            "aborted_model_forward_passes": stopped[0]["observed_forward_passes"],
            "cancel_to_process_release_ms": wire_to_release_ms,
            "cleanup_release_ms": stopped[0]["release_ms"],
            "retry_model_forward_passes": stopped[1]["observed_forward_passes"],
            "retry_exit_code": stopped[1]["exit_code"],
            "orphan_worker_pids": [],
            "limits": [
                "Direct canonical runtime provider path, not HTTP chat ingress",
                "No production-installed or trained model asserted",
                "No browser, reverse proxy, persistent transcript, or remote worker",
                "Cancellation observation is not a production-latency SLO",
            ],
        }
        path = os.environ.get("KAREN_CHAT_REAL_WORKER_REPORT")
        if path:
            from pathlib import Path

            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(evidence, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=10)
        finally:
            listener.close()
        assert all(not psutil.pid_exists(row["pid"]) for row in stopped)
        assert all(not row.get("pid") or not psutil.pid_exists(row["pid"])
                   for row in started)
