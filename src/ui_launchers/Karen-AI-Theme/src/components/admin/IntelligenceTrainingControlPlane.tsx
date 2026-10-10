"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  Layers3,
  Network,
  Search,
  CircleAlert,
  BrainCircuit,
  ChartNoAxesCombined,
  Gauge,
  HeartPulse,
  History,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  UserRoundCog,
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
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type TrainingLane = {
  lane_id: string;
  title: string;
  category: string;
  authority: string;
  module: string;
  mode: string;
  description: string;
  human_like_role: string;
  prediction_task?: string | null;
  available: boolean;
  model_count: number;
  active_model_count: number;
  shadow_model_count: number;
  candidate_model_count: number;
};

type RegistryModel = {
  model_id: string;
  model_version: string;
  status: string;
  architecture: string;
  feature_version: string;
  training_dataset_version: string;
  metrics: Record<string, unknown>;
  created_at: string;
};

type TrainingControlPlane = {
  architecture: {
    strategy: string;
    fast_path: string;
    slow_path: string;
    weight_updates_are_immediate: boolean;
    memory_is_training_data_source_not_model_weights: boolean;
    llm_direct_forecasting: boolean;
  };
  prediction_tasks: string[];
  lanes: TrainingLane[];
  registry: {
    total_models: number;
    status_counts: Record<string, number>;
    models_by_task: Record<string, RegistryModel[]>;
  };
  governance: {
    promotion_path: string[];
    required_controls: string[];
    personalization_rules: string[];
  };
};

const CATEGORY_META: Record<
  string,
  { label: string; icon: typeof BrainCircuit; description: string }
> = {
  personalization: {
    label: "Personalization",
    icon: UserRoundCog,
    description: "Adapts to an individual without leaking learning across users.",
  },
  memory: {
    label: "Memory",
    icon: History,
    description: "Turns experience into episodic, semantic, and procedural continuity.",
  },
  feedback: {
    label: "Feedback",
    icon: Target,
    description: "Converts verified outcomes and explicit corrections into learning evidence.",
  },
  ml: {
    label: "Model Learning",
    icon: BrainCircuit,
    description: "Trains and calibrates governed predictive models.",
  },
  forecasting: {
    label: "Forecasting",
    icon: ChartNoAxesCombined,
    description: "Anticipates likely needs, patterns, outcomes, and temporal change.",
  },
  affect: {
    label: "Affect",
    icon: HeartPulse,
    description: "Reads transient emotional and sentiment context without treating it as identity.",
  },
  governance: {
    label: "Governance",
    icon: ShieldCheck,
    description: "Prevents weak or unsafe learning from silently becoming active behavior.",
  },
};

const formatError = (error: unknown) => {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Sign in before opening the training control plane.";
    if (error.status === 403) return error.message && error.message !== "Permission denied" ? error.message : "Training requires training:read. Check the account roles and permission claims in the authenticated session.";
    return error.message || "Karen could not load training intelligence.";
  }
  if (error instanceof Error) return error.message;
  return "Karen could not load training intelligence.";
};

const prettify = (value: string) =>
  value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

