"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Cpu, Database, Gauge, RefreshCw, SlidersHorizontal, Layers3, Server, ShieldCheck, Clock3, ArrowUpRight } from "lucide-react";

import { apiClient, ApiError } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type Engine = { id: string; label: string; supported: boolean; status: "ready" | "worker_offline" | "missing_dependencies" | "not_implemented"; missing_dependencies: string[]; details: string };
type Dataset = { version: string; bytes: number; format: string };
type Catalog = {
  engines: Engine[];
  datasets: Dataset[];
  tasks: string[];
  defaults: {
    engine: string; seed: number; test_split: number; max_samples: number;
    max_iter: number; optimizer: string; class_weight: string; precision: string;
  };
  configuration: { unsupported_export_targets: string[] };
};
type Config = {
  engine: string; task: string; dataset_version: string;
  test_split: number; max_samples: number; seed: number; max_iter: number;
  optimizer: string; class_weight: string; precision: string;
  base_model_path: string; license_id: string; license_accepted: boolean;
  license_model_path: string; epochs: number; sequence_length: number;
  lora_rank: number; allow_cpu_training: boolean; lags: number; horizon: number;
};
type Finding = { code: string; message: string };
type JobSummary = { job_id: string; state: string; submitted_at: string; updated_at: string };
type ExecutionStatus = { queued_jobs: number; active_leases: number; expired_leases: number; worker_status: string; worker_status_reason: string; automatic_dispatch_verified: boolean };
type Preflight = {
  ready: boolean;
  checks: Finding[];
  warnings: Finding[];
  evidence: {
    dataset_version: string; examples_scanned: number;
    class_counts?: Record<string, number>; feature_count?: number;
    holdout_windows?: number;
  };
};

const title = (v: string) => v.replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());

const trainingError = (cause: unknown, action: "read" | "execute"): string => {
  if (cause instanceof ApiError && cause.status === 401) {
    return "Your training session has expired. Sign in again and retry.";
  }
  if (cause instanceof ApiError && cause.status === 403) {
    return action === "execute"
      ? "Job submission requires training:execute permission for your current account and tenant."
      : "Training inventory requires training:read permission and an authenticated tenant-scoped session. Check your assigned role and tenant, then retry.";
  }
  return cause instanceof Error ? cause.message : "Training service unavailable";
};

