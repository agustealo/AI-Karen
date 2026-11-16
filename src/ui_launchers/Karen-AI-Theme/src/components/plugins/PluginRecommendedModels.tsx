"use client";

/**
 * Model provisioning within a plugin's host-owned management UI.
 *
 * The recommended artifact, immutable revision, license terms, download
 * policy, jobs, and queue are all resolved by the existing model control
 * plane. This component never downloads files or declares voice readiness.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Download, Loader2, RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

type ModelRecommendation = {
  id: string;
  model_id: string;
  label: string;
  purpose: string;
  channel_id: string;
  revision?: string | null;
  resolved_revision?: string | null;
  metadata_verified?: boolean;
  verification_state?: string;
  verification_error?: string | null;
  license?: string | null;
  license_url?: string | null;
  gated?: boolean;
  include_patterns?: string[] | null;
  app_consumers: string[];
  installed: boolean;
};

type RecommendationResponse = { recommendations: ModelRecommendation[] };
type DownloadPolicy = {
  master_enabled: boolean;
  block_new_downloads: boolean;
  require_license_acceptance: boolean;
};
type DownloadChannel = { id: string; effective_enabled: boolean; admin_only: boolean };
type DownloadChannelsResponse = { channels: DownloadChannel[] };
type DownloadValidation = {
  allowed: boolean;
  model_id: string;
  channel_id: string;
  blocking_reasons: string[];
  metadata: { resolved_revision?: string | null };
};
type DownloadJob = {
  job_id: string;
  model_id: string;
  revision?: string | null;
  channel_id: string;
  status: string;
  progress: number;
  requested_by?: string | null;
};
type DownloadReceipt = { job_id: string; status: string };

const IMMUTABLE_REVISION = /^[a-f0-9]{40,64}$/i;
const ACTIVE = new Set(["queued", "running", "promoting", "paused", "pause_requested"]);
const JOB_ID = /^mdl-[a-f0-9-]{36}$/i;

function normalizedProgress(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(100, Math.max(0, numeric > 1 ? numeric : numeric * 100));
}

function isModelRecommendation(value: unknown): value is ModelRecommendation {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<ModelRecommendation>;
  return typeof item.id === "string" &&
    typeof item.model_id === "string" &&
    /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(item.model_id) &&
    typeof item.label === "string" &&
    typeof item.purpose === "string" &&
    typeof item.channel_id === "string" &&
    typeof item.installed === "boolean" &&
    Array.isArray(item.app_consumers) &&
    item.app_consumers.every((consumer) => typeof consumer === "string") &&
    (item.include_patterns == null ||
      (Array.isArray(item.include_patterns) &&
       item.include_patterns.every((pattern) => typeof pattern === "string")));
}

/** Mount only on explicit plugin-model management, never across the plugin catalog. */
export function PluginRecommendedModels({ pluginId }: { pluginId: string }) {
  const { user, isAdmin } = useAuth();
  const canManage = isAdmin() || user?.roles?.includes("super_admin") === true;
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [items, setItems] = useState<ModelRecommendation[]>([]);
  const [policy, setPolicy] = useState<DownloadPolicy | null>(null);
  const [channels, setChannels] = useState<DownloadChannel[]>([]);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [trackedJob, setTrackedJob] = useState<DownloadJob | null>(null);
  const epoch = useRef(0);
  const submitting = useRef(false);

  const refresh = useCallback(async () => {
    const generation = ++epoch.current;
    setState("loading");
    setProblem(null);
    try {
      const [recommended, nextPolicy, channelResponse, nextJobs] = await Promise.all([
        apiClient.get<RecommendationResponse>("/api/models/download/recommendations"),
        apiClient.get<DownloadPolicy>("/api/models/download/policy"),
        apiClient.get<DownloadChannelsResponse>("/api/models/download/channels"),
        apiClient.get<DownloadJob[]>("/api/models/download/jobs?limit=200"),
      ]);
      if (generation !== epoch.current) return;
      if (!Array.isArray(recommended.recommendations) ||
          !recommended.recommendations.every(isModelRecommendation) ||
          !nextPolicy || typeof nextPolicy.master_enabled !== "boolean" ||
          typeof nextPolicy.block_new_downloads !== "boolean" ||
          !Array.isArray(channelResponse.channels) || !Array.isArray(nextJobs)) {
        throw new Error("model_setup_contract_invalid");
      }
      setItems(recommended.recommendations.filter((item) =>
        item.app_consumers.includes(pluginId),
      ));
      setPolicy(nextPolicy);
      setChannels(channelResponse.channels);
      setJobs(nextJobs);
      // License acceptance must be fresh for the backend-verified revision.
      setAccepted({});
      setState("ready");
    } catch {
      if (generation !== epoch.current) return;
      setItems([]);
      setPolicy(null);
      setChannels([]);
      setJobs([]);
      setState("unavailable");
      setProblem("Karen could not verify recommended models, download policy, or job state. No installation was started.");
    }
  }, [pluginId]);

  useEffect(() => {
    if (canManage) void refresh();
    return () => { epoch.current += 1; };
  }, [canManage, refresh]);

  // Poll only the operator's newly queued job, not all recommendations.
  useEffect(() => {
    if (!trackedJob || !ACTIVE.has(trackedJob.status)) return;
    let cancelled = false;
    const handle = window.setTimeout(() => {
      void apiClient.get<DownloadJob>(
        `/api/models/download/jobs/${encodeURIComponent(trackedJob.job_id)}`,
      ).then((updated) => {
        if (cancelled) return;
        if (updated.job_id !== trackedJob.job_id ||
            updated.model_id !== trackedJob.model_id ||
            updated.channel_id !== trackedJob.channel_id ||
            updated.revision !== trackedJob.revision) {
          setProblem("Download job identity changed; refresh the model download manager.");
          return;
        }
        setTrackedJob(updated);
        if (updated.status === "completed") {
          setNotice("Model download completed. Refresh Voice Studio to verify that the runtime can load it.");
        } else if (updated.status === "failed" || updated.status === "cancelled") {
          setProblem("Model download did not complete. Check Models & Runtime for job details.");
        }
      }).catch(() => {
        if (!cancelled) setProblem("Download progress could not be verified. Check Models & Runtime.");
      });
    }, 4000);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [trackedJob]);

  const install = async (item: ModelRecommendation) => {
    const revision = item.resolved_revision;
    const channel = channels.find((entry) => entry.id === item.channel_id);
    const alreadyRunning = jobs.some((job) =>
      job.model_id === item.model_id && job.revision === revision &&
      job.channel_id === item.channel_id && ACTIVE.has(job.status));
    if (submitting.current || !canManage || state !== "ready" || !policy ||
        !policy.master_enabled || policy.block_new_downloads ||
        !channel?.effective_enabled || !channel.admin_only ||
        item.installed || alreadyRunning ||
        item.metadata_verified !== true || item.verification_state !== "verified" ||
        !revision || !IMMUTABLE_REVISION.test(revision) ||
        accepted[`${item.id}:${revision}`] !== true) return;

    submitting.current = true;
    setBusyId(item.id);
    setProblem(null);
    setNotice(null);
    try {
      // Revalidate pinned upstream terms after the user explicitly accepted
      // them. Never queue a moving branch head or permit remote-code execution.
      const validation = await apiClient.post<DownloadValidation>(
        "/api/models/download/validate", {
          model_id: item.model_id,
          revision,
          channel_id: item.channel_id,
          include_patterns: item.include_patterns ?? [],
          exclude_patterns: [],
          trust_remote_code: false,
          accept_license: true,
        },
      );
      if (!validation.allowed || validation.model_id !== item.model_id ||
          validation.channel_id !== item.channel_id ||
          validation.metadata?.resolved_revision !== revision) {
        throw new Error("model_setup_validation_denied");
      }

      const receipt = await apiClient.post<DownloadReceipt>(
        "/api/models/download", {
          model_id: item.model_id,
          revision: null,
          validated_revision: revision,
          channel_id: item.channel_id,
          include_patterns: item.include_patterns ?? [],
          exclude_patterns: [],
          trust_remote_code: false,
          accept_license: true,
          pin: true,
        },
      );
      if (!JOB_ID.test(receipt.job_id) || !ACTIVE.has(receipt.status)) {
        throw new Error("model_setup_queue_unverified");
      }
      setTrackedJob({
        job_id: receipt.job_id,
        model_id: item.model_id,
        revision,
        channel_id: item.channel_id,
        status: receipt.status,
        progress: 0,
      });
      setJobs((current) => [{
        job_id: receipt.job_id,
        model_id: item.model_id,
        revision,
        channel_id: item.channel_id,
        status: receipt.status,
        progress: 0,
      }, ...current]);
      setNotice(`Karen confirmed the ${item.label} download job is ${receipt.status}.`);
    } catch {
      setProblem("Karen could not verify or queue the selected model. Review its access terms and try again.");
    } finally {
      submitting.current = false;
      setBusyId(null);
    }
  };

  if (!canManage) {
    return (
      <p className="text-sm text-muted-foreground" role="note">
        Model downloads require an administrator. Ask your workspace administrator to install the recommended speech model.
      </p>
    );
  }

  return (
    <section aria-label={`Recommended models for ${pluginId}`}
      className="space-y-3 rounded-xl border bg-muted/20 p-4" data-testid="plugin-recommended-models">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Recommended plugin models</h3>
          <p className="text-xs text-muted-foreground">
            Verified model requirements from Karen&apos;s governed download catalog.
          </p>
        </div>
        <Button type="button" size="sm" variant="outline"
          onClick={() => void refresh()} disabled={state === "loading" || busyId !== null}>
          <RefreshCw className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
          Refresh
        </Button>
      </div>
      {state === "loading" && <p role="status" className="text-sm">
        <Loader2 className="mr-2 inline h-4 w-4 animate-spin" aria-hidden="true" />
        Checking model requirements and installation policy…
      </p>}
      {problem && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Model setup needs attention</AlertTitle>
          <AlertDescription>{problem}</AlertDescription>
        </Alert>
      )}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {state === "ready" && items.length === 0 && (
        <p role="status" className="text-sm text-muted-foreground">
          Karen has no curated downloadable model for this plugin. No model source has been guessed.
        </p>
      )}
      {state === "ready" && items.map((item) => {
        const revision = item.resolved_revision;
        const channel = channels.find((candidate) => candidate.id === item.channel_id);
        const activeJob = trackedJob?.model_id === item.model_id &&
          trackedJob.revision === revision && trackedJob.channel_id === item.channel_id
            ? trackedJob
            : jobs.find((job) => job.model_id === item.model_id &&
              job.revision === revision && job.channel_id === item.channel_id &&
              ACTIVE.has(job.status));
        const verified = item.metadata_verified === true &&
          item.verification_state === "verified" &&
          typeof revision === "string" && IMMUTABLE_REVISION.test(revision);
        const blocked = !policy?.master_enabled || policy.block_new_downloads ||
          !channel?.effective_enabled || !channel.admin_only;
        const acceptanceKey = `${item.id}:${revision || "unverified"}`;
        const canQueue = !item.installed && !activeJob && !blocked && verified &&
          accepted[acceptanceKey] === true && busyId === null;
        return (
          <div key={item.id} className="space-y-3 rounded-lg border bg-background p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h4 className="text-sm font-medium">{item.label}</h4>
                <p className="mt-1 text-xs text-muted-foreground">{item.purpose}</p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">
                {item.installed ? "Artifact registered" :
                  activeJob ? `Job ${activeJob.status}` : "Model missing"}
              </span>
            </div>
            <p className="break-all text-xs text-muted-foreground">
              {item.model_id} · {item.channel_id}
              {verified && <span> · Revision {revision?.slice(0, 12)}</span>}
            </p>
            {item.installed ? (
              <p className="flex gap-2 text-xs text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
                Model files are registered. This does not confirm tenant eligibility,
                a licensed runtime dependency, or a ready voice. Verify in Voice Studio.
              </p>
            ) : activeJob ? (
              <div role="status" className="text-xs">
                Download job: {activeJob.status}. {normalizedProgress(activeJob.progress).toFixed(1)}% reported.
                Completion alone does not establish TTS runtime readiness.
              </div>
            ) : (
              <>
                {!verified && (
                  <p role="alert" className="text-xs text-destructive">
                    Source revision or access terms could not be verified. Refresh when the model source is reachable.
                  </p>
                )}
                {blocked && (
                  <p role="status" className="text-xs text-muted-foreground">
                    Download blocked by backend policy or disabled admin-only channel.
                  </p>
                )}
                {verified && !blocked && (
                  <div className="space-y-2">
                    {item.license_url ? (
                      <a href={item.license_url} target="_blank" rel="noreferrer"
                        className="text-xs font-medium underline underline-offset-2">
                        Review {item.license || "model access"} terms
                      </a>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        No source terms link was returned. Verify the model terms before proceeding.
                      </p>
                    )}
                    <label className="flex items-start gap-2 text-xs">
                      <Checkbox checked={Boolean(accepted[acceptanceKey])}
                        onCheckedChange={(value) => setAccepted((old) => ({
                          ...old, [acceptanceKey]: value === true,
                        }))} disabled={!item.license_url} />
                      <span>I reviewed and accept the model license and any gated-access conditions
                        for revision {revision?.slice(0, 12)}.</span>
                    </label>
                  </div>
                )}
                <Button type="button" size="sm" disabled={!canQueue}
                  onClick={() => void install(item)}>
                  {busyId === item.id ?
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden="true" /> :
                    <Download className="mr-1 h-4 w-4" aria-hidden="true" />}
                  {busyId === item.id ? "Validating & queueing…" : "Download recommended model"}
                </Button>
              </>
            )}
          </div>
        );
      })}
      <p className="text-xs text-muted-foreground">
        Downloads run in Karen&apos;s existing audited model worker. The plugin never receives
        your model-source credentials or downloads weights itself.
      </p>
    </section>
  );
}
