# KCHAT-HOST-02 | Inference-host cancellation evidence and scheduler quiescence

**Default status: HOLD until independently observed on the actual target host.**

## Source of truth and scope

The canonical ChatRuntime, RuntimePolicy, ExpressionGateway, provider registry and Core SSE transport remain authoritative. The host probe is an acceptance consumer of that transport, not a second model executor, chat route, scheduler, fallback or persistence layer.

Previous verified evidence is limited in scope:

- KCHAT-SEC-02: authenticated HTTP/SSE and PostgreSQL transcript tests.
- KCHAT-SEC-03: real but locally initialized CPU Transformer subprocess cancellation.
- KCHAT-SEC-04: installed Ollama model on a **temporary CI runner**, stream closure, a surviving independent request, and an **explicit** native model unload and reload.

Those do not prove model-host scheduler cancellation on Karen's deployment host. This slice targets a direct, locally accessible **vLLM** server because it exposes model-labeled running/waiting gauges, generation counters, and normal request-terminal counters. Socket closure alone is insufficient. The first host gate incorrectly assumed a native abort-reason counter must increase; vLLM may correctly abort without incrementing that metric. Thus, this revision measures native scheduler quiescence and absence of a normal completion in a truly isolated request phase, without calling that a request-specific abort trace.

## Operator and security prerequisites

Before running the probe, the operator must verify:

1. The actual inference host is registered as a self-hosted Linux GitHub Actions runner labeled **karen-inference-host**. The runner must access vLLM through loopback in its own network namespace.
2. The repository environment **inference-host-certification** has real required-reviewer protection, restricted main-branch access, and authorized operators. Naming an environment in workflow YAML **does not automatically enable approvals**.
3. The vLLM server exposes exactly one selected installed model through /v1/models and native, exact-model labeled /metrics series.
4. vLLM exposes model-labeled running, waiting, generated-token, KV-cache and normal stop/length completion metrics. A short warmup must increment the normal completion counter, proving its instrumented presence. The native abort counter is optional evidence because supported vLLM versions may not update it for real aborted requests.
5. The host is exclusive to this acceptance during a maintenance window. Stop other model consumers, warm-up jobs, deployments and benchmarks. The probe also requires a zero-running and zero-waiting native preflight.
6. The checkout's HEAD is the exact requested mainline SHA and its tracked files are unmodified. The operator supplies the actual observed hostname and model ID.
7. The inference runner can create a temporary Python virtual environment. If a local API key is necessary, provide it via the protected KAREN_VLLM_HOST_PROOF_API_KEY secret, never in the workflow parameters or logs.

The acceptance workflow, at .github/workflows/kchat-host-vllm-cancellation-acceptance.yml, has **workflow_dispatch only**. There is no push/PR trigger. Select live main, supply the observed local URL, hostname, model and acceptance budgets, then explicitly approve maintenance_ack. The job uses the protected environment and will run only on the labeled self-hosted runner.

## Execution

The existing Core provider SSE transport performs every inference call:

1. Confirm local /v1 URL, machine and source identity, exact model inventory and idle native gauges.
2. Execute real model warm-up and sample the idle baseline.
3. In an **isolated first phase**, open long generation A, observe an actual provider token and native running-request gauge. Require the native normal completion counter to be unchanged when cancellation starts.
4. Close A and measure transport closure. Start the scheduler-drain budget at the **actual disconnect** rather than after a separate model request finishes. Require zero running/waiting counts before the deadline, a stable generated-token counter after a one-second quiet period, and no new normal stop/length completion for A.
5. In a **second phase**, open long generation A2, then open independent B before closing A2. Verify B's own model token and genuine terminal completion. Require **exactly one** new normal completion (B), and no extra normal completion for A2; check this again after a quiet interval. Drain the scheduler after B without reusing B's duration as a measurement of A's first-phase cancellation latency.
6. Run a fresh model request without restarting the host; verify its terminal receipt and final idle scheduler.
7. Save bounded technical evidence without prompts, generated text, credentials or identifying tenant data, with separate flags for quiescence observed and request-specific abort unverified.

