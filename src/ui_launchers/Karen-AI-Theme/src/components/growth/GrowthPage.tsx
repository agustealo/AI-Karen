"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Gauge,
  Loader2,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  Trophy,
} from "lucide-react";

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
import { apiClient } from "@/lib/api";

interface ProgressMilestone {
  id: string;
  title: string;
  description: string;
  unlocked: boolean;
  evidence_count: number;
  threshold: number;
}

interface RewardEvidence {
  trajectory_id: string;
  score: number;
  confidence: number;
  dimensions: Record<string, number>;
  reason_codes: string[];
  recorded_at: string;
}

interface RewardProgressResponse {
  policy: {
    id: string;
    version: string;
  };
  level: string;
  progress_index: number;
  average_quality: number;
  evidence_count: number;
  quality_run: number;
  dimensions: Record<string, number>;
  dimension_coverage: Record<string, number>;
  milestones: ProgressMilestone[];
  recent_evidence: RewardEvidence[];
  generated_at: string;
  principles: {
    engagement_volume_rewarded: boolean;
    daily_login_streaks_rewarded: boolean;
    rbac_affected: boolean;
    routing_affected: boolean;
    memory_consent_affected: boolean;
  };
}

const DIMENSIONS = [
  {
    key: "completion",
    label: "Completion",
    detail: "Work reached a real completed outcome.",
    icon: CheckCircle2,
  },
  {
    key: "durability",
    label: "Durability",
    detail: "Results and conversation state persisted successfully.",
    icon: ShieldCheck,
  },
  {
    key: "verification",
    label: "Verification",
    detail: "Available tool, schema, or plugin checks supported the result.",
    icon: Target,
  },
  {
    key: "efficiency",
    label: "Efficiency",
    detail: "Useful work completed without unnecessary runtime drag.",
    icon: Gauge,
  },
  {
    key: "resilience",
    label: "Resilience",
    detail: "Execution succeeded without avoidable fallback pressure.",
    icon: Activity,
  },
  {
    key: "user_feedback",
    label: "Feedback",
    detail: "Explicit user feedback is linked to completed work.",
    icon: Sparkles,
  },
] as const;

function clampPercent(value: number | undefined): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value ?? 0));
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

