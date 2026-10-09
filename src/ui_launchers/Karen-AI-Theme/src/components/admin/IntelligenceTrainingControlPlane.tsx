"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
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
    if (error.status === 403) return "This account does not have training read permission.";
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

  const availableCount = (data?.lanes ?? []).filter((lane) => lane.available).length;
  const totalLaneCount = data?.lanes.length ?? 0;
  const readiness = totalLaneCount
    ? Math.round((availableCount / totalLaneCount) * 100)
    : 0;

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
      <div className="grid gap-4 xl:grid-cols-[1.4fr_0.8fr]">
        <Card className="overflow-hidden border-border/70">
          <CardHeader className="bg-gradient-to-br from-primary/10 via-background to-background">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>Two-speed adaptation</Badge>
              <Badge variant="outline">Memory first</Badge>
              <Badge variant="outline">Shadow before promotion</Badge>
            </div>
            <CardTitle className="mt-3 flex items-center gap-2 text-xl">
              <Sparkles className="h-5 w-5 text-primary" />
              Cognitive Learning Architecture
            </CardTitle>
            <CardDescription className="max-w-3xl leading-6">
              Karen adapts quickly through memory, profiles, reward evidence, and calibration.
              Model weights change slowly through curated training, held-out evaluation, shadow
              comparison, and governed promotion.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 pt-6 md:grid-cols-2">
            <div className="rounded-xl border border-border/70 p-4">
              <div className="mb-2 text-sm font-semibold">Fast path</div>
              <p className="text-sm leading-6 text-muted-foreground">
                {data.architecture.fast_path}
              </p>
            </div>
            <div className="rounded-xl border border-border/70 p-4">
              <div className="mb-2 text-sm font-semibold">Slow path</div>
              <p className="text-sm leading-6 text-muted-foreground">
                {data.architecture.slow_path}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Gauge className="h-5 w-5 text-primary" />
              Learning Readiness
            </CardTitle>
            <CardDescription>Backend authorities available to the control plane.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-end justify-between">
              <div>
                <div className="text-3xl font-semibold">{readiness}%</div>
                <div className="text-xs text-muted-foreground">
                  {availableCount} of {totalLaneCount} learning lanes available
                </div>
              </div>
              <Badge variant={readiness === 100 ? "secondary" : "outline"}>
                {readiness === 100 ? "Authorities online" : "Partial"}
              </Badge>
            </div>
            <Progress value={readiness} />
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-muted/50 p-3">
                <div className="font-semibold">{data.registry.total_models}</div>
                <div className="text-xs text-muted-foreground">registered ML artifacts</div>
              </div>
              <div className="rounded-lg bg-muted/50 p-3">
                <div className="font-semibold">{data.prediction_tasks.length}</div>
                <div className="text-xs text-muted-foreground">governed prediction tasks</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="capabilities">
        <TabsList className="flex h-auto w-full flex-wrap justify-start">
          <TabsTrigger value="capabilities">Capabilities</TabsTrigger>
          <TabsTrigger value="models">Model Lifecycle</TabsTrigger>
          <TabsTrigger value="governance">Learning Policy</TabsTrigger>
        </TabsList>

        <TabsContent value="capabilities" className="mt-6 space-y-6">
          {grouped.map(([category, lanes]) => {
            const meta = CATEGORY_META[category] ?? CATEGORY_META.ml;
            const Icon = meta.icon;
            return (
              <Card key={category} className="border-border/70">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-lg">
                    <Icon className="h-5 w-5 text-primary" />
                    {meta.label}
                  </CardTitle>
                  <CardDescription>{meta.description}</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-4 lg:grid-cols-2">
                  {lanes.map((lane) => (
                    <div key={lane.lane_id} className="rounded-xl border border-border/70 p-4">
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
                      <div className="mt-4 flex flex-wrap gap-2">
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
              <CardTitle>Candidate → Shadow → Active</CardTitle>
              <CardDescription>
                Model artifacts remain governed independently from instant user-memory adaptation.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-3 md:grid-cols-4">
                {Object.entries(data.registry.status_counts).map(([status, count]) => (
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
                            ? models.map((model) => `${model.model_id} · ${model.status}`).join(" | ")
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
