"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  BadgeCheck,
  BrainCircuit,
  Database,
  GitBranch,
  Archive,
  FileCheck2,
  Fingerprint,
  Layers3,
  Loader2,
  RadioTower,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { apiClient, ApiError } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
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
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import IntelligenceTrainingControlPlane from "./IntelligenceTrainingControlPlane";
import AdvancedTrainingWorkbench from "./AdvancedTrainingWorkbench";

type DatasetRecord = {
  dataset_id: string;
  name: string;
  description?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  created_by?: string | null;
  format?: string | null;
  size?: number | null;
  quality_score?: number | null;
  tags?: string[];
  provenance?: Record<string, unknown>;
};

type DatasetListResponse = {
  datasets: DatasetRecord[];
  total: number;
};

type CuratedDatasetResponse = {
  dataset_id: string;
  version_id: string;
  example_count: number;
  quality_score?: number | null;
  message?: string | null;
};

type TrainingSource = {
  title: string;
  description: string;
  stat: string;
  icon: typeof BrainCircuit;
  tone: string;
};

type GuidanceLane = {
  label: string;
  description: string;
  status: string;
};

type CuratedDatasetForm = {
  datasetName: string;
  datasetDescription: string;
  datasetTags: string;
  minConfidence: string;
  maxExamples: string;
};

const DEFAULT_FORM: CuratedDatasetForm = {
  datasetName: "Curated Memory Training Pack",
  datasetDescription:
    "Curated from approved autonomous-learning outputs, validated interaction summaries, and governed memory signals.",
  datasetTags: "curated-memory,training,approved",
  minConfidence: "0.7",
  maxExamples: "250",
};

const TRAINING_SOURCES: TrainingSource[] = [
  {
    title: "Stable Preferences",
    description:
      "Recurring user preferences that have stayed consistent across sessions and contexts.",
    stat: "Governed source",
    icon: BrainCircuit,
    tone: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
  },
  {
    title: "Validated Outcomes",
    description:
      "Task completions with verified success signals and explicit operator approval.",
    stat: "Approved signal",
    icon: BadgeCheck,
    tone: "bg-sky-500/10 text-sky-600 dark:text-sky-300",
  },
  {
    title: "Reasoning Patterns",
    description:
      "Successful multi-step chains worth distilling into reusable behavior scaffolds.",
    stat: "Curated motif lane",
    icon: GitBranch,
    tone: "bg-amber-500/10 text-amber-600 dark:text-amber-300",
  },
  {
    title: "EchoCore Telemetry",
    description:
      "Structured metadata from telemetry, training interfaces, and curated memory snapshots.",
    stat: "Metadata gated",
    icon: RadioTower,
    tone: "bg-violet-500/10 text-violet-600 dark:text-violet-300",
  },
];

const GOVERNANCE_LANES: GuidanceLane[] = [
  {
    label: "High-quality interaction summaries",
    description:
      "Conversation summaries must be explicit, useful, non-sensitive unless approved, and linked to provenance.",
    status: "Quality gate",
  },
  {
    label: "Curated memory snapshots",
    description:
      "Memory-derived examples must come from governed memory layers and respect deletion/RBAC policy.",
    status: "Memory gate",
  },
  {
    label: "Approved feedback loops",
    description:
      "User/operator feedback must be traced to outcome evidence instead of raw thumbs-up noise.",
    status: "Approval gate",
  },
  {
    label: "Structured metadata ingestion",
    description:
      "Metadata must include source, confidence, timestamp, tenant/user boundary, and audit context.",
    status: "Provenance gate",
  },
];

const formatErrorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "This session is not authenticated. Sign in before using training controls.";
    }

    if (error.status === 403) {
      return "This session is not authorized to use training controls.";
    }

    return error.message || fallback;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return fallback;
};

const formatDateTime = (value: string | null | undefined): string => {
  if (!value) {
    return "Not recorded";
  }

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
};

const formatQualityScore = (value: number | null | undefined): string => {
  if (!Number.isFinite(value ?? NaN)) {
    return "unscored";
  }

  const normalized = Number(value);
  const percent = normalized <= 1 ? normalized * 100 : normalized;

  return `${Math.max(0, Math.min(100, percent)).toFixed(0)}%`;
};