export default function IntelligenceTrainingControlPlane() {
  const [data, setData] = useState<TrainingControlPlane | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [onlyUnavailable, setOnlyUnavailable] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.get<TrainingControlPlane>(
        "/api/admin/training/control-plane",
      );
      setData(response);
    } catch (loadError) {
      setData(null);
      setError(formatError(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => {
    const groups = new Map<string, TrainingLane[]>();
    for (const lane of data?.lanes ?? []) {
      const items = groups.get(lane.category) ?? [];
      items.push(lane);
      groups.set(lane.category, items);
    }
    return Array.from(groups.entries());
  }, [data?.lanes]);

  const visibleGroups = useMemo(() => grouped.map(([category, lanes]) => [
    category, lanes.filter((lane) => {
      if (onlyUnavailable && lane.available) return false;
      const search = filter.trim().toLowerCase();
      return !search || [lane.title, lane.category, lane.description, lane.authority, lane.mode,
        lane.human_like_role, lane.prediction_task ?? ""].some((value) => value.toLowerCase().includes(search));
    }),
  ] as const).filter(([, lanes]) => lanes.length > 0), [grouped, filter, onlyUnavailable]);

  const availableCount = (data?.lanes ?? []).filter((lane) => lane.available).length;
  const totalLaneCount = data?.lanes.length ?? 0;
  const readiness = totalLaneCount
    ? Math.round((availableCount / totalLaneCount) * 100)
    : 0;
  const activeCount = Object.entries(data?.registry.status_counts ?? {})
    .filter(([status]) => status.toLowerCase() === "active")
    .reduce((total, [, count]) => total + count, 0);
  const shadowCount = Object.entries(data?.registry.status_counts ?? {})
    .filter(([status]) => status.toLowerCase() === "shadow")
    .reduce((total, [, count]) => total + count, 0);

  if (loading) {
    return (
      <Card className="border-border/70">
        <CardContent className="flex min-h-52 items-center justify-center gap-3 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          Loading Karen&apos;s intelligence and learning authorities.
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Alert variant="destructive">
        <Activity className="h-4 w-4" />
        <AlertTitle>Training intelligence unavailable</AlertTitle>
        <AlertDescription className="flex flex-col gap-3">
          <span>{error ?? "No control-plane response was returned."}</span>
          <Button variant="outline" size="sm" className="w-fit" onClick={() => void load()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">

      <section className="overflow-hidden rounded-2xl border border-border/70 bg-card">
        <div className="border-b border-border/70 bg-gradient-to-br from-primary/10 via-background to-background px-5 py-6 sm:px-7">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-3xl">
              <div className="mb-3 flex flex-wrap gap-2">
                <Badge variant="outline" className="border-primary/30 bg-primary/5 text-primary">Learning intelligence</Badge>
                <Badge variant="outline">Memory first</Badge>
                <Badge variant="outline">Governed promotion</Badge>
              </div>
              <h3 className="flex items-center gap-3 text-2xl font-semibold tracking-tight">
                <BrainCircuit className="h-6 w-6 text-primary" />
                Learning Overview
              </h3>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                See how Karen learns through memory, verified outcomes, predictive models,
                and governed evaluation. Availability is reported by the control-plane service,
                not inferred from a healthy page.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              <RefreshCw className="mr-2 h-4 w-4" />Refresh overview
            </Button>
          </div>
        </div>
        <div className="grid gap-px bg-border/60 sm:grid-cols-2 xl:grid-cols-4">
          {[
            { label: "Learning authorities", value: availableCount + " / " + totalLaneCount, detail: "backend-available lanes", icon: Layers3 },
            { label: "Registry artifacts", value: String(data.registry.total_models), detail: "governed model records", icon: BrainCircuit },
            { label: "Active / shadow", value: activeCount + " / " + shadowCount, detail: "model lifecycle states", icon: Network },
            { label: "Prediction tasks", value: String(data.prediction_tasks.length), detail: "registered task contracts", icon: Target },
          ].map((metric) => {
            const Icon = metric.icon;
            return (
              <div key={metric.label} className="bg-card p-5">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.12em] text-muted-foreground">
                  <span>{metric.label}</span><Icon className="h-4 w-4 text-primary" />
                </div>
                <div className="mt-3 text-2xl font-semibold tabular-nums">{metric.value}</div>
                <div className="mt-1 text-xs text-muted-foreground">{metric.detail}</div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[1.35fr_0.65fr]">
        <Card className="overflow-hidden border-border/70">
          <CardHeader className="border-b border-border/60">
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4 text-primary" />Two-speed Adaptation
            </CardTitle>
            <CardDescription>
              Context updates and model-weight promotion are deliberately separate operating paths.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 pt-5 md:grid-cols-2">
            <div className="rounded-xl border border-border/70 bg-muted/20 p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                <History className="h-4 w-4 text-primary" />Fast path: Memory
              </div>
              <p className="text-sm leading-6 text-muted-foreground">{data.architecture.fast_path}</p>
              <Badge variant="outline" className="mt-4">No immediate weight updates</Badge>
            </div>
            <div className="rounded-xl border border-border/70 bg-muted/20 p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                <BrainCircuit className="h-4 w-4 text-primary" />Slow path: Model learning
              </div>
              <p className="text-sm leading-6 text-muted-foreground">{data.architecture.slow_path}</p>
              <Badge variant="outline" className="mt-4">Evidence before activation</Badge>
            </div>
          </CardContent>
        </Card>
        <Card className="border-border/70">
          <CardHeader className="border-b border-border/60">
            <CardTitle className="flex items-center gap-2 text-base">
              <Gauge className="h-4 w-4 text-primary" />Authority Coverage
            </CardTitle>
            <CardDescription>Available learning lanes, not a model-quality score.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-5">
            <div className="flex items-end justify-between gap-3">
              <div className="text-3xl font-semibold tabular-nums">{readiness}%</div>
              <Badge variant={readiness === 100 ? "secondary" : "outline"}>
                {totalLaneCount === 0 ? "No lanes reported" : readiness === 100 ? "All lanes available" : "Partial availability"}
              </Badge>
            </div>
            <Progress value={readiness} />
            <p className="text-xs leading-5 text-muted-foreground">
              {availableCount} of {totalLaneCount} backend learning authorities reported available.
              This does not imply every executor or training worker is healthy.
            </p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="capabilities">
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 rounded-xl border border-border/70 bg-muted/30 p-1.5">
          <TabsTrigger value="capabilities" className="rounded-lg px-4 py-2">Learning Capabilities</TabsTrigger>
          <TabsTrigger value="models" className="rounded-lg px-4 py-2">Model Lifecycle</TabsTrigger>
          <TabsTrigger value="governance" className="rounded-lg px-4 py-2">Learning Policy</TabsTrigger>
        </TabsList>

        <TabsContent value="capabilities" className="mt-6 space-y-6">
          {grouped.map(([category, lanes]) => {
            const meta = CATEGORY_META[category];
            const Icon = meta?.icon ?? BrainCircuit;
            return (
              <Card key={category} className="overflow-hidden border-border/70">
                <CardHeader className="border-b border-border/60 bg-muted/10">
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Icon className="h-5 w-5 text-primary" />
                    {meta?.label ?? prettify(category)}
                  </CardTitle>
                  <CardDescription>{meta?.description ?? "Registered learning authorities."} · {lanes.filter((lane) => lane.available).length}/{lanes.length} available</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-3 pt-5 lg:grid-cols-2">
                  {lanes.map((lane) => (
                    <div key={lane.lane_id} className="rounded-xl border border-border/70 bg-muted/10 p-5 transition-colors hover:border-primary/30">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="font-medium">{lane.title}</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {lane.authority} · {prettify(lane.mode)}
                          </div>
                        </div>
                        <Badge variant={lane.available ? "secondary" : "destructive"}>
                          {lane.available ? "Available" : "Unavailable"}
                        </Badge>
                      </div>
                      <p className="mt-3 text-sm leading-6 text-muted-foreground">
                        {lane.description}
                      </p>
                      <div className="mt-4 flex flex-wrap gap-2 border-t border-border/60 pt-3">
                        <Badge variant="outline">{prettify(lane.human_like_role)}</Badge>
                        {lane.prediction_task && (
                          <Badge variant="outline">{prettify(lane.prediction_task)}</Badge>
                        )}
                        {lane.model_count > 0 && (
                          <Badge variant="outline">
                            {lane.active_model_count} active · {lane.shadow_model_count} shadow ·{" "}
                            {lane.candidate_model_count} candidate
                          </Badge>
                        )}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            );
          })}
        </TabsContent>

        <TabsContent value="models" className="mt-6">
          <Card className="border-border/70">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><ArrowRight className="h-4 w-4 text-primary" />Candidate → Shadow → Active</CardTitle>
              <CardDescription>
                Model artifacts remain governed independently from instant user-memory adaptation.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {Object.entries(data.registry.status_counts).length === 0 && <p className="text-sm text-muted-foreground">No lifecycle counts reported.</p>}\n                {Object.entries(data.registry.status_counts).map(([status, count]) => (
                  <div key={status} className="rounded-xl border border-border/70 p-4">
                    <div className="text-2xl font-semibold">{count}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{prettify(status)}</div>
                  </div>
                ))}
              </div>
              <div className="space-y-3">
                {data.prediction_tasks.map((task) => {
                  const models = data.registry.models_by_task[task] ?? [];
                  return (
                    <div
                      key={task}
                      className="flex flex-col gap-2 rounded-xl border border-border/70 p-4 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div>
                        <div className="font-medium">{prettify(task)}</div>
                        <div className="text-xs text-muted-foreground">
                          {models.length
                            ? models.map((model) => `${model.model_id} v${model.model_version} · ${prettify(model.status)} · ${model.architecture || "unspecified architecture"}`).join(" | ")
                            : "No trained artifact registered yet"}
                        </div>
                      </div>
                      <Badge variant={models.length ? "secondary" : "outline"}>
                        {models.length} artifact{models.length === 1 ? "" : "s"}
                      </Badge>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="governance" className="mt-6 grid gap-6 xl:grid-cols-2">
          <Card className="border-border/70">
            <CardHeader>
              <CardTitle>Promotion safeguards</CardTitle>
              <CardDescription>
                A trained model is evidence, not authority. These controls must remain satisfied.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.governance.required_controls.map((control) => (
                <div key={control} className="flex items-center gap-3 rounded-xl border p-3">
                  <ShieldCheck className="h-4 w-4 text-primary" />
                  <span className="text-sm">{prettify(control)}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="border-border/70">
            <CardHeader>
              <CardTitle>User adaptation policy</CardTitle>
              <CardDescription>
                Personalization stays useful without turning guesses into permanent identity.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.governance.personalization_rules.map((rule) => (
                <div key={rule} className="rounded-xl border border-border/70 p-4 text-sm leading-6">
                  {rule}
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