If host, network, required scheduler/normal terminal metrics, source identity, generation, concurrency or recovery evidence is missing, the probe returns **HOLD**. An absent or unchanged native abort counter alone no longer invalidates verified quiescence. It does not turn missing metrics or continued tokens into success.

## Acceptance boundaries

| Evidence | Meaning |
| --- | --- |
| Canonical stream closure | Karen's provider transport reader closed |
| Native running request before disconnect | vLLM scheduler was actively generating |
| Model-scoped native abort counter increment | Optional supporting signal; may stay zero on vLLM even when a request is cancelled |
| Zero running/waiting, stable tokens, no additional normal completion | Native scheduler quiescence observed for an isolated cancelled stream |
| Request-specific internal abort identity | **Not certified** by aggregate host metrics |
| Independent B terminal and fresh retry | Model execution recovered without mixing responses |
| KV-cache percentage at quiescence | Bounded cache-usage observation, **not VRAM weight release** |
| GPU memory released automatically | **Not certified** |
| Per-request trace correlated to a particular chat | **Not certified**, native metrics are host-wide |
| Authenticated ChatRuntime/PostgreSQL | **Not established here**, separately tested |
| Ollama or remote-model internal scheduler cancellation | **Not established by this vLLM probe** |

A successful host report states host_scheduler_quiescence_observed and includes exact SHA, SHA-256 hostname fingerprint, optional native abort counter before/after, **unchanged normal stop/length counter**, bounded latency from disconnect to drain, idle scheduler, independent model terminal, and explicit limitations. The evidence artifact is kchat-host-02-native-quiescence and should be inspected together with the protected workflow run. Even this observed quiescence is **not** a correlated internal request-abort receipt.

A missing artifact or unavailable host is a **release HOLD** for this gate, not a passing result. Additional direct evidence is required for GPU/VRAM release, per-request scheduler trace, reverse-proxy disconnect and consumer browser acceptance. Do not set consumer-ready UI flags based on this probe alone.

## Metric/version caution

Prometheus metrics have version-dependent availability. Relevant native series include vllm:num_requests_running, vllm:num_requests_waiting, vllm:generation_tokens_total, vllm:kv_cache_usage_perc and vllm:request_success_total with finished_reason=abort. An incremented abort counter is not required because some versions omit that signal despite terminating work. Instead, the isolated request must produce native scheduler drain, a stable generation counter and no change to its normal completion counter. The separately marked per-request abort trace remains uncertified. Model residency can legitimately persist as warm weights or prefix cache even when no request is running.


## In-process Transformers retirement boundary (KUI-004B4.48C7Z8E7)

The governed single-device Transformers path fences observed CUDA devices with
`torch.cuda.synchronize(device)` before the native generation lock is released.
The same scope covers governed specialist borrows, including marker mutation,
reference inference, guided generation and verifier operations. The explicit
CPU path does not issue a CUDA synchronization. Unknown device identity denies
governed dispatch. Cancellation does not bypass the retirement fence.

A synchronization failure places the canonical Transformers runtime in a
process-wide native execution hold; replacing the cached model or provider
runtime is not evidence of recovery. No automated reset is supplied. Operators
must investigate the device/driver failure and establish host quiescence before
a controlled restart. No model attempt may be replayed automatically as orphan
recovery. Already-running work on other instances is not certified terminated by
the hold, and the hold is not durable across process death.

The source regression exercises explicit device selection, lock ordering,
cancelled borrow retirement and failed-fence replacement denial using test
doubles. **Actual CUDA host acceptance remains NOT_RUN.** These checks do not
establish multi-device/remote execution, GPU weight release, process-death
recovery, or successful cancellation of a hung driver. Partial failure during
pipeline construction before a device can be observed is a separate acceptance
gap. Do not promote this source contract into a consumer-ready or GPU release
receipt.
