"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
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
  policy: { id: string; version: string };
  level: string;
  progress_index: number;
  average_quality: number;
  evidence_count: number;
  completed_outcome_count: number;
  observed_outcome_count: number;
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
  { key: "completion", label: "Completion", detail: "Completed, meaningful outcomes", icon: CheckCircle2 },
  { key: "durability", label: "Durability", detail: "Persisted results and conversation state", icon: ShieldCheck },
  { key: "verification", label: "Verification", detail: "Verified tool, schema or plugin evidence", icon: Target },
  { key: "efficiency", label: "Efficiency", detail: "Useful work without unnecessary runtime drag", icon: Gauge },
  { key: "resilience", label: "Resilience", detail: "Execution without avoidable fallback pressure", icon: Activity },
  { key: "user_feedback", label: "Feedback", detail: "Explicit feedback tied to completed work", icon: Sparkles },
] as const;

const clampPercent = (value: number | undefined): number =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.min(100, value))
    : 0;

const formatNumber = (value: number | undefined, decimals = 0): string =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : "Unavailable";

const formatTimestamp = (value: string): string => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
};

function SectionHeading({
  eyebrow,
  title,
  description,
  aside,
}: {
  eyebrow: string;
  title: string;
  description: string;
  aside?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 px-4 py-4 sm:px-5">
      <div className="min-w-0">
        <p className="karen-metric uppercase tracking-[0.13em]">{eyebrow}</p>
        <h3 className="mt-1 text-[15px] font-bold tracking-tight text-foreground">{title}</h3>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted-foreground">{description}</p>
      </div>
      {aside}
    </div>
  );
}

