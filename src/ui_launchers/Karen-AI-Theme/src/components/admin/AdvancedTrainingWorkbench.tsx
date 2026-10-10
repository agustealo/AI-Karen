"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Cpu,
  Database,
  Gauge,
  HardDrive,
  Loader2,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";

import { apiClient, ApiError } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Engine = {
  id: string;
  label: string;
  supported: boolean;
  status: "ready" | "worker_offline" | "missing_dependencies" | "not_implemented";
  missing_dependencies: string[];
  details: string;
};

type Dataset = {
  version: string;
  bytes: number;
  format: string;
  schema_engines?: string[];
  inspection_status?: string;
  inspection_reason?: string;
  scope?: "legacy" | "tenant";
};

type Catalog = {
  engines: Engine[];
  datasets: Dataset[];
  tasks: string[];
  defaults: {
    engine: string;
    seed: number;
    test_split: number;
    max_samples: number;
    max_iter: number;
    optimizer: string;
    class_weight: string;
    precision: string;
  };
  configuration: {
    unsupported_export_targets: string[];
  };
};

type Config = {
  engine: string;
  task: string;
  dataset_version: string;
  dataset_scope: "legacy" | "tenant";
  test_split: number;
  max_samples: number;
  seed: number;
  max_iter: number;
  optimizer: string;
  class_weight: string;
  precision: string;
  base_model_path: string;
  license_id: string;
  license_accepted: boolean;
  license_model_path: string;
  epochs: number;
  sequence_length: number;
  lora_rank: number;
  allow_cpu_training: boolean;
  lags: number;
  horizon: number;
};

type Finding = {
  code: string;
  message: string;
};

type JobSummary = {
  job_id: string;
  state: string;
  submitted_at: string;
  updated_at: string;
};

type ExecutionStatus = {
  queued_jobs: number;
  active_leases: number;
  expired_leases: number;
  worker_status: string;
  worker_status_reason: string;
  automatic_dispatch_verified: boolean;
};

type Preflight = {
  ready: boolean;
  checks: Finding[];
  warnings: Finding[];
  evidence: {
    dataset_version: string;
    examples_scanned: number;
    class_counts?: Record<string, number>;
    feature_count?: number;
    holdout_windows?: number;
  };
};

const title = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());

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

const engineStatusLabel = (engine: Engine): string => {
  switch (engine.status) {
    case "ready":
      return "Executor ready";
    case "worker_offline":
      return "Worker offline";
    case "missing_dependencies":
      return "Dependencies missing";
    default:
      return "Not implemented";
  }
};

const engineStatusVariant = (
  engine: Engine,
): "default" | "secondary" | "destructive" | "outline" => {
  if (engine.status === "ready") return "secondary";
  if (engine.status === "worker_offline" || engine.status === "missing_dependencies") {
    return "outline";
  }
  return "destructive";
};

const jobStateClass = (state: string): string => {
  const normalized = state.toLowerCase();

  if (normalized.includes("run") || normalized.includes("active")) {
    return "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-300";
  }

  if (normalized.includes("complete") || normalized.includes("succeed")) {
    return "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300";
  }

  if (normalized.includes("fail") || normalized.includes("error")) {
    return "border-destructive/30 bg-destructive/10 text-destructive";
  }

  return "border-border/70 bg-muted/50 text-muted-foreground";
};

const formatBytes = (bytes: number): string => {
  if (!Number.isFinite(bytes) || bytes < 0) return "Unknown";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KiB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MiB";
};