const formatRecordCount = (value: number | null | undefined): string => {
  if (!Number.isFinite(value ?? NaN)) {
    return "unknown";
  }

  return Number(value).toLocaleString();
};

const parseTags = (value: string): string[] => {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    ),
  );
};

const validateCuratedForm = (form: CuratedDatasetForm): string | null => {
  const name = form.datasetName.trim();
  const description = form.datasetDescription.trim();
  const tags = parseTags(form.datasetTags);
  const confidence = Number.parseFloat(form.minConfidence);
  const maxExamples = Number.parseInt(form.maxExamples, 10);

  if (!name) {
    return "Dataset name is required.";
  }

  if (name.length < 3) {
    return "Dataset name must be at least 3 characters.";
  }

  if (!description) {
    return "Dataset description is required.";
  }

  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
    return "Minimum confidence must be a number between 0 and 1.";
  }

  if (!Number.isInteger(maxExamples) || maxExamples < 1 || maxExamples > 10_000) {
    return "Maximum examples must be an integer between 1 and 10000.";
  }

  if (tags.length === 0) {
    return "At least one dataset tag is required.";
  }

  return null;
};

export default function TrainingSettingsPanel() {
  const { toast } = useToast();

  const [datasets, setDatasets] = useState<DatasetRecord[]>([]);
  const [isLoadingDatasets, setIsLoadingDatasets] = useState(true);
  const [datasetLoadError, setDatasetLoadError] = useState<string | null>(null);
  const [isCreatingCurated, setIsCreatingCurated] = useState(false);

  const [datasetAuthRequired, setDatasetAuthRequired] = useState(false);
  const [datasetAccessDenied, setDatasetAccessDenied] = useState(false);
  const [curatedIngestAuthRequired, setCuratedIngestAuthRequired] = useState(false);
  const [curatedIngestAccessDenied, setCuratedIngestAccessDenied] = useState(false);
  const [curatedIngestError, setCuratedIngestError] = useState<string | null>(null);

  const [form, setForm] = useState<CuratedDatasetForm>(DEFAULT_FORM);

  const formError = useMemo(() => validateCuratedForm(form), [form]);

  const curatedDatasetCount = useMemo(() => {
    return datasets.filter((dataset) =>
      Array.isArray(dataset.tags) && dataset.tags.includes("curated-memory"),
    ).length;
  }, [datasets]);

  const averageQuality = useMemo(() => {
    const scoredDatasets = datasets.filter((dataset) =>
      Number.isFinite(dataset.quality_score ?? NaN),
    );

    if (scoredDatasets.length === 0) {
      return null;
    }

    const average =
      scoredDatasets.reduce((total, item) => total + Number(item.quality_score), 0) /
      scoredDatasets.length;

    return average <= 1 ? average * 100 : average;
  }, [datasets]);

  const totalRecords = useMemo(() => {
    return datasets.reduce((total, dataset) => {
      return total + (Number.isFinite(dataset.size ?? NaN) ? Number(dataset.size) : 0);
    }, 0);
  }, [datasets]);

  const loadDatasets = useCallback(async () => {
    setIsLoadingDatasets(true);
    setDatasetLoadError(null);
    setDatasetAuthRequired(false);
    setDatasetAccessDenied(false);

    try {
      const response = await apiClient.get<DatasetListResponse>(
        "/api/training-data/datasets",
      );

      setDatasets(Array.isArray(response.datasets) ? response.datasets : []);
    } catch (error) {
      setDatasets([]);

      if (error instanceof ApiError && error.status === 401) {
        setDatasetAuthRequired(true);
        setDatasetAccessDenied(false);
        return;
      }

      if (error instanceof ApiError && error.status === 403) {
        setDatasetAuthRequired(false);
        setDatasetAccessDenied(true);
        return;
      }

      const message = formatErrorMessage(
        error,
        "Karen could not load the current training dataset inventory.",
      );

      setDatasetLoadError(message);

      toast({
        title: "Unable to load training datasets",
        description: message,
        variant: "destructive",
      });
    } finally {
      setIsLoadingDatasets(false);
    }
  }, [toast]);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  const updateForm = useCallback((key: keyof CuratedDatasetForm, value: string) => {
    setForm((current) => ({
      ...current,
      [key]: value,
    }));
  }, []);

  const handleCreateCuratedDataset = useCallback(async () => {
    if (formError) {
      toast({
        title: "Curated dataset form needs attention",
        description: formError,
        variant: "destructive",
      });
      return;
    }

    setIsCreatingCurated(true);
    setCuratedIngestAuthRequired(false);
    setCuratedIngestAccessDenied(false);
    setCuratedIngestError(null);

    try {
      const response = await apiClient.post<CuratedDatasetResponse>(
        "/api/training-data/datasets/from-curated-memory",
        {
          name: form.datasetName.trim(),
          description: form.datasetDescription.trim(),
          min_confidence: Number.parseFloat(form.minConfidence),
          max_examples: Number.parseInt(form.maxExamples, 10),
          tags: parseTags(form.datasetTags),
        },
      );

      toast({
        title: "Curated dataset created",
        description: `${response.example_count.toLocaleString()} examples staged in ${response.dataset_id}.`,
      });

      await loadDatasets();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setCuratedIngestAuthRequired(true);
        setCuratedIngestAccessDenied(false);

        toast({
          title: "Sign in required",
          description:
            "This session must be authenticated before it can create curated training datasets.",
          variant: "destructive",
        });
        return;
      }

      if (error instanceof ApiError && error.status === 403) {
        setCuratedIngestAuthRequired(false);
        setCuratedIngestAccessDenied(true);

        toast({
          title: "Training access restricted",
          description:
            "This account does not have permission to create curated training datasets.",
          variant: "destructive",
        });
        return;
      }

      const message = formatErrorMessage(
        error,
        "Karen could not build a dataset from curated memory outputs.",
      );

      setCuratedIngestError(message);

      toast({
        title: "Curated dataset creation failed",
        description: message,
        variant: "destructive",
      });
    } finally {
      setIsCreatingCurated(false);
    }
  }, [form, formError, loadDatasets, toast]);

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden border-border/70">
        <CardHeader className="relative overflow-hidden bg-gradient-to-br from-primary/10 via-background to-background">
          <div className="absolute inset-y-0 right-0 w-40 bg-gradient-to-l from-primary/10 to-transparent" />

          <div className="relative flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="border-primary/30 bg-primary/5 text-primary">
                  Admin Training
                </Badge>
                <Badge variant="secondary">Service-backed</Badge>
              </div>

              <div>
                <CardTitle className="text-2xl tracking-tight">
                  Training Control Plane
                </CardTitle>
                <CardDescription className="mt-2 max-w-2xl text-sm leading-6">
                  Operate Karen&apos;s learning system across adaptive memory, user modeling, outcome evidence,
                  continual ML, affect, forecasting, evaluation, and governed promotion while keeping
                  runtime authority, provenance, RBAC, and deletion boundaries intact.
                </CardDescription>
              </div>
            </div>

            <div className="relative grid min-w-[240px] gap-3 rounded-xl border border-border/70 bg-background/80 p-4 shadow-sm backdrop-blur">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Dataset inventory</span>
                <span className="font-medium">{datasets.length}</span>
              </div>

              <div className="h-px bg-border/70" />

              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div className="rounded-lg bg-muted/60 p-2">
                  <div className="font-medium text-foreground">{datasets.length}</div>
                  dataset records
                </div>

                <div className="rounded-lg bg-muted/60 p-2">
                  <div className="font-medium text-foreground">{curatedDatasetCount}</div>
                  curated packs
                </div>

                <div className="rounded-lg bg-muted/60 p-2">
                  <div className="font-medium text-foreground">
                    {formatRecordCount(totalRecords)}
                  </div>
                  total records
                </div>

                <div className="rounded-lg bg-muted/60 p-2">
                  <div className="font-medium text-foreground">
                    {averageQuality == null ? "unscored" : `${averageQuality.toFixed(0)}%`}
                  </div>
                  avg quality
                </div>
              </div>
            </div>
          </div>
        </CardHeader>
      </Card>

      <Tabs defaultValue="intelligence" className="w-full">
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 rounded-xl border border-border/70 bg-muted/30 p-1.5">\n          <TabsTrigger value="intelligence" className="rounded-lg px-4 py-2">Learning Overview</TabsTrigger>\n          <TabsTrigger value="advanced" className="rounded-lg px-4 py-2">Train a Model</TabsTrigger>\n          <TabsTrigger value="management" className="rounded-lg px-4 py-2">Data &amp; Governance</TabsTrigger>\n        </TabsList>

        <TabsContent value="advanced" className="mt-6 space-y-3">
          <p className="text-sm text-muted-foreground">
            Configure any executor currently reported as supported by Karen&apos;s training catalog.\n            Preflight, worker availability, persisted queue state, license acknowledgments, and\n            execution eligibility remain service-backed rather than simulated in the browser.
          </p>
          <AdvancedTrainingWorkbench />
        </TabsContent>

        <TabsContent value="intelligence" className="mt-6 space-y-3">
          <p className="text-sm text-muted-foreground">
            Memory adaptation and model-weight retraining are separate. This view reports backend
            learning capabilities; it does not mean autonomous retraining is enabled.
          </p>
          <IntelligenceTrainingControlPlane />
        </TabsContent>

        <TabsContent value="management" className="mt-6 space-y-6">
          <section className="overflow-hidden rounded-2xl border border-border/70 bg-card">
            <div className="flex flex-col gap-4 border-b border-border/70 bg-gradient-to-br from-primary/10 via-background to-background p-6 lg:flex-row lg:items-start lg:justify-between">
              <div className="max-w-3xl">
                <div className="mb-3 flex flex-wrap gap-2">
                  <Badge variant="outline" className="border-primary/30 bg-primary/5 text-primary">Governed datasets</Badge>
                  <Badge variant="outline">Tenant scoped</Badge>
                  <Badge variant="outline">Provenance aware</Badge>
                </div>
                <h3 className="flex items-center gap-3 text-2xl font-semibold tracking-tight">
                  <ShieldCheck className="h-6 w-6 text-primary" />Data &amp; Governance
                </h3>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  Inspect versioned training data, prepare curated memory, and review learning-policy boundaries.
                  The backend remains the authority for ingestion, permissions and provenance.
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => void loadDatasets()} disabled={isLoadingDatasets}>
                {isLoadingDatasets ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                Refresh inventory
              </Button>
            </div>
            <div className="grid gap-px bg-border/60 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { label: "Datasets", value: datasets.length.toLocaleString(), icon: Database },
                { label: "Curated packs", value: curatedDatasetCount.toLocaleString(), icon: Archive },
                { label: "Reported records", value: formatRecordCount(totalRecords), icon: Layers3 },
                { label: "Average quality", value: averageQuality == null ? "Unscored" : averageQuality.toFixed(0) + "%", icon: FileCheck2 },
              ].map(metric => {
                const Icon = metric.icon;
                return <div key={metric.label} className="bg-card p-5">
                  <div className="flex items-center justify-between text-xs uppercase tracking-[0.12em] text-muted-foreground">
                    <span>{metric.label}</span><Icon className="h-4 w-4 text-primary" />
                  </div>
                  <div className="mt-3 text-2xl font-semibold tabular-nums">
                    {isLoadingDatasets || datasetLoadError || datasetAuthRequired || datasetAccessDenied ? "Unavailable" : metric.value}
                  </div>
                </div>;
              })}
            </div>
          </section>
          <Tabs defaultValue="datasets" className="w-full">
            <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 rounded-xl border border-border/70 bg-muted/30 p-1.5">
              <TabsTrigger value="datasets" className="rounded-lg px-4 py-2">Dataset Inventory</TabsTrigger>
              <TabsTrigger value="curation" className="rounded-lg px-4 py-2">Curated Ingest</TabsTrigger>
              <TabsTrigger value="overview" className="rounded-lg px-4 py-2">Governance Policy</TabsTrigger>
            </TabsList>
        <TabsContent value="overview" className="mt-6 space-y-6">\n          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Fingerprint className="h-4 w-4 text-primary" /> Governance reference: backend services enforce permissions, source integrity and approval.</div>
          <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
            {TRAINING_SOURCES.map((source) => {
              const Icon = source.icon;

              return (
                <Card key={source.title} className="border-border/70">
                  <CardHeader className="space-y-4">
                    <div
                      className={`flex h-11 w-11 items-center justify-center rounded-2xl ${source.tone}`}
                    >
                      <Icon className="h-5 w-5" />
                    </div>

                    <div>
                      <CardTitle className="text-base">{source.title}</CardTitle>
                      <CardDescription className="mt-2 text-sm leading-6">
                        {source.description}
                      </CardDescription>
                    </div>
                  </CardHeader>

                  <CardContent className="pt-0">
                    <Badge variant="outline">{source.stat}</Badge>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          <div className="grid gap-6 xl:grid-cols-[1.25fr_0.85fr]">
            <Card className="border-border/70">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Layers3 className="h-5 w-5 text-primary" />
                  Curation Governance Lanes
                </CardTitle>
                <CardDescription>
                  Training candidates should be promoted only after quality,
                  traceability, and governance checks are satisfied by backend services.
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-5">
                {GOVERNANCE_LANES.map((lane) => (
                  <div key={lane.label} className="rounded-xl border border-border/70 p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <div className="font-medium">{lane.label}</div>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {lane.description}
                        </p>
                      </div>

                      <Badge variant="outline">{lane.status}</Badge>
                    </div>
                  </div>
                ))}

                <Separator />

                <div className="grid gap-3 md:grid-cols-3">
                  <div className="rounded-xl border border-border/70 bg-muted/30 p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                      Stage 1
                    </div>
                    <div className="mt-2 font-medium">Collect</div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      EchoCore, approved feedback, and memory-derived metadata.
                    </p>
                  </div>

                  <div className="rounded-xl border border-border/70 bg-muted/30 p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                      Stage 2
                    </div>
                    <div className="mt-2 font-medium">Curate</div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Promote only validated summaries, patterns, and stable preferences.
                    </p>
                  </div>

                  <div className="rounded-xl border border-border/70 bg-muted/30 p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                      Stage 3
                    </div>
                    <div className="mt-2 font-medium">Approve</div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Create dataset versions with provenance for later training execution.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/70">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <ShieldCheck className="h-5 w-5 text-primary" />
                  Governance
                </CardTitle>
                <CardDescription>
                  Documented governance controls. This view does not assert that each enforcement check has passed.
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-4">
                <div className="flex items-center justify-between gap-4 rounded-xl border border-border/70 p-4">
                  <div>
                    <div className="font-medium">Require admin approval</div>
                    <div className="text-sm text-muted-foreground">
                      Dataset creation stays behind authenticated admin APIs.
                    </div>
                  </div>
                  <Badge variant="outline" className="shrink-0">Policy reference</Badge>
                </div>

                <div className="flex items-center justify-between gap-4 rounded-xl border border-border/70 p-4">
                  <div>
                    <div className="font-medium">Curated-memory only ingest</div>
                    <div className="text-sm text-muted-foreground">
                      Training packs can be built from autonomous-learning curation.
                    </div>
                  </div>
                  <Badge variant="outline" className="shrink-0">Policy reference</Badge>
                </div>

                <div className="flex items-center justify-between gap-4 rounded-xl border border-border/70 p-4">
                  <div>
                    <div className="font-medium">Audit-backed dataset events</div>
                    <div className="text-sm text-muted-foreground">
                      Uploads and curated pack generation are emitted through the backend logger.
                    </div>
                  </div>
                  <Badge variant="outline" className="shrink-0">Policy reference</Badge>
                </div>

                <Alert>
                  <ShieldCheck className="h-4 w-4" />
                  <AlertTitle className="text-xs">Backend ownership</AlertTitle>
                  <AlertDescription className="text-[10px]">
                    These are policy descriptions, not browser-managed controls. RBAC, audit,
                    provenance, tenant isolation, and training eligibility must be enforced by
                    backend services.
                  </AlertDescription>
                </Alert>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="datasets" className="mt-6">
          <Card className="border-border/70">
            <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Database className="h-5 w-5 text-primary" />
                  Training Dataset Inventory
                </CardTitle>
                <CardDescription>
                  Backend-derived dataset state from the training-data service, including
                  curated-memory packs and manual datasets.
                </CardDescription>
              </div>

              <Button
                variant="outline"
                onClick={() => void loadDatasets()}
                disabled={isLoadingDatasets}
              >
                {isLoadingDatasets ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                Refresh
              </Button>
            </CardHeader>

            <CardContent className="space-y-3">
              {datasetAuthRequired && (
                <Alert className="border-primary/20 bg-primary/5">
                  <ShieldCheck className="h-4 w-4 !text-primary" />
                  <AlertTitle>Sign In Required</AlertTitle>
                  <AlertDescription>
                    The training dataset service is live, but this session is not
                    authenticated. Sign in to inspect dataset inventory.
                  </AlertDescription>
                </Alert>
              )}

              {datasetAccessDenied && (
                <Alert className="border-primary/20 bg-primary/5">
                  <ShieldCheck className="h-4 w-4 !text-primary" />
                  <AlertTitle>Dataset Access Restricted</AlertTitle>
                  <AlertDescription>
                    The training dataset service is live, but this account does not have
                    permission to read dataset inventory.
                  </AlertDescription>
                </Alert>
              )}

              {datasetLoadError && (
                <Alert className="border-yellow-500/30 bg-yellow-500/5">
                  <AlertCircle className="h-4 w-4 !text-yellow-600" />
                  <AlertTitle>Dataset Inventory Unavailable</AlertTitle>
                  <AlertDescription>{datasetLoadError}</AlertDescription>
                </Alert>
              )}

              {isLoadingDatasets ? (
                <div className="flex items-center gap-2 rounded-xl border border-border/70 p-4 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading training datasets from Karen&apos;s backend service.
                </div>
              ) : datasetAuthRequired ? (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  Dataset inventory requires an authenticated session.
                </div>
              ) : datasetAccessDenied ? (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  Dataset inventory is restricted by backend permissions.
                </div>
              ) : datasets.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  No datasets are currently registered.
                </div>
              ) : (
                datasets.map((dataset) => (
                  <div
                    key={dataset.dataset_id}
                    className="rounded-xl border border-border/70 p-4"
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="space-y-1">
                        <div className="font-medium">{dataset.name}</div>

                        <div className="text-sm text-muted-foreground">
                          {dataset.description || "No description provided."}
                        </div>

                        <div className="flex flex-wrap gap-2 pt-2">
                          <Badge variant="outline">{dataset.format || "unknown format"}</Badge>
                          <Badge variant="secondary">
                            quality {formatQualityScore(dataset.quality_score)}
                          </Badge>

                          {dataset.tags?.slice(0, 4).map((tag) => (
                            <Badge key={tag} variant="outline">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      </div>

                      <div className="grid gap-1 text-sm text-muted-foreground lg:text-right">
                        <div className="flex items-center gap-1 lg:justify-end"><Fingerprint className="h-3 w-3" /> ID {dataset.dataset_id}</div>
                        <div>created {formatDateTime(dataset.created_at)}</div>
                        <div>updated {formatDateTime(dataset.updated_at)}</div>
                        <div>records {formatRecordCount(dataset.size)}</div>\n                        {dataset.provenance && Object.keys(dataset.provenance).length > 0 && <div>Provenance metadata recorded</div>}
                        {dataset.created_by && <div>owner {dataset.created_by}</div>}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="curation" className="mt-6">
          <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
            <Card className="border-border/70">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Sparkles className="h-5 w-5 text-primary" />
                  Build Dataset From Curated Memory
                </CardTitle>
                <CardDescription>
                  This uses the governed autonomous-learning path instead of raw session
                  debris. Karen curates conversation metadata, builds training examples, and
                  then stages a dataset version.
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-4">
                {curatedIngestAuthRequired && (
                  <Alert className="border-primary/20 bg-primary/5">
                    <ShieldCheck className="h-4 w-4 !text-primary" />
                    <AlertTitle>Sign In Required</AlertTitle>
                    <AlertDescription>
                      Curated dataset creation requires an authenticated session before RBAC can
                      be evaluated.
                    </AlertDescription>
                  </Alert>
                )}

                {curatedIngestAccessDenied && (
                  <Alert className="border-primary/20 bg-primary/5">
                    <ShieldCheck className="h-4 w-4 !text-primary" />
                    <AlertTitle>Curated Ingest Restricted</AlertTitle>
                    <AlertDescription>
                      Curated dataset creation is governed by backend RBAC. This session can view
                      the panel but cannot create training packs.
                    </AlertDescription>
                  </Alert>
                )}

                {curatedIngestError && (
                  <Alert className="border-yellow-500/30 bg-yellow-500/5">
                    <AlertCircle className="h-4 w-4 !text-yellow-600" />
                    <AlertTitle>Curated Ingest Failed</AlertTitle>
                    <AlertDescription>{curatedIngestError}</AlertDescription>
                  </Alert>
                )}

                {formError && (
                  <Alert className="border-yellow-500/30 bg-yellow-500/5">
                    <AlertCircle className="h-4 w-4 !text-yellow-600" />
                    <AlertTitle>Form Validation</AlertTitle>
                    <AlertDescription>{formError}</AlertDescription>
                  </Alert>
                )}

                <div className="grid gap-2">
                  <Label htmlFor="dataset-name">Dataset name</Label>
                  <Input
                    id="dataset-name"
                    value={form.datasetName}
                    onChange={(event) => updateForm("datasetName", event.target.value)}
                    disabled={isCreatingCurated}
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="dataset-description">Description</Label>
                  <Input
                    id="dataset-description"
                    value={form.datasetDescription}
                    onChange={(event) =>
                      updateForm("datasetDescription", event.target.value)
                    }
                    disabled={isCreatingCurated}
                  />
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="grid gap-2">
                    <Label htmlFor="min-confidence">Minimum confidence</Label>
                    <Input
                      id="min-confidence"
                      inputMode="decimal"
                      value={form.minConfidence}
                      onChange={(event) => updateForm("minConfidence", event.target.value)}
                      disabled={isCreatingCurated}
                    />
                  </div>

                  <div className="grid gap-2">
                    <Label htmlFor="max-examples">Maximum examples</Label>
                    <Input
                      id="max-examples"
                      inputMode="numeric"
                      value={form.maxExamples}
                      onChange={(event) => updateForm("maxExamples", event.target.value)}
                      disabled={isCreatingCurated}
                    />
                  </div>
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="dataset-tags">Tags</Label>
                  <Input
                    id="dataset-tags"
                    value={form.datasetTags}
                    onChange={(event) => updateForm("datasetTags", event.target.value)}
                    disabled={isCreatingCurated}
                  />
                </div>

                <div className="flex flex-wrap gap-3 pt-2">
                  <Button
                    onClick={() => void handleCreateCuratedDataset()}
                    disabled={isCreatingCurated || !!formError}
                  >
                    {isCreatingCurated ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <BadgeCheck className="mr-2 h-4 w-4" />
                    )}
                    Create Curated Dataset
                  </Button>

                  <Button
                    variant="outline"
                    onClick={() => void loadDatasets()}
                    disabled={isLoadingDatasets}
                  >
                    <RefreshCw className="mr-2 h-4 w-4" />
                    Refresh Inventory
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/70">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Activity className="h-5 w-5 text-primary" />
                  Service Alignment
                </CardTitle>
                <CardDescription>
                  What this admin panel is wired to in the current system.
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <div className="rounded-xl border border-border/70 p-4">
                  <div className="font-medium text-foreground">Dataset inventory</div>
                  <div className="mt-1">
                    Reads <code>/api/training-data/datasets</code> instead of relying
                    on queue state.
                  </div>
                </div>

                <div className="rounded-xl border border-border/70 p-4">
                  <div className="font-medium text-foreground">Curated ingest</div>
                  <div className="mt-1">
                    Uses <code>/api/training-data/datasets/from-curated-memory</code>{" "}
                    so training packs originate from approved autonomous-learning outputs.
                  </div>
                </div>

                <div className="rounded-xl border border-border/70 p-4">
                  <div className="font-medium text-foreground">Governed provenance</div>
                  <div className="mt-1">
                    The backend must stamp provenance and audit events when datasets are
                    created from curated memory.
                  </div>
                </div>

                <Alert>
                  <ShieldCheck className="h-4 w-4" />
                  <AlertTitle className="text-xs">Training safety boundary</AlertTitle>
                  <AlertDescription className="text-[10px]">
                    This panel stages governed datasets. It must not directly fine-tune models,
                    scrape raw memory, bypass consent, or train from unapproved private content.
                  </AlertDescription>
                </Alert>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
          </Tabs>
        </TabsContent>
      </Tabs>
    </div>
  );
}