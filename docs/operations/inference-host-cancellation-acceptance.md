# KCHAT-HOST-01 | Inference-host cancellation acceptance

**Default status: HOLD until independently observed on the actual target host.**

## Source of truth and scope

The canonical ChatRuntime, RuntimePolicy, ExpressionGateway, provider registry and Core SSE transport remain authoritative. The host probe is an acceptance consumer of that transport, not a second model executor, chat route, scheduler, fallback or persistence layer.

Previous verified evidence is limited in scope:

- KCHAT-SEC-02: authenticated HTTP/SSE and PostgreSQL transcript tests.
- KCHAT-SEC-03: real but locally initialized CPU Transformer subprocess cancellation.
- KCHAT-SEC-04: installed Ollama model on a **temporary CI runner**, stream closure, a surviving independent request, and an **explicit** native model unload and reload.

Those do not prove model-host scheduler cancellation on Karen's deployment host. This slice targets a direct, locally accessible **vLLM** server because it exposes model-labeled running/waiting gauges, generation counters, and potentially abort-reason counters. Socket closure alone is insufficient.

## Operator and security prerequisites

Before running the probe, the operator must verify:

1. The actual inference host is registered as a self-hosted Linux GitHub Actions runner labeled **karen-inference-host**. The runner must access vLLM through loopback in its own network namespace.
2. The repository environment **inference-host-certification** has real required-reviewer protection, restricted main-branch access, and authorized operators. Naming an environment in workflow YAML **does not automatically enable approvals**.
3. The vLLM server exposes exactly one selected installed model through /v1/models and native, exact-model labeled /metrics series.
4. vLLM exposes running, waiting, generated-token and KV-cache metrics. The host must record an **incremented abort-reason counter** after client cancellation. Versions that do not expose this metric remain HOLD, even if the transport closes correctly.
5. The host is exclusive to this acceptance during a maintenance window. Stop other model consumers, warm-up jobs, deployments and benchmarks. The probe also requires a zero-running and zero-waiting native preflight.
6. The checkout's HEAD is the exact requested mainline SHA and its tracked files are unmodified. The operator supplies the actual observed hostname and model ID.
7. The inference runner can create a temporary Python virtual environment. If a local API key is necessary, provide it via the protected KAREN_VLLM_HOST_PROOF_API_KEY secret, never in the workflow parameters or logs.

The acceptance workflow, at .github/workflows/kchat-host-vllm-cancellation-acceptance.yml, has **workflow_dispatch only**. There is no push/PR trigger. Select live main, supply the observed local URL, hostname, model and acceptance budgets, then explicitly approve maintenance_ack. The job uses the protected environment and will run only on the labeled self-hosted runner.

## Execution

The existing Core provider SSE transport performs every inference call:

1. Confirm local /v1 URL, machine and source identity, exact model inventory and idle native gauges.
2. Execute real model warm-up and sample the idle baseline.
3. Open long generation A, obtain an actual provider token and separately observe a scheduler-running request.
4. Open independent generation B before cancelling A, observe B's own model token, and verify the scheduler remains active before closing A.
5. Close A and measure transport closure. Require B to finish with matching model, real token text and verified terminal.
6. Observe native running/waiting return to zero **and** the model's native aborted-request counter increase within the accepted scheduler budget. After a quiet period, reject any continued generated-token growth.
7. Run a fresh model request without restarting the host; verify its terminal receipt and final idle scheduler.
8. Save bounded technical evidence without user prompts, generated text, credentials or identifying tenant data.

If the host, network, metrics, abort counter, source identity, generation, concurrency or recovery evidence is missing, the probe returns **HOLD**. It does not turn missing instrumentation into success.

## Acceptance boundaries

| Evidence | Meaning |
| --- | --- |
| Canonical stream closure | Karen's provider transport reader closed |
| Native running request before disconnect | vLLM scheduler was actively generating |
| Model-scoped native abort counter increment | The exclusive host observed a model abort |
| Zero running/waiting, stable token counter | Scheduler drained and stopped generating after cancellation |
| Independent B terminal and fresh retry | Model execution recovered without mixing responses |
| KV-cache percentage at quiescence | Bounded cache-usage observation, **not VRAM weight release** |
| GPU memory released automatically | **Not certified** |
| Per-request trace correlated to a particular chat | **Not certified**, native metrics are host-wide |
| Authenticated ChatRuntime/PostgreSQL | **Not established here**, separately tested |
| Ollama or remote-model internal scheduler cancellation | **Not established by this vLLM probe** |

A successful host report states host_scheduler_observation_passed and includes exact SHA, SHA-256 hostname fingerprint, native abort counter before/after, bounded latency measurements, scheduler idle, model terminal truth, and explicit limitations. The evidence artifact is kchat-host-01-native-scheduler and should be inspected together with the protected workflow run.

A missing artifact or unavailable host is a **release HOLD** for this gate, not a passing result. Additional direct evidence is required for GPU/VRAM release, per-request scheduler trace, reverse-proxy disconnect and consumer browser acceptance. Do not set consumer-ready UI flags based on this probe alone.

## Metric/version caution

Prometheus metrics have version-dependent availability. Relevant native series include vllm:num_requests_running, vllm:num_requests_waiting, vllm:generation_tokens_total, vllm:kv_cache_usage_perc and vllm:request_success_total with finished_reason=abort. This probe deliberately requires an observed abort increment and a stable generation counter; a vLLM version that does not emit an abort receipt remains uncertified. Model residency can legitimately persist as warm weights or prefix cache even when no request is running.