const formatTimestamp = (value: string): string => {
  if (!value) return "Unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
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
        task: response.tasks.includes("execution_topology")
          ? "execution_topology"
          : response.tasks[0] ?? "",
        dataset_version: response.datasets[0]?.version ?? "",
        dataset_scope: response.datasets[0]?.scope ?? "legacy",
        base_model_path: "",
        license_id: "",
        license_accepted: false,
        license_model_path: "",
        epochs: 1,
        sequence_length: 256,
        lora_rank: 8,
        allow_cpu_training: false,
        lags: 5,
        horizon: 1,
      });
      setPreflight(null);
    } catch (cause) {
      setError(trainingError(cause, "read"));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const change = <K extends keyof Config>(key: K, value: Config[K]) => {
    setConfig((previous) =>
      previous
        ? {
            ...previous,
            [key]: value,
            ...(key === "engine"
              ? {
                  max_iter:
                    value === "spacy" ? 20 : (catalog?.defaults.max_iter ?? 1000),
                  task:
                    value === "timeseries"
                      ? "outcome_forecast"
                      : previous.task,
                }
              : {}),
            ...(key === "base_model_path"
              ? {
                  license_accepted: false,
                  license_model_path: "",
                }
              : {}),
          }
        : previous,
    );
    setPreflight(null);
    setQueueMessage(null);
  };

  const validate = async () => {
    if (!config) return;

    setBusy(true);
    setError(null);
    setQueueMessage(null);

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
      const [jobResponse, status] = await Promise.all([
        apiClient.get<{ jobs: JobSummary[] }>("/api/admin/training/advanced/jobs"),
        apiClient.get<ExecutionStatus>(
          "/api/admin/training/advanced/execution-status",
        ),
      ]);

      setJobs(jobResponse.jobs);
      setExecutionStatus(status);
    } catch (cause) {
      setExecutionStatus(null);
      setError(trainingError(cause, "read"));
    }
  }, []);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const queueJob = async () => {
    if (!config || !preflight?.ready) return;

    setQueueing(true);
    setQueueMessage(null);
    setError(null);

    try {
      const queued = await apiClient.post<{ job_id: string; status: string }>(
        "/api/admin/training/advanced/jobs",
        config,
      );

      setQueueMessage(
        "Job " +
          queued.job_id +
          " submitted as " +
          queued.status +
          ". This confirms persistence only. Worker execution remains backend-reported.",
      );
      await loadJobs();
      setPreflight(null);
    } catch (cause) {
      setError(trainingError(cause, "execute"));
    } finally {
      setQueueing(false);
    }
  };

  const supportedEngineCount = useMemo(
    () => catalog?.engines.filter((engine) => engine.supported).length ?? 0,
    [catalog],
  );

  const selectedEngine = catalog?.engines.find(
    (engine) => engine.id === config?.engine,
  );

  const readinessValue = preflight ? (preflight.ready ? 100 : 35) : 0;

  if (!catalog || !config) {
    return (
      <Card className="overflow-hidden border-border/70">
        <CardContent className="flex min-h-48 flex-col items-center justify-center gap-4 p-6 text-center">
          {busy ? (
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          ) : (
            <Activity className="h-6 w-6 text-muted-foreground" />
          )}
          <div>
            <p className="font-medium">
              {error || "Loading backend training capabilities..."}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              Karen only renders engines and datasets reported by the training service.
            </p>
          </div>
          {!busy && (
            <Button size="sm" variant="outline" onClick={() => void load()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-2xl border border-border/70 bg-card">
        <div className="border-b border-border/70 bg-gradient-to-br from-primary/10 via-background to-background px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-3xl">
              <div className="mb-3 flex flex-wrap gap-2">
                <Badge variant="outline" className="border-primary/30 bg-primary/5 text-primary">
                  Governed execution
                </Badge>
                <Badge variant="outline">Tenant scoped</Badge>
                <Badge variant="outline">Backend truth only</Badge>
              </div>
              <h3 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
                <Sparkles className="h-5 w-5 text-primary" />
                Train a Model
              </h3>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                Select a real executor, bind a versioned dataset, tune supported controls,
                pass backend preflight, and submit the approved job to Karen&apos;s persisted
                training queue.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void load()}
                disabled={busy}
              >
                {busy ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                Refresh capabilities
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void loadJobs()}
              >
                <Activity className="mr-2 h-4 w-4" />
                Refresh execution
              </Button>
            </div>
          </div>
        </div>

        <div className="grid gap-px bg-border/60 sm:grid-cols-2 xl:grid-cols-4">
          <div className="bg-card p-4">
            <div className="flex items-center justify-between text-xs uppercase tracking-[0.16em] text-muted-foreground">
              <span>Executors</span>
              <Cpu className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 text-2xl font-semibold">{supportedEngineCount}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              of {catalog.engines.length} available
            </div>
          </div>

          <div className="bg-card p-4">
            <div className="flex items-center justify-between text-xs uppercase tracking-[0.16em] text-muted-foreground">
              <span>Datasets</span>
              <Database className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 text-2xl font-semibold">{catalog.datasets.length}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              versioned training corpora
            </div>
          </div>

          <div className="bg-card p-4">
            <div className="flex items-center justify-between text-xs uppercase tracking-[0.16em] text-muted-foreground">
              <span>Worker</span>
              <ServerCog className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 truncate text-lg font-semibold">
              {executionStatus?.worker_status || "Unavailable"}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {executionStatus
                ? executionStatus.automatic_dispatch_verified
                  ? "automatic dispatch verified"
                  : "dispatch verification pending"
                : "status not loaded"}
            </div>
          </div>

          <div className="bg-card p-4">
            <div className="flex items-center justify-between text-xs uppercase tracking-[0.16em] text-muted-foreground">
              <span>Queue</span>
              <Clock3 className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 text-2xl font-semibold">
              {executionStatus?.queued_jobs ?? 0}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {executionStatus?.active_leases ?? 0} active lease
              {(executionStatus?.active_leases ?? 0) === 1 ? "" : "s"}
            </div>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h4 className="text-base font-semibold">Architecture &amp; Execution Engine</h4>
            <p className="mt-1 text-sm text-muted-foreground">
              Capability cards are generated from the backend catalog. Unsupported engines
              remain visible for operator awareness but cannot be selected.
            </p>
          </div>
          <Badge variant="outline">
            {selectedEngine ? engineStatusLabel(selectedEngine) : "No engine selected"}
          </Badge>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {catalog.engines.map((engine) => {
            const selected = config.engine === engine.id;

            return (
              <button
                type="button"
                key={engine.id}
                disabled={!engine.supported}
                aria-pressed={selected}
                onClick={() => change("engine", engine.id)}
                className={
                  "group flex min-h-48 flex-col justify-between rounded-2xl border p-4 text-left transition-all " +
                  (selected
                    ? "border-primary bg-primary/5 shadow-sm"
                    : "border-border/70 bg-card hover:border-border hover:bg-muted/20") +
                  (!engine.supported ? " cursor-not-allowed opacity-70" : "")
                }
              >
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <div
                      className={
                        "flex h-10 w-10 items-center justify-center rounded-xl border " +
                        (selected
                          ? "border-primary/30 bg-primary/10 text-primary"
                          : "border-border/70 bg-muted/40 text-muted-foreground")
                      }
                    >
                      <Cpu className="h-5 w-5" />
                    </div>
                    <Badge variant={engineStatusVariant(engine)}>
                      {engineStatusLabel(engine)}
                    </Badge>
                  </div>

                  <div className="mt-4 font-semibold">{engine.label}</div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    {engine.details}
                  </p>
                </div>

                <div className="mt-4 border-t border-border/60 pt-3 text-xs text-muted-foreground">
                  {engine.missing_dependencies.length > 0
                    ? "Missing: " + engine.missing_dependencies.join(", ")
                    : engine.supported
                      ? "Eligible for backend preflight"
                      : "Launch requests are rejected"}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-12">
        <div className="space-y-6 xl:col-span-7">
          <Card className="border-border/70">
            <CardHeader className="border-b border-border/60">
              <CardTitle className="flex items-center gap-2 text-base">
                <Database className="h-4 w-4 text-primary" />
                Dataset &amp; Preprocessing
              </CardTitle>
              <CardDescription>
                Training input is restricted to registered versioned datasets. Curated
                memory must be staged through the governed ingest path first.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5 pt-6">
              <div className="space-y-2">
                <Label>Versioned ML dataset</Label>
                {catalog.datasets.length ? (
                  <Select
                    value={`${config.dataset_scope}:${config.dataset_version}`}
                    onValueChange={(value) => {
                      const item = catalog.datasets.find((entry) => `${entry.scope ?? "legacy"}:${entry.version}` === value);
                      if (!item) return;
                      setConfig((previous) => previous ? {...previous, dataset_version: item.version, dataset_scope: item.scope ?? "legacy"} : previous);
                      setPreflight(null);
                    }}
                  >
                    <SelectTrigger className="h-11">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {catalog.datasets.map((item) => (
                        <SelectItem value={`${item.scope ?? "legacy"}:${item.version}`} key={`${item.scope ?? "legacy"}:${item.version}`}>
                          {item.version} · {item.scope === "tenant" ? "Private" : "Shared"} · {item.format} · {formatBytes(item.bytes)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Alert>
                    <HardDrive className="h-4 w-4" />
                    <AlertTitle>No registered training datasets</AlertTitle>
                    <AlertDescription>
                      Build or register a governed dataset before running preflight.
                    </AlertDescription>
                  </Alert>
                )}
              </div>

              {(() => {
                const chosen = catalog.datasets.find((item) => item.version === config.dataset_version);
                if (!chosen) return null;
                const matches = chosen.schema_engines?.includes(config.engine) ?? false;
                return (
                  <div className="rounded-xl border border-border/70 bg-muted/20 p-4 text-sm">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">Dataset schema inspection</span>
                      <Badge variant="outline">
                        {chosen.inspection_status === "structural_only"
                          ? matches ? "Structure matches" : "Structure mismatch"
                          : "Not verified"}
                      </Badge>
                    </div>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {chosen.inspection_status === "structural_only" && !matches
                        ? `The selected ${title(config.engine)} engine does not match the inspected record shape.`
                        : chosen.inspection_reason ?? "No dataset inspection was reported."}
                      {" "}Full backend preflight is required before submission.
                    </p>
                  </div>
                );
              })()}

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-xl border border-border/70 bg-muted/20 p-4">
                  <Label htmlFor="test-split">Held-out test split</Label>
                  <Input
                    id="test-split"
                    className="mt-3"
                    type="number"
                    min="0.05"
                    max="0.5"
                    step="0.05"
                    value={config.test_split}
                    onChange={(event) =>
                      change("test_split", Number(event.target.value))
                    }
                  />
                  <p className="mt-2 text-xs text-muted-foreground">
                    Evaluation remains separated from training evidence.
                  </p>
                </div>

                <div className="rounded-xl border border-border/70 bg-muted/20 p-4">
                  <Label htmlFor="max-samples">Maximum samples</Label>
                  <Input
                    id="max-samples"
                    className="mt-3"
                    type="number"
                    min="10"
                    max="10000000"
                    value={config.max_samples}
                    onChange={(event) =>
                      change("max_samples", Number(event.target.value))
                    }
                  />
                  <p className="mt-2 text-xs text-muted-foreground">
                    Bound execution cost without inventing synthetic progress.
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <Label>Prediction task</Label>
                <Select
                  value={config.task}
                  onValueChange={(value) => change("task", value)}
                >
                  <SelectTrigger className="h-11">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {catalog.tasks.map((task) => (
                      <SelectItem key={task} value={task}>
                        {title(task)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {config.engine === "timeseries" && (
                <div className="space-y-4 rounded-2xl border border-border/70 bg-muted/20 p-4">
                  <div>
                    <div className="font-semibold">Chronological forecasting contract</div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      JSONL records require a timezone-aware timestamp and finite numeric
                      value, strictly increasing within one series. Holdout remains
                      chronological.
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label htmlFor="temporal-lags">Observed lag window</Label>
                      <Input
                        id="temporal-lags"
                        className="mt-2"
                        type="number"
                        min={2}
                        max={128}
                        value={config.lags}
                        onChange={(event) =>
                          change("lags", Number(event.target.value))
                        }
                      />
                    </div>
                    <div>
                      <Label htmlFor="temporal-horizon">Forecast horizon</Label>
                      <Input
                        id="temporal-horizon"
                        className="mt-2"
                        type="number"
                        min={1}
                        max={32}
                        value={config.horizon}
                        onChange={(event) =>
                          change("horizon", Number(event.target.value))
                        }
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                    Temporal artifacts remain candidates until benchmarked and promoted.
                  </div>
                </div>
              )}

              {config.engine === "transformers" && (
                <div className="space-y-4 rounded-2xl border border-border/70 bg-muted/20 p-4">
                  <div>
                    <div className="font-semibold">Local LoRA / PEFT contract</div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      Training uses an already-installed local Hugging Face base model.
                      Karen does not silently download models or infer acceptance of
                      third-party terms.
                    </p>
                  </div>

                  <div>
                    <Label htmlFor="lora-model">Absolute local base-model path</Label>
                    <Input
                      id="lora-model"
                      className="mt-2"
                      value={config.base_model_path}
                      onChange={(event) =>
                        change("base_model_path", event.target.value)
                      }
                      placeholder="/models/base-model"
                    />
                  </div>

                  <div>
                    <Label htmlFor="lora-license">
                      Model license identifier or source reference
                    </Label>
                    <Input
                      id="lora-license"
                      className="mt-2"
                      value={config.license_id}
                      onChange={(event) =>
                        change("license_id", event.target.value)
                      }
                      placeholder="License name or source reference"
                    />
                  </div>

                  <label className="flex items-start gap-3 rounded-xl border border-border/70 bg-background p-3 text-sm">
                    <input
                      className="mt-1"
                      type="checkbox"
                      checked={config.license_accepted}
                      onChange={(event) =>
                        setConfig((previous) =>
                          previous
                            ? {
                                ...previous,
                                license_accepted: event.target.checked,
                                license_model_path: event.target.checked
                                  ? previous.base_model_path
                                  : "",
                              }
                            : previous,
                        )
                      }
                    />
                    <span>
                      I reviewed the model terms from its source and accept them for this
                      exact installed base model. This acknowledgment does not
                      automatically verify the source license.
                    </span>
                  </label>

                  <div className="grid gap-3 sm:grid-cols-3">
                    <div>
                      <Label>Epochs</Label>
                      <Input
                        className="mt-2"
                        type="number"
                        min={1}
                        max={10}
                        value={config.epochs}
                        onChange={(event) =>
                          change("epochs", Number(event.target.value))
                        }
                      />
                    </div>
                    <div>
                      <Label>Token length</Label>
                      <Input
                        className="mt-2"
                        type="number"
                        min={32}
                        max={2048}
                        value={config.sequence_length}
                        onChange={(event) =>
                          change("sequence_length", Number(event.target.value))
                        }
                      />
                    </div>
                    <div>
                      <Label>LoRA rank</Label>
                      <Select
                        value={String(config.lora_rank)}
                        onValueChange={(value) =>
                          change("lora_rank", Number(value))
                        }
                      >
                        <SelectTrigger className="mt-2">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {[4, 8, 16, 32].map((rank) => (
                            <SelectItem key={rank} value={String(rank)}>
                              {rank}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={config.allow_cpu_training}
                      onChange={(event) =>
                        change("allow_cpu_training", event.target.checked)
                      }
                    />
                    Permit CPU training when CUDA is unavailable
                  </label>
                </div>
              )}

              {selectedEngine && !selectedEngine.supported && (
                <Alert>
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Executor unavailable</AlertTitle>
                  <AlertDescription>
                    {selectedEngine.details} Backend validation rejects unsupported
                    launches.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader className="border-b border-border/60">
              <CardTitle className="flex items-center gap-2 text-base">
                <SlidersHorizontal className="h-4 w-4 text-primary" />
                Optimizer &amp; Reproducibility
              </CardTitle>
              <CardDescription>
                Only controls supported by the selected executor are editable.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5 pt-6">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="training-seed">Deterministic seed</Label>
                  <Input
                    id="training-seed"
                    className="mt-2"
                    type="number"
                    min="0"
                    value={config.seed}
                    onChange={(event) => change("seed", Number(event.target.value))}
                  />
                </div>
                <div>
                  <Label htmlFor="max-iterations">Max iterations / steps</Label>
                  <Input
                    id="max-iterations"
                    className="mt-2"
                    type="number"
                    min="1"
                    max="10000"
                    value={config.max_iter}
                    onChange={(event) =>
                      change("max_iter", Number(event.target.value))
                    }
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <div className="rounded-xl border border-border/70 p-3">
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                    Optimizer
                  </div>
                  <div className="mt-2 text-sm font-medium">
                    {config.optimizer || "Backend default"}
                  </div>
                </div>
                <div className="rounded-xl border border-border/70 p-3">
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                    Precision
                  </div>
                  <div className="mt-2 text-sm font-medium">
                    {config.precision || "Backend default"}
                  </div>
                </div>
                <div className="rounded-xl border border-border/70 p-3">
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                    Class weight
                  </div>
                  <div className="mt-2 text-sm font-medium">
                    {title(config.class_weight || "none")}
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <Label>Class weighting</Label>
                <Select
                  value={config.class_weight}
                  onValueChange={(value) => change("class_weight", value)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="balanced">Balanced</SelectItem>
                    <SelectItem value="none">None</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6 xl:col-span-5">
          <Card className="border-border/70 xl:sticky xl:top-20">
            <CardHeader className="border-b border-border/60 bg-gradient-to-br from-primary/5 via-background to-background">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Gauge className="h-4 w-4 text-primary" />
                    Preflight &amp; Execution Gate
                  </CardTitle>
                  <CardDescription className="mt-1">
                    Backend validation decides whether this exact configuration can run.
                  </CardDescription>
                </div>
                <Badge variant={preflight?.ready ? "secondary" : "outline"}>
                  {preflight
                    ? preflight.ready
                      ? "Ready to queue"
                      : "Blocked"
                    : "Not validated"}
                </Badge>
              </div>
            </CardHeader>

            <CardContent className="space-y-5 pt-6">
              <div>
                <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
                  <span>Readiness</span>
                  <span>{preflight ? readinessValue + "%" : "Pending"}</span>
                </div>
                <Progress value={readinessValue} />
              </div>

              <Button
                className="w-full"
                onClick={() => void validate()}
                disabled={busy || !config.dataset_version}
              >
                {busy ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Running preflight
                  </>
                ) : (
                  <>
                    <ShieldCheck className="mr-2 h-4 w-4" />
                    Run backend preflight
                  </>
                )}
              </Button>

              {error && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              {preflight && (
                <>
                  <div
                    className={
                      "rounded-xl border p-4 " +
                      (preflight.ready
                        ? "border-emerald-500/30 bg-emerald-500/5"
                        : "border-amber-500/30 bg-amber-500/5")
                    }
                  >
                    <div className="flex items-center gap-2">
                      {preflight.ready ? (
                        <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                      ) : (
                        <AlertTriangle className="h-5 w-5 text-amber-500" />
                      )}
                      <strong>
                        {preflight.ready ? "Preflight passed" : "Preflight blocked"}
                      </strong>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Dataset {preflight.evidence.dataset_version || config.dataset_version}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                      <div className="text-lg font-semibold">
                        {preflight.evidence.examples_scanned}
                      </div>
                      <div className="text-xs text-muted-foreground">samples scanned</div>
                    </div>

                    {typeof preflight.evidence.feature_count === "number" && (
                      <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                        <div className="text-lg font-semibold">
                          {preflight.evidence.feature_count}
                        </div>
                        <div className="text-xs text-muted-foreground">features</div>
                      </div>
                    )}

                    {typeof preflight.evidence.holdout_windows === "number" && (
                      <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                        <div className="text-lg font-semibold">
                          {preflight.evidence.holdout_windows}
                        </div>
                        <div className="text-xs text-muted-foreground">holdout windows</div>
                      </div>
                    )}

                    {preflight.evidence.class_counts && (
                      <div className="col-span-2 rounded-xl border border-border/70 bg-muted/20 p-3">
                        <div className="text-xs font-medium">Class support</div>
                        <div className="mt-1 text-xs leading-5 text-muted-foreground">
                          {Object.entries(preflight.evidence.class_counts)
                            .map(([name, count]) => name + " (" + count + ")")
                            .join(", ") || "Not available"}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="space-y-2">
                    {preflight.checks.map((item) => (
                      <div
                        key={item.code}
                        className="flex items-start gap-3 rounded-xl border border-border/70 p-3"
                      >
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                        <div>
                          <div className="text-sm font-medium">{title(item.code)}</div>
                          <p className="mt-1 text-xs leading-5 text-muted-foreground">
                            {item.message}
                          </p>
                        </div>
                      </div>
                    ))}

                    {preflight.warnings.map((item) => (
                      <div
                        key={item.code}
                        className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-3"
                      >
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                        <div>
                          <div className="text-sm font-medium">{title(item.code)}</div>
                          <p className="mt-1 text-xs leading-5 text-muted-foreground">
                            {item.message}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>

                  {preflight.ready && (
                    <Button
                      className="w-full"
                      variant="secondary"
                      disabled={queueing}
                      onClick={() => void queueJob()}
                    >
                      {queueing ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Submitting approved job
                        </>
                      ) : (
                        <>
                          <Activity className="mr-2 h-4 w-4" />
                          Queue approved training job
                        </>
                      )}
                    </Button>
                  )}
                </>
              )}

              {queueMessage && (
                <Alert>
                  <CheckCircle2 className="h-4 w-4" />
                  <AlertTitle>Submission persisted</AlertTitle>
                  <AlertDescription>{queueMessage}</AlertDescription>
                </Alert>
              )}

              <Alert>
                <ShieldCheck className="h-4 w-4" />
                <AlertTitle>Execution remains governed</AlertTitle>
                <AlertDescription>
                  Preflight proves eligibility, not completion. Worker leases, queue
                  state, failures, and finished artifacts stay authoritative on the
                  backend.
                </AlertDescription>
              </Alert>
            </CardContent>
          </Card>
        </div>
      </div>

      <Card className="overflow-hidden border-border/70">
        <CardHeader className="border-b border-border/60">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Activity className="h-4 w-4 text-primary" />
                Active Job Pipeline &amp; Execution Queue
              </CardTitle>
              <CardDescription className="mt-1">
                Persisted backend state only. No client-generated progress or synthetic
                worker activity.
              </CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => void loadJobs()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh jobs
            </Button>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          {executionStatus && (
            <div className="grid gap-px border-b border-border/60 bg-border/60 sm:grid-cols-4">
              <div className="bg-card p-4">
                <div className="text-xs text-muted-foreground">Worker status</div>
                <div className="mt-1 font-medium">{executionStatus.worker_status}</div>
              </div>
              <div className="bg-card p-4">
                <div className="text-xs text-muted-foreground">Queued</div>
                <div className="mt-1 font-medium">{executionStatus.queued_jobs}</div>
              </div>
              <div className="bg-card p-4">
                <div className="text-xs text-muted-foreground">Active leases</div>
                <div className="mt-1 font-medium">{executionStatus.active_leases}</div>
              </div>
              <div className="bg-card p-4">
                <div className="text-xs text-muted-foreground">Expired leases</div>
                <div className="mt-1 font-medium">{executionStatus.expired_leases}</div>
              </div>
            </div>
          )}

          {executionStatus && (
            <div className="border-b border-border/60 px-5 py-3 text-xs text-muted-foreground">
              {executionStatus.worker_status_reason}
              {executionStatus.expired_leases > 0
                ? " Operator recovery review is required."
                : ""}
              {!executionStatus.automatic_dispatch_verified
                ? " Automatic dispatch has not been verified."
                : ""}
            </div>
          )}

          {jobs.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">
              No training jobs are reported for this tenant.
            </div>
          ) : (
            <div className="divide-y divide-border/60">
              {jobs.map((job) => (
                <div
                  key={job.job_id}
                  className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)_auto] sm:items-center"
                >
                  <div>
                    <div className="font-mono text-sm font-semibold">{job.job_id}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Submitted {formatTimestamp(job.submitted_at)}
                    </div>
                  </div>

                  <div>
                    <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                      Last backend update
                    </div>
                    <div className="mt-1 text-sm">{formatTimestamp(job.updated_at)}</div>
                  </div>

                  <Badge variant="outline" className={jobStateClass(job.state)}>
                    {title(job.state)}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