function Stat({
  label,
  value,
  description,
  icon: Icon,
}: {
  label: string;
  value: ReactNode;
  description: string;
  icon: LucideIcon;
}) {
  return (
    <div className="karen-growth-stat min-w-0 p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <span className="karen-metric uppercase tracking-[0.10em]">{label}</span>
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="mt-4 break-words text-2xl font-bold tracking-tight text-foreground sm:text-[28px]">
        {value}
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{description}</p>
    </div>
  );
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
      if (
        !response ||
        !response.policy ||
        !Array.isArray(response.milestones) ||
        !Array.isArray(response.recent_evidence) ||
        !response.dimensions ||
        !response.dimension_coverage
      ) {
        throw new Error("The Growth service returned an incomplete evidence record.");
      }
      setProgress(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Growth progress is unavailable.");
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

  const refresh = (
    <Button
      type="button"
      size="sm"
      variant="outline"
      className="h-9 gap-2 rounded-lg border-border/80 bg-card/70 text-xs font-semibold"
      onClick={() => void loadProgress()}
      disabled={isLoading}
      aria-label={isLoading ? "Refreshing Growth evidence" : "Refresh Growth evidence"}
    >
      <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} aria-hidden="true" />
      {isLoading ? "Refreshing" : "Refresh evidence"}
    </Button>
  );

  if (isLoading && !progress) {
    return (
      <section className="karen-growth karen-surface flex min-h-[380px] flex-col items-center justify-center rounded-xl p-8 text-center" role="status" aria-live="polite">
        <Loader2 className="h-6 w-6 animate-spin text-primary" aria-hidden="true" />
        <h2 className="karen-page-title mt-4">Reading Growth evidence</h2>
        <p className="mt-2 text-sm text-muted-foreground">Loading durable, verified outcomes from the runtime.</p>
      </section>
    );
  }

  if (!progress) {
    return (
      <section className="karen-growth karen-surface rounded-xl p-6" role="alert">
        <p className="karen-metric uppercase tracking-wider">Evidence unavailable</p>
        <h2 className="karen-page-title mt-2">Growth cannot be verified</h2>
        <p className="mt-3 max-w-xl text-sm text-muted-foreground">
          KAREN could not read the durable outcome evidence. No fallback score has been invented.
        </p>
        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
        <div className="mt-5">{refresh}</div>
      </section>
    );
  }

  return (
    <main className="karen-growth space-y-4 pb-8 text-foreground" aria-labelledby="growth-title">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border/70 pb-4">
        <div className="min-w-0">
          <p className="karen-metric flex items-center gap-2 uppercase tracking-[0.15em]">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
            KARI OS / PERSONAL INTELLIGENCE
          </p>
          <h2 id="growth-title" className="karen-page-title mt-2 flex items-center gap-2.5">
            <Trophy className="h-6 w-6 text-primary" aria-hidden="true" />
            Growth
          </h2>
          <p className="karen-page-description mt-2">
            Progress comes from completed, durable, verified work. Message volume and daily logins
            do not earn progress, and this score never changes permissions, routing, or memory consent.
          </p>
        </div>
        {refresh}
      </header>

      {error && (
        <div role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-muted-foreground">
          Latest refresh failed. Showing the last received snapshot, not live progress: {error}
        </div>
      )}

      <section className="karen-growth-hero karen-surface overflow-hidden rounded-xl" aria-label="Evidence-backed Growth overview">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="karen-growth-hero-main relative border-b border-border/70 p-5 sm:p-7 lg:border-b-0 lg:border-r">
            <div className="relative z-10">
              <div className="flex flex-wrap items-center gap-2">
                <span className="karen-metric uppercase tracking-[0.15em]">CURRENT PROGRESSION</span>
                <Badge variant="outline" className="border-primary/30 bg-primary/10 text-[10px] text-primary">
                  Policy verified projection
                </Badge>
              </div>
              <p className="mt-5 text-[34px] font-extrabold leading-none tracking-tight sm:text-[42px]">
                {progress.level}
              </p>
              <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="karen-metric uppercase">PROGRESS INDEX</p>
                  <p className="mt-1 font-mono text-3xl font-semibold tabular-nums text-primary sm:text-4xl">
                    {formatNumber(progress.progress_index, 1)}
                    <span className="ml-1 text-sm font-normal text-muted-foreground">/ 100</span>
                  </p>
                </div>
                <span className="karen-metric">Measured from recorded work</span>
              </div>
              <Progress
                value={clampPercent(progress.progress_index)}
                className="mt-3 h-[5px] bg-muted/70"
                aria-label="Growth progress index"
              />
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                The index reflects eligible outcome evidence, not activity frequency.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 divide-x divide-y divide-border/70 [&>*:nth-child(-n+2)]:border-t-0">
            <Stat
              label="Quality"
              value={<span className="font-mono tabular-nums text-accent">{formatNumber(progress.average_quality, 1)}</span>}
              description="Confidence-weighted outcome quality"
              icon={Target}
            />
            <Stat
              label="Completed"
              value={<span className="font-mono tabular-nums">{formatNumber(progress.completed_outcome_count)}</span>}
              description={`Of ${formatNumber(progress.observed_outcome_count)} observed attempts`}
              icon={CheckCircle2}
            />
            <Stat
              label="Quality run"
              value={<span className="font-mono tabular-nums">{formatNumber(progress.quality_run)}</span>}
              description="Consecutive strong outcomes"
              icon={Activity}
            />
            <Stat
              label="Milestones"
              value={<span className="font-mono tabular-nums">{unlockedMilestones}<span className="text-base text-muted-foreground"> / {progress.milestones.length}</span></span>}
              description="Unlocked through durable evidence"
              icon={Trophy}
            />
          </div>
        </div>
      </section>

      <section className="karen-surface overflow-hidden rounded-xl" aria-labelledby="growth-dimensions">
        <SectionHeading
          eyebrow="SIGNAL QUALITY / SIX DIMENSIONS"
          title="Evidence quality"
          description="Measured dimension scores and the percentage of recorded work containing each signal."
          aside={<Badge variant="secondary" className="font-mono text-[11px]">{formatNumber(progress.evidence_count)} evidence records</Badge>}
        />
        <div className="grid gap-px bg-border/70 sm:grid-cols-2 xl:grid-cols-3">
          {DIMENSIONS.map(({ key, label, detail, icon: Icon }) => {
            const score = progress.dimensions[key];
            const coverage = progress.dimension_coverage[key] ?? 0;
            const hasEvidence = typeof score === "number" && Number.isFinite(score) && coverage > 0;
            return (
              <div key={key} className="bg-card/95 p-4 sm:p-5">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                    {label}
                  </span>
                  <span className={`font-mono text-sm font-semibold tabular-nums ${hasEvidence ? "text-accent" : "text-muted-foreground"}`}>
                    {hasEvidence ? `${formatNumber(score, 0)}%` : "No data"}
                  </span>
                </div>
                <p className="mt-2 min-h-8 text-xs leading-relaxed text-muted-foreground">{detail}</p>
                <div className="mt-3 flex justify-between gap-2 font-mono text-[11px] text-muted-foreground">
                  <span>Evidence coverage</span>
                  <span className="tabular-nums">{formatNumber(coverage, 0)}%</span>
                </div>
                <Progress
                  className="mt-2 h-[5px] bg-muted/70"
                  value={clampPercent(coverage)}
                  aria-label={`${label} evidence coverage`}
                />
              </div>
            );
          })}
        </div>
      </section>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.85fr)]">
        <section className="karen-surface min-w-0 overflow-hidden rounded-xl" aria-labelledby="growth-milestones">
          <SectionHeading
            eyebrow="RECORDED ACHIEVEMENTS"
            title="Milestones"
            description="Only completed and recorded evidence can unlock a milestone."
            aside={<span className="karen-metric tabular-nums">{unlockedMilestones} / {progress.milestones.length} UNLOCKED</span>}
          />
          <div className="divide-y divide-border/70">
            {progress.milestones.length === 0 ? (
              <p className="p-5 text-sm text-muted-foreground">No milestones are available from the current policy.</p>
            ) : (
              progress.milestones.map((milestone) => {
                const threshold = Math.max(0, milestone.threshold);
                const amount = Math.max(0, milestone.evidence_count);
                const fraction = threshold > 0 ? clampPercent((amount / threshold) * 100) : 0;
                return (
                  <div key={milestone.id} className="flex gap-3 p-4 sm:p-5">
                    <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${milestone.unlocked ? "border-primary/35 bg-primary/10 text-primary" : "border-border bg-muted/50 text-muted-foreground"}`}>
                      {milestone.unlocked ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : <LockKeyhole className="h-4 w-4" aria-hidden="true" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <h4 className="text-[13px] font-semibold">{milestone.title}</h4>
                        <span className={`font-mono text-[11px] ${milestone.unlocked ? "text-primary" : "text-muted-foreground"}`}>
                          {milestone.unlocked ? "VERIFIED · UNLOCKED" : `${Math.min(amount, threshold)} / ${threshold}`}
                        </span>
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{milestone.description}</p>
                      <Progress value={fraction} className="mt-3 h-[5px] bg-muted/70" aria-label={`${milestone.title} milestone progress`} />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>

        <section className="karen-surface min-w-0 overflow-hidden rounded-xl" aria-labelledby="growth-evidence">
          <SectionHeading
            eyebrow="PROVENANCE / RECENT OUTCOMES"
            title="Evidence ledger"
            description="The recorded outcomes behind this projection."
            aside={<ArrowUpRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />}
          />
          {progress.recent_evidence.length === 0 ? (
            <div className="p-7 text-center">
              <Clock3 className="mx-auto h-6 w-6 text-muted-foreground" aria-hidden="true" />
              <h4 className="mt-3 text-sm font-semibold">No completed outcome evidence yet</h4>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                Failed or incomplete attempts remain observable, but do not earn progress.
              </p>
            </div>
          ) : (
            <ol className="divide-y divide-border/70">
              {progress.recent_evidence.map((item) => (
                <li key={item.trajectory_id} className="p-4 sm:px-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-lg font-semibold tabular-nums text-accent">{formatNumber(item.score, 1)}
                        <span className="ml-2 text-xs font-normal text-muted-foreground">quality</span>
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">{formatTimestamp(item.recorded_at)}</p>
                    </div>
                    <Badge variant="outline" className="font-mono text-[11px]">
                      {formatNumber(clampPercent(item.confidence * 100))}% confidence
                    </Badge>
                  </div>
                  {item.reason_codes.includes("user_feedback_unavailable") && (
                    <p className="mt-2 text-xs text-muted-foreground">Explicit feedback is unavailable for this outcome.</p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <footer className="karen-surface flex flex-wrap items-center justify-between gap-3 rounded-lg px-4 py-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <ShieldCheck className="h-4 w-4 text-primary" aria-hidden="true" />
          Informational projection only. No permissions, routing, or memory-consent changes.
        </div>
        <p className="karen-metric break-all">
          POLICY {progress.policy.id}:{progress.policy.version} · SNAPSHOT {formatTimestamp(progress.generated_at)}
        </p>
      </footer>
    </main>
  );
}
