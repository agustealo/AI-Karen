"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Cpu, Database, Gauge, RefreshCw, SlidersHorizontal } from "lucide-react";

import { apiClient, ApiError } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type Engine = { id: string; label: string; supported: boolean; status: "ready" | "missing_dependencies" | "not_implemented"; missing_dependencies: string[]; details: string };
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
    class_counts: Record<string, number>; feature_count: number;
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
      ...(key === "engine" ? { max_iter: value === "spacy" ? 20 : (catalog?.defaults.max_iter ?? 1000) } : {}),
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
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-xl font-semibold">Train a Model</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Choose a supported model type and dataset, validate the configuration, then queue training.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={busy}>
          <RefreshCw className="mr-2 h-4 w-4" />Refresh capabilities
        </Button>
      </div>
      <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-5">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-base">
              <Cpu className="h-4 w-4" />Architecture &amp; execution engine
            </CardTitle><CardDescription>
              Engines without a verified runtime executor cannot launch.
            </CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                {catalog.engines.map(engine => (
                  <button type="button" key={engine.id} disabled={!engine.supported}
                    aria-pressed={config.engine === engine.id}
                    onClick={() => change("engine", engine.id)}
                    className={`rounded-xl border p-4 text-left transition-colors ${config.engine === engine.id ? "border-primary bg-primary/5" : "border-border/70 hover:bg-muted/30"}`}>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-semibold">{engine.label}</span>
                      <Badge variant={engine.supported ? "secondary" : "outline"}>
                        {engine.status === "ready" ? "Executor ready" : engine.status === "missing_dependencies" ? "Dependencies missing" : "Executor not implemented"}
                      </Badge>
                    </div>
                    <p className="text-xs leading-5 text-muted-foreground">{engine.details}</p>
                    {engine.missing_dependencies.length > 0 && (
                      <p className="mt-2 text-xs text-muted-foreground">Missing: {engine.missing_dependencies.join(", ")}</p>
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
              {selectedEngine && !selectedEngine.supported && (
                <Alert><AlertTriangle className="h-4 w-4" /><AlertDescription>
                  {selectedEngine.details} Validation will reject unsupported launch requests.
                </AlertDescription></Alert>
              )}
            </CardContent>
          </Card>
          <Card>
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
        <div className="space-y-5">
          <Card>
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
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-base">
              <Gauge className="h-4 w-4" />Preflight &amp; execution readiness
            </CardTitle><CardDescription>
              Dataset schema, feature order, class support, selected engine and optimizer compatibility.
            </CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <Button className="w-full" onClick={() => void validate()} disabled={busy || !config.dataset_version}>
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
                  <div className="rounded-lg bg-muted/50 p-3">Features: {preflight.evidence.feature_count}</div>
                  <div className="rounded-lg bg-muted/50 p-3 col-span-2">
                    Classes: {Object.entries(preflight.evidence.class_counts)
                      .map(([name, count]) => `${name} (${count})`).join(", ") || "Not available"}
                  </div>
                </div>
                {[...preflight.checks, ...preflight.warnings].map(item => (
                  <div key={item.code} className="rounded-lg border p-3 text-sm">
                    <strong>{title(item.code)}</strong><p className="mt-1 text-muted-foreground">{item.message}</p>
                  </div>
                ))}
                {preflight.ready && (
                  <Button className="w-full" variant="secondary" disabled={queueing}
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
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">Training Jobs</CardTitle>
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
            <div key={job.job_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3">
              <div>
                <p className="text-sm font-medium">{job.job_id}</p>
                <p className="text-xs text-muted-foreground">Updated: {job.updated_at || "Unavailable"}</p>
              </div>
              <Badge variant="outline">{job.state}</Badge>
            </div>
          ))}
          {queueMessage && <p className="text-sm" role="status">{queueMessage}</p>}
        </CardContent>
      </Card>
    </div>
  );
}
