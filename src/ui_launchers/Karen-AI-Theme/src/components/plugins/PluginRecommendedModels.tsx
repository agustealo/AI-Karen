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
  download_methods?: Array<"hf_hub" | "direct_https">;
  installed: boolean;
};

type RecommendationResponse = { recommendations: ModelRecommendation[] };
type DownloadPolicy = {
  master_enabled: boolean;
  block_new_downloads: boolean;
  require_license_acceptance: boolean;
};
type DownloadChannel = { id: string; effective_enabled: boolean };
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
  download_method?: "hf_hub" | "direct_https";
  // This comes from the canonical owned SQL projection, never raw worker errors.
  failure_category?: "source_access" | "network" | "storage" | "integrity" | "cancelled" | "unknown" | null;
  requested_by?: string | null;
};
type DownloadReceipt = { job_id: string; status: string; download_method: "hf_hub" | "direct_https" };
type OwnedJobsResponse = { jobs: DownloadJob[]; scope: "authenticated_user" };

const IMMUTABLE_REVISION = /^[a-f0-9]{40,64}$/i;
const ACTIVE = new Set(["queued", "running", "promoting", "paused", "pause_requested"]);
const JOB_ID = /^mdl-[a-f0-9-]{36}$/i;

function normalizedProgress(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(100, Math.max(0, numeric > 1 ? numeric : numeric * 100));
}

/** Only the owner-scoped server category may choose an operator action. */
function downloadFailureGuidance(job: DownloadJob): string {
  switch (job.failure_category) {
    case "source_access":
      return "The model source denied access. For gated models, verify upstream approval. For public models, inspect worker connectivity and source credentials in Models & Runtime before retrying.";
    case "network":
      return "The model worker could not reach or verify its source. Check backend network, proxy, TLS and source availability before retrying.";
    case "storage":
      return "The model worker reported a storage limit. Check available model storage and worker quota before retrying.";
    case "integrity":
      return "Model revision or artifact integrity could not be verified. Do not use the partial download; inspect Models & Runtime before retrying.";
    case "cancelled":
      return "The download was cancelled. Start a new download only after checking the reason in Models & Runtime.";
    default:
      return "Check the authenticated job details in Models & Runtime before retrying. A failed download is never a ready model.";
  }
}

type DownloadRequestStage = "validation" | "queue";

/** Map only stable backend status and policy contract values to safe guidance. */
function downloadRequestGuidance(
  error: unknown,
  stage: DownloadRequestStage,
): string {
  const fallback = "Karen could not verify or queue the selected model. Check the authenticated model job and backend status in Models & Runtime before retrying.";
  if (error && typeof error === "object") {
    const response = error as {
      status?: unknown;
      blocking_reasons?: unknown;
    };
    // A validation response's reasons are backend policy truth, but are not
    // automatically safe for UI. Match known phrases; never render raw text.
    if (stage === "validation" && Array.isArray(response.blocking_reasons)) {
      const reasons = response.blocking_reasons.filter(
        (reason): reason is string => typeof reason === "string",
      );
      if (reasons.some((reason) =>
        reason.startsWith("Model access metadata could not be verified") ||
        reason.startsWith("License acceptance is required")
      )) {
        return "Karen could not verify the model license or source access. Confirm the Hugging Face account has accepted the gated terms and the backend worker has authorized access. No job was queued.";
      }
      if (reasons.some((reason) =>
        reason.startsWith("New downloads are blocked by policy") ||
        reason.startsWith("Master downloads switch is off") ||
        (reason.startsWith("Channel ") && reason.endsWith(" is disabled by policy"))
      )) {
        return "Karen's model-download policy or plugin_audio channel blocked this request. Ask an administrator to review Models & Runtime. No job was queued.";
      }
    }
    switch (response.status) {
      case 401:
        return "Your authenticated Karen session is unavailable. Sign in again before requesting a model download.";
      case 403:
        return "Karen denied permission for this model download. Confirm your administrator and tenant permissions in Models & Runtime; a Hugging Face token does not grant Karen permissions.";
      case 409:
        return "Karen rejected a conflicting model download request. Inspect the existing authenticated jobs in Models & Runtime before retrying.";
      case 429:
        return "The model-download service is rate-limited. Review its status in Models & Runtime before retrying.";
      case 502:
      case 503:
      case 504:
        return "Karen's backend model-download service is unavailable. Check its connectivity and worker health in Models & Runtime.";
    }
  }
  return fallback;
}

/**
 * A verified public model uses one explicit Install click. Gated or unknown
 * sources retain fresh per-revision checkbox consent.
 */