export default function AdvancedTrainingWorkbench() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [executionStatus, setExecutionStatus] = useState<ExecutionStatus | null>(null);
  const [queueing, setQueueing] = useState(false);
  const [queueMessage, setQueueMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await apiClient.get<Catalog>("/api/admin/training/advanced/catalog");
      setCatalog(response);
      setConfig({
        ...response.defaults,
        task: response.tasks.includes("execution_topology") ? "execution_topology" : response.tasks[0] ?? "",
        dataset_version: response.datasets[0]?.version ?? "",
        base_model_path: "", license_id: "", license_accepted: false,
        license_model_path: "", epochs: 1, sequence_length: 256,
        lora_rank: 8, allow_cpu_training: false, lags: 5, horizon: 1,
      });
      setPreflight(null);
    } catch (cause) {
      setError(trainingError(cause, "read"));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const change = <K extends keyof Config>(key: K, value: Config[K]) => {
    setConfig(previous => previous ? {
      ...previous, [key]: value,
      ...(key === "engine" ? { max_iter: value === "spacy" ? 20 : (catalog?.defaults.max_iter ?? 1000), task: value === "timeseries" ? "outcome_forecast" : previous.task } : {}),
      ...(key === "base_model_path" ? { license_accepted: false, license_model_path: "" } : {}),
    } : previous);
    setPreflight(null);
  };

  const validate = async () => {
    if (!config) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiClient.post<Preflight>(
        "/api/admin/training/advanced/preflight",
        config,
      );
      setPreflight(result);
    } catch (cause) {
      setPreflight(null);
      setError(trainingError(cause, "read"));
    } finally {
      setBusy(false);
    }
  };

  const loadJobs = useCallback(async () => {
    try {
      const response = await apiClient.get<{ jobs: JobSummary[] }>("/api/admin/training/advanced/jobs");
      setJobs(response.jobs);
      const status = await apiClient.get<ExecutionStatus>("/api/admin/training/advanced/execution-status");
      setExecutionStatus(status);
    } catch (cause) {
      setExecutionStatus(null);
      setError(trainingError(cause, "read"));
    }
  }, []);

  useEffect(() => { void loadJobs(); }, [loadJobs]);

  const queueJob = async () => {
    if (!config || !preflight?.ready) return;
    setQueueing(true);
    setQueueMessage(null);
    try {
      const queued = await apiClient.post<{ job_id: string; status: string }>(
        "/api/admin/training/advanced/jobs", config,
      );
      setQueueMessage(`Job ${queued.job_id} submitted as ${queued.status}. This does not confirm that a worker has started.`);
      await loadJobs();
      setPreflight(null);
    } catch (cause) {
      setError(trainingError(cause, "execute"));
    } finally {
      setQueueing(false);
    }
  };

  if (!catalog || !config) {
    return (
      <Card><CardContent className="flex items-center gap-3 p-6">
        <Activity className="h-5 w-5" />
        <span>{error || "Loading backend training capabilities..."}</span>
        <Button size="sm" variant="outline" onClick={() => void load()}>Retry</Button>
      </CardContent></Card>
    );
  }

  const selectedEngine = catalog.engines.find(engine => engine.id === config.engine);
  const readyEngines = catalog.engines.filter(engine => engine.supported && engine.status === "ready").length;
  const workerReady = executionStatus?.worker_status === "ready" && executionStatus.automatic_dispatch_verified;
  return (
    <div className="space-y-6 rounded-2xl bg-[#090b10] p-3 text-slate-100 sm:p-5 xl:p-7">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-5">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.19em] text-cyan-300"><span className="h-1.5 w-1.5 rounded-full bg-cyan-300" />Training control plane / Execution workbench</div>
          <h3 className="text-2xl font-semibold tracking-tight text-slate-50 sm:text-3xl">Train a Model</h3>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
            Configure a governed training run, inspect backend readiness, and submit to the durable execution queue.
          </p>
        </div>
        <Button variant="outline" size="sm" className="border-white/15 bg-white/5 text-slate-200 hover:bg-white/10" onClick={() => { void load(); void loadJobs(); }} disabled={busy}>
          <RefreshCw className="mr-2 h-4 w-4" />Refresh capabilities
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-white/10 bg-white/[0.035] p-4"><div className="flex items-center justify-between text-xs font-medium uppercase tracking-widest text-slate-400"><span>Architectures</span><Layers3 className="h-4 w-4 text-cyan-300" /></div><div className="mt-3 text-2xl font-semibold tabular-nums">{readyEngines}<span className="ml-2 text-sm font-normal text-slate-500">/ {catalog.engines.length} ready</span></div><p className="mt-1 text-xs text-slate-500">Verified executor availability</p></div>
        <div className="rounded-xl border border-white/10 bg-white/[0.035] p-4"><div className="flex items-center justify-between text-xs font-medium uppercase tracking-widest text-slate-400"><span>Versioned datasets</span><Database className="h-4 w-4 text-indigo-300" /></div><div className="mt-3 text-2xl font-semibold tabular-nums">{catalog.datasets.length}</div><p className="mt-1 text-xs text-slate-500">Catalogued by the backend</p></div>
        <div className="rounded-xl border border-white/10 bg-white/[0.035] p-4"><div className="flex items-center justify-between text-xs font-medium uppercase tracking-widest text-slate-400"><span>Worker dispatch</span><Server className="h-4 w-4 text-cyan-300" /></div><div className="mt-3 text-lg font-semibold">{!executionStatus ? "Unverified" : workerReady ? "Verified" : title(executionStatus.worker_status)}</div><p className="mt-1 text-xs text-slate-500">{executionStatus ? `${executionStatus.queued_jobs} queued · ${executionStatus.active_leases} active leases` : "Awaiting live execution status"}</p></div>
      </div>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(340px,0.7fr)]">
        <div className="min-w-0 space-y-5">
          <Card className="border-white/10 bg-[#12151d] text-slate-100 shadow-xl shadow-black/10">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base">
              <Cpu className="h-4 w-4 text-indigo-300" />Architecture &amp; execution engine
            </CardTitle><CardDescription>
              Engines without a verified runtime executor cannot launch.
            </CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                {catalog.engines.map(engine => (
                  <button type="button" key={engine.id} disabled={!engine.supported}
                    aria-pressed={config.engine === engine.id}
                    onClick={() => change("engine", engine.id)}
                    className={`group relative flex min-h-40 flex-col rounded-xl border p-4 text-left transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:cursor-not-allowed disabled:opacity-60 ${config.engine === engine.id ? "border-indigo-300/75 bg-indigo-400/10 shadow-[inset_0_0_0_1px_rgba(165,180,252,0.22)]" : "border-white/10 bg-[#0c0f15] hover:border-white/30 hover:bg-white/[0.04]"}`}>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <span className="max-w-[14rem] text-sm font-semibold leading-5 text-slate-100">{engine.label}</span>
                      <Badge variant={engine.supported ? "secondary" : "outline"}>
                        {engine.status === "ready" ? "Executor ready" : engine.status === "worker_offline" ? "Training worker offline" : engine.status === "missing_dependencies" ? "Worker dependencies missing" : "Executor not implemented"}
                      </Badge>
                    </div>
                    <p className="flex-1 text-xs leading-5 text-slate-400">{engine.details}</p>
                    {engine.missing_dependencies.length > 0 && (
                      <p className="mt-3 border-t border-white/10 pt-2 text-xs text-amber-200">Missing: {engine.missing_dependencies.join(", ")}</p>
                    )}
                  </button>
                ))}
              </div>
              <div className="space-y-2">
                <Label>Prediction task</Label>
                <Select value={config.task} onValueChange={v => change("task", v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{catalog.tasks.map(task => (
                    <SelectItem key={task} value={task}>{title(task)}</SelectItem>
                  ))}</SelectContent>
                </Select>
              </div>
              {config.engine === "timeseries" && (
                <div className="space-y-3 rounded-lg border p-3">
                  <p className="text-sm font-semibold">Chronological forecasting</p>
                  <p className="text-xs text-muted-foreground">JSONL records need a timezone-aware timestamp and finite numeric value, strictly increasing within one series. Holdout is chronological, not randomly shuffled.</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div><Label htmlFor="temporal-lags">Observed lag window</Label><Input id="temporal-lags" type="number" min={2} max={128} value={config.lags} onChange={e => change("lags", Number(e.target.value))}/></div>
                    <div><Label htmlFor="temporal-horizon">Forecast horizon</Label><Input id="temporal-horizon" type="number" min={1} max={32} value={config.horizon} onChange={e => change("horizon", Number(e.target.value))}/></div>
                  </div>
                  <p className="text-xs text-muted-foreground">Models remain candidates until an engine-specific benchmark approves promotion.</p>
                </div>
              )}
              {config.engine === "transformers" && (
                <div className="space-y-3 rounded-lg border p-3">
                  <p className="text-sm font-semibold">Local LoRA adapter training</p>
                  <p className="text-xs text-muted-foreground">Requires an already-installed local Hugging Face model, JSONL text records, torch, transformers and peft. No automatic model downloads.</p>
                  <div><Label htmlFor="lora-model">Absolute local base-model path</Label><Input id="lora-model" value={config.base_model_path} onChange={e => change("base_model_path", e.target.value)} placeholder="/models/base-model"/></div>
                  <div><Label htmlFor="lora-license">Model license identifier (operator-declared)</Label><Input id="lora-license" value={config.license_id} onChange={e => { change("license_id", e.target.value); }} placeholder="License name or source reference"/></div>
                  <label className="flex items-start gap-2 text-sm">
                    <input type="checkbox" checked={config.license_accepted} onChange={e => setConfig(previous => previous ? { ...previous, license_accepted: e.target.checked, license_model_path: e.target.checked ? previous.base_model_path : "" } : previous)} />
                    <span>I reviewed the model terms from its source and accept them for this exact installed base model. This acknowledgment does not verify the source license automatically.</span>
                  </label>
                  <div className="grid grid-cols-3 gap-3">
                    <div><Label>Epochs</Label><Input type="number" min={1} max={10} value={config.epochs} onChange={e => change("epochs", Number(e.target.value))}/></div>
                    <div><Label>Token length</Label><Input type="number" min={32} max={2048} value={config.sequence_length} onChange={e => change("sequence_length", Number(e.target.value))}/></div>
                    <div><Label>LoRA rank</Label><Select value={String(config.lora_rank)} onValueChange={value => change("lora_rank", Number(value))}><SelectTrigger><SelectValue/></SelectTrigger><SelectContent>{[4,8,16,32].map(rank => <SelectItem key={rank} value={String(rank)}>{rank}</SelectItem>)}</SelectContent></Select></div>
                  </div>
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={config.allow_cpu_training} onChange={e => change("allow_cpu_training", e.target.checked)}/>Permit CPU training when CUDA is unavailable (slow)</label>
                  <p className="text-xs text-muted-foreground">Adapter candidates are not automatically promoted or used in chat inference.</p>
                </div>
              )}
              {selectedEngine && !selectedEngine.supported && (
                <Alert><AlertTriangle className="h-4 w-4" /><AlertDescription>
                  {selectedEngine.details} Validation will reject unsupported launch requests.
                </AlertDescription></Alert>
              )}
            </CardContent>
          </Card>
          <Card className="border-white/10 bg-[#12151d] text-slate-100">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base">
              <Database className="h-4 w-4" />Dataset &amp; preprocessing
            </CardTitle><CardDescription>
              Only existing versioned JSONL ML corpora appear here. Memory-derived datasets
              must pass curated ingest before training.
            </CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Versioned ML dataset</Label>
                {catalog.datasets.length ? (
                  <Select value={config.dataset_version} onValueChange={v => change("dataset_version", v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{catalog.datasets.map(item => (
                      <SelectItem value={item.version} key={item.version}>
                        {item.version} ({(item.bytes / 1024).toFixed(1)} KiB)
                      </SelectItem>
                    ))}</SelectContent>
                  </Select>
                ) : <p className="text-sm text-muted-foreground">
                  No canonical ML JSONL datasets found. Build or register a dataset before running preflight.
                </p>}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2"><Label>Held-out test split</Label>
                  <Input type="number" min="0.05" max="0.5" step="0.05" value={config.test_split}
                    onChange={e => change("test_split", Number(e.target.value))} />
                </div>
                <div className="space-y-2"><Label>Maximum samples</Label>
                  <Input type="number" min="10" max="10000000" value={config.max_samples}
                    onChange={e => change("max_samples", Number(e.target.value))} />
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
        <div className="min-w-0 space-y-5">
          <Card className="border-white/10 bg-[#12151d] text-slate-100">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base">
              <SlidersHorizontal className="h-4 w-4" />Optimizer &amp; reproducibility
            </CardTitle><CardDescription>
              The supported sklearn executor currently uses logistic regression and LBFGS.
            </CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2"><Label>Seed</Label>
                  <Input type="number" min="0" value={config.seed}
                    onChange={e => change("seed", Number(e.target.value))} />
                </div>
                <div className="space-y-2"><Label>Max iterations</Label>
                  <Input type="number" min="100" max="10000" value={config.max_iter}
                    onChange={e => change("max_iter", Number(e.target.value))} />
                </div>
              </div>
              <div className="space-y-2"><Label>Class weighting</Label>
                <Select value={config.class_weight} onValueChange={v => change("class_weight", v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="balanced">Balanced</SelectItem>
                    <SelectItem value="none">None</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Optimizer</Label><p className="mt-2 text-sm">LBFGS</p></div>
                <div><Label>Precision</Label><p className="mt-2 text-sm">CPU float64</p></div>
              </div>
              <p className="text-xs text-muted-foreground">
                GPU precision, gradient accumulation, distributed training, spaCy component freezing,
                and advanced checkpoint/export targets unlock only with verified backend executors.
              </p>
            </CardContent>
          </Card>
          <Card className="border-indigo-300/20 bg-[#12151d] text-slate-100 shadow-[0_16px_40px_rgba(0,0,0,0.2)]">
            <CardHeader><CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="h-4 w-4" />Preflight &amp; execution readiness
            </CardTitle><CardDescription>
              Dataset schema, feature order, class support, selected engine and optimizer compatibility.
            </CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className={`rounded-xl border px-4 py-3 ${preflight?.ready ? "border-cyan-400/30 bg-cyan-400/5" : "border-white/10 bg-white/[0.03]"}`} role="status"><div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Execution gate</span><Badge variant="outline">{preflight?.ready ? "Preflight passed" : preflight ? "Blocked" : "Not validated"}</Badge></div><p className="mt-2 text-sm text-slate-300">{preflight?.ready ? "Configuration passed backend checks. Submission still requires an available worker." : preflight ? "Review the findings below and run preflight again." : "Run preflight to obtain backend evidence before queuing."}</p></div>
              <Button className="w-full border border-white/15 bg-white/10 text-slate-100 hover:bg-white/15" onClick={() => void validate()} disabled={busy || !config.dataset_version}>
                {busy ? "Validating..." : "Run backend preflight"}
              </Button>
              {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
              {preflight && <>
                <div className="flex items-center gap-2">
                  {preflight.ready ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> :
                    <AlertTriangle className="h-5 w-5 text-amber-500" />}
                  <strong>{preflight.ready ? "Preflight passed" : "Preflight blocked"}</strong>
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div className="rounded-lg bg-muted/50 p-3">Samples: {preflight.evidence.examples_scanned}</div>
                  {typeof preflight.evidence.feature_count === "number" && (
                    <div className="rounded-lg bg-muted/50 p-3">Features: {preflight.evidence.feature_count}</div>
                  )}
                  {typeof preflight.evidence.holdout_windows === "number" && (
                    <div className="rounded-lg bg-muted/50 p-3">Holdout windows: {preflight.evidence.holdout_windows}</div>
                  )}
                  {preflight.evidence.class_counts && (
                    <div className="rounded-lg bg-muted/50 p-3 col-span-2">
                      Classes: {Object.entries(preflight.evidence.class_counts)
                        .map(([name, count]) => `${name} (${count})`).join(", ") || "Not available"}
                    </div>
                  )}
                </div>
                {[...preflight.checks, ...preflight.warnings].map(item => (
                  <div key={item.code} className="rounded-lg border p-3 text-sm">
                    <strong>{title(item.code)}</strong><p className="mt-1 text-muted-foreground">{item.message}</p>
                  </div>
                ))}
                {preflight.ready && (
                  <Button className="w-full bg-indigo-300 font-semibold text-slate-950 hover:bg-indigo-200" disabled={queueing}
                    onClick={() => void queueJob()}>
                    {queueing ? "Submitting..." : "Queue approved training job"}
                  </Button>
                )}
                {queueMessage && <p className="text-sm" role="status">{queueMessage}</p>}
                <Alert><AlertTriangle className="h-4 w-4" /><AlertTitle>Execution remains governed</AlertTitle>
                  <AlertDescription>
                    Preflight confirms eligibility only. Queued jobs need an active training worker.
                    Refresh Training Jobs to see the real persisted state; a queued job is not a completed model.
                  </AlertDescription>
                </Alert>
              </>}
            </CardContent>
          </Card>
        </div>
      </div>
      <Card className="border-white/10 bg-[#12151d] text-slate-100">
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base"><Clock3 className="h-4 w-4 text-cyan-300" />Training jobs &amp; execution queue</CardTitle>
            <CardDescription>Backend-reported state, not estimated progress.</CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={() => void loadJobs()}>
            <RefreshCw className="mr-2 h-4 w-4" />Refresh jobs
          </Button>
        </CardHeader>
        <CardContent className="space-y-2">
          {executionStatus && (
            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Worker availability: {executionStatus.worker_status}</AlertTitle>
              <AlertDescription>
                {executionStatus.worker_status_reason}. Queued: {executionStatus.queued_jobs};
                active job leases: {executionStatus.active_leases};
                expired leases: {executionStatus.expired_leases}.
                {executionStatus.expired_leases > 0 && " Operator recovery review required."}
                {!executionStatus.automatic_dispatch_verified && " Automatic dispatch has not been verified."}
              </AlertDescription>
            </Alert>
          )}
          {jobs.length === 0 && <p className="text-sm text-muted-foreground">No jobs reported for this tenant.</p>}
          {jobs.map(job => (
            <div key={job.job_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#0b0e14] p-4 transition-colors hover:border-white/20">
              <div>
                <p className="flex items-center gap-2 font-mono text-xs font-semibold text-indigo-200"><ArrowUpRight className="h-3.5 w-3.5" />{job.job_id}</p>
                <p className="text-xs text-muted-foreground">Updated: {job.updated_at || "Unavailable"}</p>
              </div>
              <Badge variant="outline" className="border-white/20 text-slate-200">{title(job.state)}</Badge>
            </div>
          ))}
          {queueMessage && <p className="text-sm" role="status">{queueMessage}</p>}
        </CardContent>
      </Card>
    </div>
  );
}