export default function GrowthPage() {
  const [progress, setProgress] = useState<RewardProgressResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProgress = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.get<RewardProgressResponse>("/api/progress/");
      setProgress(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Growth progress is unavailable");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProgress();
  }, [loadProgress]);

  const unlockedMilestones = useMemo(
    () => progress?.milestones.filter((milestone) => milestone.unlocked).length ?? 0,
    [progress],
  );

  if (isLoading && !progress) {
    return (
      <div className="flex min-h-[360px] items-center justify-center">
        <div className="text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary" />
          <p className="mt-3 text-sm text-muted-foreground">
            Reading evidence-backed progress…
          </p>
        </div>
      </div>
    );
  }

  if (error || !progress) {
    return (
      <Card className="border-destructive/20 bg-destructive/5">
        <CardHeader>
          <CardTitle>Growth unavailable</CardTitle>
          <CardDescription>
            KAREN could not read the durable outcome evidence required to calculate
            progress. No fallback score was invented.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive">{error}</p>
          <Button className="mt-4 gap-2" variant="outline" onClick={() => void loadProgress()}>
            <RefreshCw className="h-4 w-4" />
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <Trophy className="h-7 w-7 text-primary" />
            <h2 className="text-3xl font-bold tracking-tight">Growth</h2>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Progress comes from completed, durable, verified work. Message volume and
            daily logins do not earn progress, and this score never changes permissions,
            routing, or memory consent.
          </p>
        </div>
        <Button variant="ghost" size="sm" className="gap-2" onClick={() => void loadProgress()}>
          <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="bg-gradient-to-br from-background to-primary/5">
          <CardHeader className="pb-2">
            <CardDescription>Current level</CardDescription>
            <CardTitle className="text-2xl">{progress.level}</CardTitle>
          </CardHeader>
          <CardContent>
            <Progress value={clampPercent(progress.progress_index)} className="h-2" />
            <p className="mt-2 text-xs text-muted-foreground">
              {progress.progress_index.toFixed(1)} progress index
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Evidence-backed quality</CardDescription>
            <CardTitle className="text-2xl">
              {progress.average_quality.toFixed(1)}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              Confidence-weighted across {progress.evidence_count} completed outcome
              {progress.evidence_count === 1 ? "" : "s"}.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Quality run</CardDescription>
            <CardTitle className="text-2xl">{progress.quality_run}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              Consecutive strong outcomes, not a login streak.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Milestones</CardDescription>
            <CardTitle className="text-2xl">
              {unlockedMilestones} / {progress.milestones.length}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              Unlocked only from recorded evidence.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Quality dimensions</CardTitle>
          <CardDescription>
            Each dimension shows its current evidence score and how much of the recorded
            work actually contains that signal.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {DIMENSIONS.map(({ key, label, detail, icon: Icon }) => {
              const score = progress.dimensions[key];
              const coverage = progress.dimension_coverage[key] ?? 0;
              const hasEvidence = Number.isFinite(score) && coverage > 0;

              return (
                <div key={key} className="rounded-xl border bg-muted/10 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Icon className="h-4 w-4 text-primary" />
                      <p className="font-semibold">{label}</p>
                    </div>
                    <Badge variant={hasEvidence ? "secondary" : "outline"}>
                      {hasEvidence ? `${score.toFixed(0)}%` : "No evidence"}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{detail}</p>
                  <div className="mt-4">
                    <div className="mb-1 flex justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
                      <span>Evidence coverage</span>
                      <span>{coverage.toFixed(0)}%</span>
                    </div>
                    <Progress value={clampPercent(coverage)} className="h-1.5" />
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Milestones</CardTitle>
            <CardDescription>
              Milestones recognize useful capability and reliability, not compulsive
              engagement.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {progress.milestones.map((milestone) => {
              const milestoneProgress =
                milestone.threshold > 0
                  ? clampPercent((milestone.evidence_count / milestone.threshold) * 100)
                  : 0;
              return (
                <div key={milestone.id} className="rounded-xl border p-4">
                  <div className="flex items-start gap-3">
                    {milestone.unlocked ? (
                      <CheckCircle2 className="mt-0.5 h-5 w-5 text-primary" />
                    ) : (
                      <LockKeyhole className="mt-0.5 h-5 w-5 text-muted-foreground" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-semibold">{milestone.title}</p>
                        <Badge variant={milestone.unlocked ? "default" : "outline"}>
                          {milestone.unlocked
                            ? "Unlocked"
                            : `${Math.min(milestone.evidence_count, milestone.threshold)} / ${milestone.threshold}`}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {milestone.description}
                      </p>
                      <Progress value={milestoneProgress} className="mt-3 h-1.5" />
                    </div>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent evidence</CardTitle>
            <CardDescription>
              A compact trail of the outcomes that actually moved the projection.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {progress.recent_evidence.length === 0 ? (
              <div className="rounded-xl border border-dashed p-6 text-center">
                <Trophy className="mx-auto h-7 w-7 text-muted-foreground" />
                <p className="mt-2 text-sm font-medium">No outcome evidence yet</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Complete real work through KAREN and durable evidence will appear here.
                </p>
              </div>
            ) : (
              progress.recent_evidence.map((item) => (
                <div key={item.trajectory_id} className="rounded-xl border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold">{item.score.toFixed(1)} quality</p>
                      <p className="text-[10px] text-muted-foreground">
                        {formatTimestamp(item.recorded_at)}
                      </p>
                    </div>
                    <Badge variant="outline">
                      {Math.round(item.confidence * 100)}% evidence
                    </Badge>
                  </div>
                  {item.reason_codes.includes("user_feedback_unavailable") && (
                    <p className="mt-2 text-[10px] text-muted-foreground">
                      Explicit user feedback is not wired for this outcome yet.
                    </p>
                  )}
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
        Projection policy {progress.policy.id}:{progress.policy.version} · generated{" "}
        {formatTimestamp(progress.generated_at)}
      </p>
    </div>
  );
}