function licenseAcknowledged(
  item: ModelRecommendation,
  accepted: Record<string, boolean>,
): boolean {
  const revision = item.resolved_revision;
  if (!item.license || !item.license_url || !revision ||
      !IMMUTABLE_REVISION.test(revision)) return false;
  return item.gated === false ||
    accepted[item.id + ":" + revision] === true;
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
  const [downloadMethods, setDownloadMethods] = useState<Record<string, "hf_hub" | "direct_https">>({});
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
        apiClient.get<OwnedJobsResponse>("/api/runtime/model-library/my-downloads?limit=200"),
      ]);
      if (generation !== epoch.current) return;
      if (!Array.isArray(recommended.recommendations) ||
          !recommended.recommendations.every(isModelRecommendation) ||
          !nextPolicy || typeof nextPolicy.master_enabled !== "boolean" ||
          typeof nextPolicy.block_new_downloads !== "boolean" ||
          !Array.isArray(channelResponse.channels) ||
          nextJobs?.scope !== "authenticated_user" || !Array.isArray(nextJobs.jobs)) {
        throw new Error("model_setup_contract_invalid");
      }
      const eligible = recommended.recommendations.filter((item) =>
        item.app_consumers.includes(pluginId),
      );
      setItems(eligible);
      setPolicy(nextPolicy);
      setChannels(channelResponse.channels);
      setJobs(nextJobs.jobs);
      // An owned active job must remain tracked after navigation or a reload.
      // Match only the current plugin's backend-verified immutable revision.
      const resumed = nextJobs.jobs.find((job) =>
        JOB_ID.test(job.job_id) &&
        ACTIVE.has(job.status) &&
        eligible.some((item) =>
          item.model_id === job.model_id &&
          item.channel_id === job.channel_id &&
          item.resolved_revision === job.revision &&
          typeof item.resolved_revision === "string" &&
          IMMUTABLE_REVISION.test(item.resolved_revision),
        ),
      ) ?? null;
      setTrackedJob((current) => {
        if (!current) return resumed;
        const latest = nextJobs.jobs.find((job) => job.job_id === current.job_id);
        return latest &&
          latest.model_id === current.model_id &&
          latest.revision === current.revision &&
          latest.channel_id === current.channel_id ? latest : resumed;
      });
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

  // Poll one verified owned active job, including across navigation and reloads.
  useEffect(() => {
    if (!trackedJob || !ACTIVE.has(trackedJob.status)) return;
    let cancelled = false;
    const handle = window.setTimeout(() => {
      void apiClient.get<DownloadJob>(
        `/api/runtime/model-library/my-downloads/${encodeURIComponent(trackedJob.job_id)}`,
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
        // Keep the locally cached job list consistent with the verified owner
        // receipt. Otherwise a stale "queued" row keeps retry blocked forever.
        setJobs((current) => current.map((job) =>
          job.job_id === updated.job_id ? updated : job,
        ));
        if (updated.status === "completed") {
          setNotice("Model download completed. Refresh Voice Studio to verify that the runtime can load it.");
        } else if (updated.status === "failed" || updated.status === "cancelled") {
          setNotice(null);
          // Failed/cancelled attempts never carry a reusable license grant.
          // The operator must actively review and accept the current revision.
          setAccepted({});
          setProblem(`Model download did not complete. ${downloadFailureGuidance(updated)}`);
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
    const downloadMethod = downloadMethods[item.id] || "hf_hub";
    if (!(item.download_methods || ["hf_hub"]).includes(downloadMethod)) return;
    const alreadyRunning = jobs.some((job) =>
      job.model_id === item.model_id && job.revision === revision &&
      job.channel_id === item.channel_id && ACTIVE.has(job.status));
    if (submitting.current || !canManage || state !== "ready" || !policy ||
        !policy.master_enabled || policy.block_new_downloads ||
        !channel?.effective_enabled ||
        item.installed || alreadyRunning ||
        item.metadata_verified !== true || item.verification_state !== "verified" ||
        !revision || !IMMUTABLE_REVISION.test(revision) ||
        !licenseAcknowledged(item, accepted)) return;

    submitting.current = true;
    setBusyId(item.id);
    setProblem(null);
    setNotice(null);
    let stage: DownloadRequestStage = "validation";
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
        if (!validation.allowed) {
          throw validation;
        }
        throw new Error("model_setup_validation_denied");
      }

      stage = "queue";
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
          download_method: downloadMethod,
        },
      );
      if (!JOB_ID.test(receipt.job_id) || !ACTIVE.has(receipt.status) ||
          receipt.download_method !== downloadMethod) {
        throw new Error("model_setup_queue_unverified");
      }
      setTrackedJob({
        job_id: receipt.job_id,
        model_id: item.model_id,
        revision,
        channel_id: item.channel_id,
        status: receipt.status,
        download_method: receipt.download_method,
        progress: 0,
      });
      setJobs((current) => [{
        job_id: receipt.job_id,
        model_id: item.model_id,
        revision,
        channel_id: item.channel_id,
        status: receipt.status,
        download_method: receipt.download_method,
        progress: 0,
      }, ...current]);
      setNotice(`Karen confirmed the ${item.label} download job is ${receipt.status}.`);
    } catch (error) {
      // Never echo untrusted HTTP error details or worker exceptions. A failed
      // attempt cannot carry license acknowledgment into the next request.
      setAccepted({});
      setProblem(downloadRequestGuidance(error, stage));
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
          trackedJob.revision === revision &&
          trackedJob.channel_id === item.channel_id &&
          ACTIVE.has(trackedJob.status)
            ? trackedJob
            : jobs.find((job) => job.model_id === item.model_id &&
              job.revision === revision && job.channel_id === item.channel_id &&
              ACTIVE.has(job.status));
        const lastFailedJob = jobs.find((job) =>
          job.model_id === item.model_id &&
          job.revision === revision &&
          job.channel_id === item.channel_id &&
          (job.status === "failed" || job.status === "cancelled"),
        );
        const verified = item.metadata_verified === true &&
          item.verification_state === "verified" &&
          typeof revision === "string" && IMMUTABLE_REVISION.test(revision);
        const blocked = !policy?.master_enabled || policy.block_new_downloads ||
          !channel?.effective_enabled;
        const acceptanceKey = `${item.id}:${revision || "unverified"}`;
        const availableMethods: Array<"hf_hub" | "direct_https"> =
          item.download_methods?.filter((value) =>
            value === "hf_hub" || value === "direct_https",
          ) ?? ["hf_hub"];
        const selectedMethod = downloadMethods[item.id] || "hf_hub";
        const canQueue = !item.installed && !activeJob && !blocked && verified &&
          availableMethods.includes(selectedMethod) &&
          licenseAcknowledged(item, accepted) && busyId === null;
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
                Download job: {activeJob.status} via {activeJob.download_method === "direct_https"
                  ? "Direct HTTPS" : "Hugging Face Hub"}. {normalizedProgress(activeJob.progress).toFixed(1)}% reported.
                Completion alone does not establish TTS runtime readiness.
              </div>
            ) : (
              <>
                {!verified && (
                  <p role="alert" className="text-xs text-destructive">
                    {item.verification_error ||
                      "Source revision or access terms could not be verified. Refresh when the model source is reachable."}
                  </p>
                )}
                {lastFailedJob && (
                  <p role="status" className="text-xs text-destructive"
                    data-testid="plugin-last-download-failure">
                    Previous attempt: {lastFailedJob.status}. {downloadFailureGuidance(lastFailedJob)}
                    {" "}{item.gated === false
                      ? "A new request will reverify the public model source."
                      : "A new attempt requires fresh explicit model-license acceptance."}
                  </p>
                )}
                {blocked && (
                  <p role="status" className="text-xs text-muted-foreground">
                    Download blocked by backend policy or a disabled channel.
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
                    {item.gated === false ? (
                      <p className="text-xs text-muted-foreground" data-testid="public-model-one-click">
                        Public model, no Hugging Face account or token needed.
                        Selecting Download acknowledges the displayed {item.license}{" "}
                        terms for this verified revision. Attribution still applies.
                      </p>
                    ) : (
                      <label className="flex items-start gap-2 text-xs">
                        <Checkbox checked={Boolean(accepted[acceptanceKey])}
                          onCheckedChange={(value) => setAccepted((old) => ({
                            ...old, [acceptanceKey]: value === true,
                          }))} disabled={!item.license_url} />
                        <span>I reviewed and accept the model license and any gated-access conditions
                          for revision {revision?.slice(0, 12)}.</span>
                      </label>
                    )}
                  </div>
                )}
                {verified && !blocked && availableMethods.length > 1 && (
                  <details className="rounded-md border px-2 py-2">
                    <summary className="cursor-pointer text-xs font-medium">
                      Advanced download options
                    </summary>
                    <label className="mt-2 block space-y-1 text-xs">
                      <span className="font-medium">Download method</span>
                    <select aria-label="Download method"
                      className="w-full rounded-md border bg-background px-2 py-2"
                      value={selectedMethod}
                      disabled={busyId !== null}
                      onChange={(event) => {
                        const next = event.target.value;
                        if (next === "hf_hub" || next === "direct_https") {
                          if (availableMethods.includes(next)) {
                            setDownloadMethods((old) => ({ ...old, [item.id]: next }));
                          }
                        }
                      }}>
                      {availableMethods.includes("hf_hub") && (
                        <option value="hf_hub">Hugging Face Hub (SDK)</option>
                      )}
                      {availableMethods.includes("direct_https") && (
                        <option value="direct_https">Direct HTTPS (no Hub SDK for transfer)</option>
                      )}
                    </select>
                    <span className="block text-muted-foreground">
                      Both methods require the same reviewed license, backend authentication,
                      model revision, audited download worker and installation checks.
                    </span>
                    </label>
                  </details>
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
