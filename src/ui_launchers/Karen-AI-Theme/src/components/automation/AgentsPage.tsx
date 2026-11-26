"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Users,
  CircleStop,
  RefreshCw,
  ShieldCheck,
  Search,
} from "lucide-react";

import useAuth from "@/lib/useAuth";
import { apiClient } from "@/lib/api";
import { isAgentCatalogResponse, type AgentCatalogResponse } from "./agentCatalog";
import { useRuntimeApprovals } from "@/components/approvals/useRuntimeApprovals";
export { isRuntimeApproval, type RuntimeApproval } from "@/components/approvals/useRuntimeApprovals";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export interface AgentRunRecord {
  run_id: string;
  correlation_id?: string | null;
  request_id?: string | null;
  session_id?: string | null;
  policy_decision_id?: string | null;
  tenant_id?: string | null;
  user_id?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  created_at?: string | null;
  cancel_requested_at?: string | null;
  outcome_status?: string | null;
  error_type?: string | null;
  cancellable?: boolean;
  durable?: boolean;
  response_source?: string | null;
  distributed_control?: {
    supported?: boolean;
    [key: string]: unknown;
  } | null;
}

export interface AgentRunsResponse {
  runs: AgentRunRecord[];
  total: number;
  generated_at: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonemptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function isAgentRunRecord(value: unknown): value is AgentRunRecord {
  return isObject(value) && nonemptyString(value.run_id) && nonemptyString(value.status)
    && ["correlation_id", "request_id", "session_id", "policy_decision_id", "tenant_id", "user_id", "started_at", "completed_at", "created_at", "cancel_requested_at", "outcome_status", "error_type", "response_source"].every((key) => value[key] == null || typeof value[key] === "string")
    && ["cancellable", "durable"].every((key) => value[key] === undefined || typeof value[key] === "boolean")
    && (value.distributed_control == null || (isObject(value.distributed_control) && (value.distributed_control.supported === undefined || typeof value.distributed_control.supported === "boolean")));
}

export function isAgentRunsResponse(value: unknown): value is AgentRunsResponse {
  return isObject(value) && Array.isArray(value.runs) && value.runs.every(isAgentRunRecord)
    && value.total === value.runs.length && new Set(value.runs.map((run) => run.run_id)).size === value.runs.length
    && nonemptyString(value.generated_at) && Number.isFinite(Date.parse(value.generated_at));
}

const transitionStatuses = ["created", "running", "cancellation_requested", "completed", "failed", "cancelled", "orphaned"] as const;
const transitionSources = {
  runtime: "Runtime",
  admin_cancel: "Administrative cancellation",
  redis_reconciliation: "Reconciled from shared execution state",
  migration_backfill: "Migration backfill (not an observed live event)",
} as const;

interface RunTransition {
  transition_id: string;
  from_status: typeof transitionStatuses[number] | null;
  to_status: typeof transitionStatuses[number];
  event_at: string;
  source: keyof typeof transitionSources;
}

interface RunTransitionsResponse {
  run_id: string;
  transitions: RunTransition[];
  truncated: boolean;
  response_source: "postgres_durable_run_ledger";
}

function isTransitionStatus(value: unknown): value is RunTransition["to_status"] {
  return typeof value === "string" && (transitionStatuses as readonly string[]).includes(value);
}

export function isRunTransitionsResponse(value: unknown): value is RunTransitionsResponse {
  if (!isObject(value) || !nonemptyString(value.run_id) || value.response_source !== "postgres_durable_run_ledger"
      || typeof value.truncated !== "boolean" || !Array.isArray(value.transitions) || value.transitions.length > 250
      || (value.truncated && value.transitions.length === 0)) return false;
  const ids = new Set<string>();
  for (const row of value.transitions) {
    if (!isObject(row) || typeof row.transition_id !== "string" || !/^[1-9][0-9]{0,18}$/.test(row.transition_id)
        || ids.has(row.transition_id) || (row.from_status !== null && !isTransitionStatus(row.from_status))
        || !isTransitionStatus(row.to_status) || !nonemptyString(row.event_at) || !Number.isFinite(Date.parse(row.event_at))
        || typeof row.source !== "string" || !Object.prototype.hasOwnProperty.call(transitionSources, row.source)) return false;
    ids.add(row.transition_id);
  }
  // Keep ledger order: JS Date loses PostgreSQL sub-millisecond precision.
  return true;
}

function useRecordedRunEvidence<T extends { run_id: string }>(
  runId: string,
  revision: number,
  resource: "transitions" | "participation",
  validate: (value: unknown) => value is T,
) {
  const [result, setResult] = useState<{ runId: string; revision: number; receipt: T | null } | null>(null);
  useEffect(() => {
    let active = true;
    apiClient.get<unknown>(`/api/agent-runtime/my-runs/${encodeURIComponent(runId)}/${resource}`)
      .then((receipt) => {
        if (!validate(receipt) || receipt.run_id !== runId) throw new Error("Invalid recorded execution evidence");
        if (active) setResult({ runId, revision, receipt });
      })
      .catch(() => { if (active) setResult({ runId, revision, receipt: null }); });
    return () => { active = false; };
  }, [runId, revision, resource, validate]);
  const current = result?.runId === runId && result.revision === revision;
  return { receipt: current ? result.receipt : null, loading: !current };
}

function ExecutionTimeline({ runId, revision }: { runId: string; revision: number }) {
  const { receipt, loading } = useRecordedRunEvidence(runId, revision, "transitions", isRunTransitionsResponse);
  return (
    <section aria-label="Recorded execution timeline" className="mt-4 space-y-2">
      <h5 className="text-sm font-medium">Recorded execution timeline</h5>
      <p className="text-xs text-muted-foreground">Durable lifecycle evidence, not a live progress estimate.</p>
      {loading ? <p role="status" className="text-sm text-muted-foreground">Loading recorded transitions…</p>
        : !receipt ? <p role="status" className="text-sm text-muted-foreground">Recorded transition history is unavailable. Refresh runtime to retry.</p>
        : receipt.transitions.length === 0 ? <p className="text-sm text-muted-foreground">No durable transitions were recorded.</p>
        : <>
          {receipt.truncated && <p className="text-xs text-muted-foreground">Only the most recent recorded transitions are shown; earlier history is omitted.</p>}
          <ol className="space-y-3 border-l border-border pl-3 text-sm">
            {receipt.transitions.map((event) => (
              <li key={event.transition_id} className="space-y-1">
                <p className="break-words font-medium">{event.from_status ? event.from_status.replaceAll("_", " ") + " → " : ""}{event.to_status.replaceAll("_", " ")}</p>
                <p className="text-xs text-muted-foreground"><time dateTime={event.event_at}>{formatTimestamp(event.event_at)}</time></p>
                <p className="text-xs text-muted-foreground">{transitionSources[event.source]}</p>
              </li>
            ))}
          </ol>
        </>}
    </section>
  );
}

const participationPhases = {
  started: "Method entered",
  completed: "Invocation returned",
  failed: "Invocation failed",
  interrupted: "Invocation interrupted",
  skipped: "Invocation skipped",
} as const;

interface ParticipationReceipt {
  receipt_id: string;
  step_id: string;
  specialist_id: string;
  phase: keyof typeof participationPhases;
  observed_at: string;
}

interface RunParticipationResponse {
  run_id: string;
  evidence_status: "recorded" | "empty";
  receipts: ParticipationReceipt[];
  truncated: boolean;
  response_source: "postgres_outcome_records";
}

function boundedEvidenceId(value: unknown, max = 256): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= max
    && value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value);
}

export function isRunParticipationResponse(value: unknown): value is RunParticipationResponse {
  if (!isObject(value) || !boundedEvidenceId(value.run_id, 128)
      || value.response_source !== "postgres_outcome_records"
      || typeof value.truncated !== "boolean"
      || !Array.isArray(value.receipts) || value.receipts.length > 100
      || value.evidence_status !== (value.receipts.length > 0 ? "recorded" : "empty")
      || (value.truncated && value.receipts.length === 0)) return false;
  const receiptIds = new Set<string>();
  const steps = new Map<string, { specialist: string; phases: Set<string> }>();
  for (const row of value.receipts) {
    if (!isObject(row) || typeof row.receipt_id !== "string"
        || !/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(row.receipt_id)
        || receiptIds.has(row.receipt_id)
        || !boundedEvidenceId(row.step_id) || !boundedEvidenceId(row.specialist_id)
        || typeof row.phase !== "string" || !Object.prototype.hasOwnProperty.call(participationPhases, row.phase)
        || typeof row.observed_at !== "string" || row.observed_at.length > 64
        || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(row.observed_at)
        || !Number.isFinite(Date.parse(row.observed_at))) return false;
    const step = steps.get(row.step_id) ?? { specialist: row.specialist_id, phases: new Set<string>() };
    if (step.specialist !== row.specialist_id || step.phases.has(row.phase)
        || (row.phase !== "started" && [...step.phases].some((phase) => phase !== "started"))
        || (row.phase === "skipped" && step.phases.has("started"))
        || (row.phase === "started" && step.phases.has("skipped"))) return false;
    step.phases.add(row.phase);
    steps.set(row.step_id, step);
    receiptIds.add(row.receipt_id);
  }
  return true;
}

function SpecialistParticipation({ runId, revision }: { runId: string; revision: number }) {
  const { receipt, loading } = useRecordedRunEvidence(runId, revision, "participation", isRunParticipationResponse);
  return (
    <section aria-label="Recorded specialist participation" className="mt-4 space-y-2">
      <h5 className="text-sm font-medium">Recorded specialist participation</h5>
      <p className="text-xs text-muted-foreground">PostgreSQL outcome evidence. Method entry and invocation return do not prove inference, external actions, or overall task success.</p>
      {loading ? <p role="status" className="text-sm text-muted-foreground">Loading recorded participation…</p>
        : !receipt ? <p role="status" className="text-sm text-muted-foreground">Specialist participation evidence is unavailable. Refresh runtime to retry.</p>
        : receipt.evidence_status === "empty" ? <p className="text-sm text-muted-foreground">No durable specialist participation was recorded. Execution status alone does not establish participation.</p>
        : <>
          {receipt.truncated && <p className="text-xs text-muted-foreground">Only the most recent participation receipts are shown; earlier receipts are omitted.</p>}
          <p className="text-xs text-muted-foreground">A method-entry receipt without a recorded terminal observation does not establish current activity or completion.</p>
          <ol className="space-y-3 border-l border-border pl-3 text-sm">
            {receipt.receipts.map((event) => (
              <li key={event.receipt_id} className="space-y-1">
                <p className="break-words font-medium">{event.specialist_id} · {participationPhases[event.phase]}</p>
                <p className="break-all text-xs text-muted-foreground">Step: {event.step_id}</p>
                <p className="text-xs text-muted-foreground"><time dateTime={event.observed_at}>{formatTimestamp(event.observed_at)}</time></p>
              </li>
            ))}
          </ol>
        </>}
    </section>
  );
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatRunElapsed(run: AgentRunRecord): string {
  if (!run.started_at || !run.completed_at) return "Not recorded";
  const elapsed = Date.parse(run.completed_at) - Date.parse(run.started_at);
  if (!Number.isFinite(elapsed) || elapsed < 0) return "Not recorded";
  const seconds = Math.floor(elapsed / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function statusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" {
  const normalized = status.toLowerCase();
  if (normalized === "completed" || normalized === "active") return "default";
  if (normalized === "failed" || normalized === "cancelled") return "destructive";
  if (normalized === "running" || normalized === "cancelling") return "secondary";
  return "outline";
}

type AgentsPageProps = { onAskKaren?: () => void; onOpenConversation?: (conversationId: string) => Promise<void>; onDiscussRun?: (runId: string) => void };

export default function AgentsPage(props: AgentsPageProps) {
  const { user, isAuthenticated, isLoading } = useAuth();
  const identity = JSON.stringify([isAuthenticated, user?.tenant_id, user?.user_id, user?.roles?.includes("admin") ?? false]);
  if (isLoading) return <p role="status">Restoring your session…</p>;
  return <ScopedAgentsPage key={identity} {...props} />;
}

function ScopedAgentsPage(props: AgentsPageProps) {
  const { user, isAuthenticated } = useAuth();
  const canAdminister = isAuthenticated && (user?.roles?.includes("admin") ?? false);
  const [scope, setScope] = useState<"personal" | "tenant">("personal");
  const effectiveScope = canAdminister ? scope : "personal";
  return (
    <div className="space-y-4">
      {canAdminister && (
        <div role="group" aria-label="Execution scope" className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" variant={effectiveScope === "personal" ? "default" : "outline"} aria-pressed={effectiveScope === "personal"} onClick={() => setScope("personal")}>My work</Button>
          <Button type="button" size="sm" variant={effectiveScope === "tenant" ? "default" : "outline"} aria-pressed={effectiveScope === "tenant"} onClick={() => setScope("tenant")}>Tenant administration</Button>
        </div>
      )}
      <AgentRuntimeWorkspace key={effectiveScope} {...props} tenantScope={effectiveScope === "tenant"} />
    </div>
  );
}

function AgentRuntimeWorkspace({ onAskKaren, onOpenConversation, onDiscussRun, tenantScope }: AgentsPageProps & { tenantScope: boolean }) {
  const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();
  const isAdmin = tenantScope && isAuthenticated && (user?.roles?.includes("admin") ?? false);

  const [catalog, setCatalog] = useState<AgentCatalogResponse | null>(null);
  const [runs, setRuns] = useState<AgentRunRecord[]>([]);
  const [isLoadingCatalog, setIsLoadingCatalog] = useState(true);
  const [isLoadingRuns, setIsLoadingRuns] = useState(true);
  const [runsGeneratedAt, setRunsGeneratedAt] = useState<string | null>(null);
  const [isRevalidatingRun, setIsRevalidatingRun] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [runsError, setRunsError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const {
    approvals, approvalsError, decidingApprovalId, pendingApprovalDecision,
    setPendingApprovalDecision, isLoadingApprovals, approvalDecisionError,
    approvalDecisionUncertain, loadApprovals, decideApproval,
  } = useRuntimeApprovals(isAuthenticated, setActionMessage);
  const [cancellationError, setCancellationError] = useState("");
  const [cancellationUncertain, setCancellationUncertain] = useState(false);
  const cancellationUncertainRef = useRef(false);
  const cancellationRevision = useRef(0);
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);
  const cancellationInFlightRef = useRef(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [verifiedRun, setVerifiedRun] = useState<AgentRunRecord | null>(null);
  const [runListRevision, setRunListRevision] = useState(0);
  const [hasActiveRunPolling, setHasActiveRunPolling] = useState(false);
  const workspaceLive = useRef(false);
  useLayoutEffect(() => {
    workspaceLive.current = true;
    return () => { workspaceLive.current = false; };
  }, []);
  const runListRequestPromiseRef = useRef<Promise<void> | null>(null);
  const runListRefreshQueuedRef = useRef(false);
  const [runDetailError, setRunDetailError] = useState("");
  const [contextMessage, setContextMessage] = useState("");
  const [workFilter, setWorkFilter] = useState<"all" | "active" | "completed" | "failed">("all");
  const [historyQuery, setHistoryQuery] = useState("");
  const [objective, setObjective] = useState("");
  const [objectiveError, setObjectiveError] = useState("");
  const objectiveHandoffPending = useRef(false);

  function reviewObjective() {
    if (!workspaceLive.current || !isAuthenticated || isAdmin || objectiveHandoffPending.current || !objective.trim()) return;
    objectiveHandoffPending.current = true;
    try {
      const accepted = !window.dispatchEvent(new CustomEvent("karen:inject-message", {
        cancelable: true,
        detail: { role: "user", content: objective.trim(), autoSubmit: false },
      }));
      if (!accepted) {
        setObjectiveError("Karen could not prepare the objective. Your text is retained. Check the conversation is ready and not processing a message, then retry.");
        return;
      }
      setObjective("");
      setObjectiveError("");
    } finally {
      objectiveHandoffPending.current = false;
    }
  }
  const normalizedHistoryQuery = historyQuery.trim().toLowerCase();

  const activeRuns = useMemo(
    () =>
      runs.filter((run) =>
        ["queued", "running", "cancelling"].includes(run.status.toLowerCase()),
      ),
    [runs],
  );

  const selectedRun = selectedRunId
    ? (verifiedRun?.run_id === selectedRunId ? verifiedRun : null)
    : null;

  useEffect(() => {
    if (!selectedRunId || !isAuthenticated) {
      setVerifiedRun(null);
      setIsRevalidatingRun(false);
      setRunDetailError("");
      return;
    }
    let active = true;
    setIsRevalidatingRun(true);
    setVerifiedRun((previous) => previous?.run_id === selectedRunId ? previous : null);
    setRunDetailError("");
    // Even an ID from the list is treated as an untrusted lookup key.
    apiClient.get<unknown>(isAdmin
      ? `/api/admin/agents/runs/${encodeURIComponent(selectedRunId)}`
      : `/api/agent-runtime/my-runs/${encodeURIComponent(selectedRunId)}`)
      .then((record) => {
        if (!isAgentRunRecord(record) || record.run_id !== selectedRunId) throw new Error("Execution details do not match the requested run.");
        if (active) setVerifiedRun(record);
      })
      .catch((error: unknown) => {
        if (active) {
          setVerifiedRun(null);
          setRunDetailError(error instanceof Error ? error.message : "Execution details unavailable.");
        }
      }).finally(() => { if (active) setIsRevalidatingRun(false); });
    return () => { active = false; };
  }, [selectedRunId, isAuthenticated, isAdmin, runListRevision]);
  const visibleRuns = runs.filter((run) => {
    if (normalizedHistoryQuery && ![run.run_id, run.status, run.started_at, run.completed_at].some((value) => value?.toLowerCase().includes(normalizedHistoryQuery))) return false;
    if (workFilter === "all") return true;
    const status = run.status.toLowerCase();
    if (workFilter === "active") return ["queued", "running", "cancelling"].includes(status);
    if (workFilter === "completed") return ["completed", "succeeded"].includes(status);
    return ["failed", "cancelled", "canceled"].includes(status);
  });

  const loadCatalog = useCallback(async () => {
    if (!isAuthenticated) {
      setCatalog(null);
      setCatalogError("Authentication is required to inspect the agent runtime.");
      setIsLoadingCatalog(false);
      return;
    }

    setIsLoadingCatalog(true);
    setCatalogError("");
    try {
      const response = await apiClient.get<unknown>(
        "/api/agent-runtime/catalog",
      );
      if (!isAgentCatalogResponse(response)) {
        throw new Error("Agent catalog response does not match the discovery contract.");
      }
      setCatalog(response);
    } catch (error) {
      setCatalog(null);
      setCatalogError(
        error instanceof Error
          ? error.message
          : "Failed to load the Agent Medusa catalog.",
      );
    } finally {
      setIsLoadingCatalog(false);
    }
  }, [isAuthenticated]);

  const loadRuns = useCallback((priority = false): Promise<void> => {
    if (!workspaceLive.current) return Promise.resolve();
    if (runListRequestPromiseRef.current) {
      if (priority) runListRefreshQueuedRef.current = true;
      return runListRequestPromiseRef.current;
    }
    if (!isAuthenticated) {
      setRuns([]);
      setRunsGeneratedAt(null);
      setHasActiveRunPolling(false);
      setRunsError("");
      setIsLoadingRuns(false);
      return Promise.resolve();
    }

    const task = (async () => {
      setIsLoadingRuns(true);
      try {
        do {
          runListRefreshQueuedRef.current = false;
          try {
            const readCancellationRevision = cancellationRevision.current;
            const response = await apiClient.get<unknown>(
              isAdmin ? "/api/admin/agents/runs?include_terminal=true" : "/api/agent-runtime/my-runs",
            );
            if (!workspaceLive.current) return;
            if (!isAgentRunsResponse(response)) throw new Error("Execution history response does not match the runtime contract.");
            setRuns(response.runs);
            setRunsGeneratedAt(response.generated_at);
            setRunsError("");
            if (!cancellationInFlightRef.current && readCancellationRevision === cancellationRevision.current) {
              cancellationUncertainRef.current = false;
              setCancellationUncertain(false);
              setCancellationError("");
            }
            setSelectedRunId((previous) => response.runs.some((run) => run.run_id === previous) ? previous : null);
            setHasActiveRunPolling(response.runs.some((run) =>
              ["queued", "running", "cancelling"].includes(run.status.toLowerCase()),
            ));
            setRunListRevision((revision) => revision + 1);
          } catch (error) {
            if (!workspaceLive.current) return;
            setRunsGeneratedAt(null);
            setRuns([]);
            setSelectedRunId(null);
            setVerifiedRun(null);
            setContextMessage("");
            setRunsError(
              error instanceof Error ? error.message : "Failed to load tenant-scoped Medusa runs.",
            );
          }
        } while (workspaceLive.current && runListRefreshQueuedRef.current);
      } finally {
        setIsLoadingRuns(false);
      }
    })().finally(() => {
      runListRequestPromiseRef.current = null;
    });
    runListRequestPromiseRef.current = task;
    return task;
  }, [isAuthenticated, isAdmin]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadRuns();
    }, hasActiveRunPolling ? 15000 : 60000);
    const onVisibility = () => { if (document.visibilityState === "visible") void loadRuns(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [isAuthenticated, hasActiveRunPolling, loadRuns]);

  const copyVerifiedRunContext = useCallback(async (runId: string) => {
    if (!workspaceLive.current || !isAuthenticated || isAdmin) return;
    setContextMessage("");
    try {
      const record = await apiClient.get<{
        resource_type: string; run_id: string; status: string;
        started_at?: string | null; completed_at?: string | null; error_type?: string | null;
      }>(`/api/agent-runtime/my-runs/${encodeURIComponent(runId)}/context`);
      if (!workspaceLive.current) return;
      if (!isObject(record) || record.resource_type !== "medusa_run" || record.run_id !== runId || !nonemptyString(record.status)) {
        throw new Error("Execution identity changed during verification.");
      }
      const prompt = `Please explain my Agent Runtime execution ${record.run_id}. Verified status: ${record.status}. Check current permissions and execution state before taking action.`;
      await navigator.clipboard.writeText(prompt);
      setContextMessage("Verified run reference copied. Open Karen and paste it to ask about this execution. Karen must independently verify access.");
    } catch (error) {
      setContextMessage(error instanceof Error ? error.message : "Could not verify or copy this execution reference.");
    }
  }, [isAuthenticated, isAdmin]);

  const refresh = useCallback(async () => {
    setActionMessage("");
    await Promise.all([loadCatalog(), loadRuns(true), loadApprovals()]);
  }, [loadCatalog, loadRuns, loadApprovals]);

  useEffect(() => {
    if (isAuthLoading) return;
    void refresh();
  }, [isAuthLoading, refresh]);

  const cancelRun = useCallback(
    async (runId: string) => {
      if (!workspaceLive.current || !isAdmin || cancellationInFlightRef.current || cancellationUncertainRef.current || isLoadingRuns || runsError || !runs.some((run) => run.run_id === runId && run.cancellable === true)) return;
      cancellationInFlightRef.current = true;
      cancellationRevision.current += 1;

      setCancellingRunId(runId);
      setActionMessage("");
      setCancellationError("");
      try {
        const response = await apiClient.post<unknown>(
          `/api/admin/agents/runs/${encodeURIComponent(runId)}/cancel`,
        );
        if (!workspaceLive.current) return;
        if (!isAgentRunRecord(response) || response.run_id !== runId) throw new Error("Cancellation response could not be verified. Refresh to inspect current state.");
        setActionMessage(
          `Cancellation endpoint responded for ${runId}. Reported status: ${response.status}. Check the refreshed run details for current state.`,
        );
        await loadRuns(true);
      } catch (error) {
        if (!workspaceLive.current) return;
        cancellationRevision.current += 1;
        cancellationUncertainRef.current = true;
        setCancellationUncertain(true);
        setCancellationError("Cancellation outcome could not be verified. Refresh to inspect current execution status.");
      } finally {
        cancellationInFlightRef.current = false;
        setCancellingRunId(null);
      }
    },
    [isAdmin, loadRuns, isLoadingRuns, runsError, runs],
  );

  if (isAuthLoading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center">
        <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-7xl min-w-0 space-y-6 pb-6" data-testid="agent-runtime-page">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <Bot className="mt-1 h-8 w-8 text-primary" />
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              Mission Control
            </h2>
            <p className="karen-page-description mt-1">
              {isAdmin ? "Inspect authorized tenant execution activity and operational evidence." : "Delegate objectives, review execution evidence, and stay in control of your work."}
            </p>
          </div>
        </div>

        <Button
          type="button"
          variant="outline"
          onClick={() => void refresh()}
          disabled={isLoadingCatalog || isLoadingRuns}
        >
          <RefreshCw
            className={`mr-2 h-4 w-4 ${
              isLoadingCatalog || isLoadingRuns ? "animate-spin" : ""
            }`}
          />
          Refresh runtime
        </Button>
      </header>

      {!isAdmin && (
        <section aria-label="Start a mission" className="relative overflow-hidden rounded-2xl border border-primary/20 bg-card p-5 sm:p-7">
          <div className="relative flex flex-col items-start gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-widest text-primary">Your AI workspace</p>
              <h3 className="text-xl font-semibold tracking-tight sm:text-2xl">What are we accomplishing today?</h3>
              <p className="max-w-xl text-sm text-muted-foreground">Prepare an objective for review in your current Karen conversation. Existing draft text is preserved. Nothing is submitted automatically.</p>
            </div>
            <Button type="button" size="lg" className="w-full shrink-0 sm:w-auto" onClick={onAskKaren} disabled={!isAuthenticated || !onAskKaren}>
              Ask Karen <ArrowUpRight aria-hidden="true" className="ml-2 h-4 w-4" />
            </Button>
          </div>
          {isAuthenticated && <form className="mt-5 space-y-3" onSubmit={(event) => { event.preventDefault(); reviewObjective(); }}>
            <label htmlFor="mission-objective" className="block text-sm font-medium">Mission objective</label>
            <textarea id="mission-objective" rows={4} value={objective} maxLength={65536} onChange={(event) => { setObjective(event.target.value); setObjectiveError(""); }} className="w-full rounded-lg border border-input bg-background p-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring" placeholder="Describe the outcome, deliverables and constraints…" />
            {objectiveError && <p role="alert" className="text-sm text-destructive">{objectiveError}</p>}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">Review in the current conversation before sending.</p>
              <Button type="submit" disabled={!objective.trim()}>Review objective <ArrowUpRight aria-hidden="true" className="ml-2 h-4 w-4" /></Button>
            </div>
          </form>}
        </section>
      )}

      {isAuthenticated && (
        <section aria-label="Workspace overview" className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">Workspace overview</h3>
            <p className="text-xs text-muted-foreground">{isAdmin ? "Tenant executions · your approvals" : "Your visible executions and approvals"}</p>
          </div>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            {[
              { label: "Active executions", icon: Activity, value: runsError ? "Unavailable" : !runsGeneratedAt ? "Loading" : activeRuns.length, hint: isLoadingRuns && runsGeneratedAt ? "Refreshing snapshot" : "Visible run history" },
              { label: "Completed executions", icon: CheckCircle2, value: runsError ? "Unavailable" : !runsGeneratedAt ? "Loading" : runs.filter((run) => ["completed", "succeeded"].includes(run.status.toLowerCase())).length, hint: isLoadingRuns && runsGeneratedAt ? "Refreshing snapshot" : "Visible run history" },
              { label: "Approval requests", icon: ShieldCheck, value: approvalsError ? "Unavailable" : isLoadingApprovals ? "Loading" : approvals.length, hint: "Your approval inbox" },
              { label: "Registered specialists", icon: Users, value: catalogError ? "Unavailable" : isLoadingCatalog ? "Loading" : catalog?.total ?? "Unavailable", hint: "Eligibility decided per request" },
            ].map(({ label, icon: Icon, value, hint }) => (
              <Card key={label} className="min-w-0">
                <CardHeader className="space-y-2 p-3 sm:p-4">
                  <Icon aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                  <CardDescription className="text-xs">{label}</CardDescription>
                  <CardTitle className="break-words text-base tabular-nums sm:text-2xl">{value}</CardTitle>
                  <p className="text-xs text-muted-foreground">{hint}</p>
                </CardHeader>
              </Card>
            ))}
          </div>
        </section>
      )}

      <nav aria-label="Mission Control sections" className="flex flex-wrap gap-2 border-b border-border pb-3">
        <Button asChild variant="ghost" size="sm"><a href="#mission-history">Mission history</a></Button>
        <Button asChild variant="ghost" size="sm"><a href="#mission-approvals">Approvals</a></Button>
        <Button asChild variant="ghost" size="sm"><a href="#mission-specialists">Specialists</a></Button>
        <Button asChild variant="ghost" size="sm"><a href="#mission-diagnostics">Diagnostics</a></Button>
      </nav>

      <section id="mission-history" aria-label="Your AI work" className="scroll-mt-4 space-y-4" data-testid="agent-workspace">
        <div>
          <h3 className="text-lg font-semibold">{isAdmin ? "Tenant execution workspace" : "Mission history"}</h3>
          <p className="text-sm text-muted-foreground">Inspect recorded executions and their verified status.</p>
        </div>
        {isAuthenticated ? (
          <>
            {cancellationError && <p role="alert" className="text-sm text-destructive">{cancellationError}</p>}
            {runsError && <p role="alert" className="rounded-lg border border-destructive/50 p-3 text-sm text-destructive">Run status refresh failed: {runsError}</p>}
            {runsGeneratedAt && <p className="text-xs text-muted-foreground" role="status">Execution snapshot: {formatTimestamp(runsGeneratedAt)}{isLoadingRuns ? " · Refreshing…" : ""}</p>}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div className="w-full max-w-md space-y-1">
                <label htmlFor="mission-history-search" className="text-xs font-medium">Search visible executions</label>
                <div className="relative">
                  <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                  <Input id="mission-history-search" type="search" className="pl-9" placeholder="Run ID, status or date" value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} />
                </div>
              </div>
              {historyQuery && <Button type="button" size="sm" variant="outline" onClick={() => setHistoryQuery("")}>Clear search</Button>}
              {runsGeneratedAt && !runsError && <p role="status" className="text-xs text-muted-foreground">{visibleRuns.length} of {runs.length} visible executions{selectedRunId && !visibleRuns.some((run) => run.run_id === selectedRunId) ? " · Selected execution is outside current filters" : ""}</p>}
            </div>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filter visible runs">
              {(["all", "active", "completed", "failed"] as const).map((filter) => (
                <Button key={filter} type="button" size="sm"
                  variant={workFilter === filter ? "default" : "outline"}
                  aria-pressed={workFilter === filter}
                  onClick={() => setWorkFilter(filter)}>
                  {filter === "all" ? "All work" : filter === "active" ? "In progress" : filter === "completed" ? "Completed" : "Failed or cancelled"}
                </Button>
              ))}
            </div>
            <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_minmax(0,2fr)]">
              <div className="space-y-2" aria-label="Execution list">
                {isLoadingRuns && !runsGeneratedAt && !runsError ? <p role="status" className="text-sm text-muted-foreground">Loading verified work…</p> : runsError ? <p className="text-sm text-muted-foreground">Execution history is unavailable. Refresh runtime to try again.</p> :
                  visibleRuns.length ? visibleRuns.map((run) => (
                    <button type="button" key={run.run_id}
                      className={`w-full min-w-0 rounded-lg border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring ${selectedRunId === run.run_id ? "border-primary bg-primary/5 ring-1 ring-primary/30" : "border-border hover:bg-muted/50"}`}
                      aria-pressed={selectedRunId === run.run_id}
                      onClick={() => { setSelectedRunId(run.run_id); setContextMessage(""); }}>
                      <span className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-medium">Execution {run.run_id.slice(0, 8)}</span><Badge variant={statusVariant(run.status)}>{run.status}</Badge></span>
                      <span className="mt-1 block break-all font-mono text-xs text-muted-foreground">{run.run_id}</span>
                      <span className="mt-1 block text-xs text-muted-foreground">Started {formatTimestamp(run.started_at)}</span>
                    </button>
                  )) : normalizedHistoryQuery ? <div className="rounded-lg border p-4 space-y-2 text-sm text-muted-foreground"><p>No visible executions match your search.</p><Button type="button" size="sm" variant="outline" onClick={() => setHistoryQuery("")}>Reset search</Button></div> : <div className="rounded-lg border p-4 space-y-2 text-sm text-muted-foreground"><p>{workFilter === "active" ? "No work is currently in progress." : workFilter === "completed" ? "No completed executions are recorded." : workFilter === "failed" ? "No failed or cancelled executions are recorded." : "No verified executions match this view."}</p><p>{workFilter === "all" ? "Use Ask Karen to describe an objective. Verified agent executions will appear here when recorded." : "Choose All work to review other execution states, or use Ask Karen to start a new objective."}</p></div>}
              </div>
              <div className="min-w-0 rounded-xl border border-border bg-card p-4 sm:p-5" aria-label="Selected execution details">
                {runsError ? <p className="text-sm text-muted-foreground">Execution details unavailable until history is verified.</p> : runDetailError ? <p role="alert" className="text-sm text-destructive">{runDetailError}</p> : selectedRun ? (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h4 className="font-semibold">Execution details</h4>
                      <Badge variant={statusVariant(selectedRun.status)}>{selectedRun.status}</Badge>
                    </div>
                    {(isRevalidatingRun || isLoadingRuns) && <p role="status" className="mt-2 text-xs text-muted-foreground">Revalidating execution status…</p>}
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <div className="rounded-lg border border-border p-3">
                        <p className="text-xs text-muted-foreground">Reported task outcome</p>
                        <p className="mt-1 break-words text-sm font-medium">{selectedRun.outcome_status || "Not recorded"}</p>
                      </div>
                      <div className="rounded-lg border border-border p-3">
                        <p className="text-xs text-muted-foreground">Recorded elapsed time</p>
                        <p className="mt-1 text-sm font-medium">{formatRunElapsed(selectedRun)}</p>
                      </div>
                    </div>
                    {!isAdmin && <>
                      <ExecutionTimeline key={selectedRun.run_id} runId={selectedRun.run_id} revision={runListRevision} />
                      <SpecialistParticipation key={`participation:${selectedRun.run_id}`} runId={selectedRun.run_id} revision={runListRevision} />
                    </>}
                    <section aria-label="Recorded lifecycle timestamps" className="mt-4 space-y-2">
                      <h5 className="text-sm font-medium">Recorded lifecycle timestamps</h5>
                      <p className="text-xs text-muted-foreground">Snapshot evidence only; not a complete transition history.</p>
                      <dl className="space-y-2 border-l border-border pl-3 text-sm">
                        {([
                          ["Created", selectedRun.created_at],
                          ["Started", selectedRun.started_at],
                          ["Cancellation requested", selectedRun.cancel_requested_at],
                          ["Ended", selectedRun.completed_at],
                        ] as const).filter(([, value]) => typeof value === "string" && Number.isFinite(Date.parse(value))).map(([label, value]) => (
                          <div key={label}><dt className="font-medium">{label}</dt><dd className="text-xs text-muted-foreground">{formatTimestamp(value)}</dd></div>
                        ))}
                      </dl>
                      {![selectedRun.created_at, selectedRun.started_at, selectedRun.cancel_requested_at, selectedRun.completed_at].some((value) => typeof value === "string" && Number.isFinite(Date.parse(value))) && <p className="text-sm text-muted-foreground">No valid lifecycle timestamps were recorded.</p>}
                    </section>
                    <p className="mt-2 text-sm text-muted-foreground">{selectedRun.status.toLowerCase() === "completed" ? "Execution completed. A saved artifact is not implied by this status." : selectedRun.status.toLowerCase() === "cancelling" ? "Cancellation requested, awaiting confirmed terminal status." : "This status comes from the Medusa run ledger, not a simulated progress estimate."}</p>
                    {selectedRun.error_type && <p role="alert" className="mt-3 text-sm text-destructive">Reported failure: {selectedRun.error_type}</p>}
                    <details className="mt-4 text-sm">
                      <summary className="cursor-pointer font-medium">Technical details</summary>
                      <dl className="mt-2 space-y-2 text-xs text-muted-foreground">
                        <div><dt>Run ID</dt><dd className="break-all">{selectedRun.run_id}</dd></div>
                        <div><dt>Correlation ID</dt><dd className="break-all">{selectedRun.correlation_id || "Not recorded"}</dd></div>
                        <div><dt>Response source</dt><dd>{selectedRun.response_source || "Not recorded"}</dd></div>
                        {isAdmin && <>
                          <div><dt>User</dt><dd className="break-all">{selectedRun.user_id || "Not recorded"}</dd></div>
                          <div><dt>Session</dt><dd className="break-all">{selectedRun.session_id || "Not recorded"}</dd></div>
                          <div><dt>Policy decision</dt><dd className="break-all">{selectedRun.policy_decision_id || "Not recorded"}</dd></div>
                          <div><dt>Durability</dt><dd>{selectedRun.durable === undefined ? "Not recorded" : selectedRun.durable ? "Durable" : "Not durable"}</dd></div>
                        </>}
                      </dl>
                    </details>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {!isAdmin && onDiscussRun && <Button type="button" size="sm" disabled={isRevalidatingRun || isLoadingRuns} onClick={() => onDiscussRun(selectedRun.run_id)}>Discuss with Karen</Button>}
                      {!isAdmin && <Button type="button" size="sm" variant="outline" disabled={isRevalidatingRun || isLoadingRuns} onClick={() => void copyVerifiedRunContext(selectedRun.run_id)}>Copy verified context for Karen</Button>}
                      {onAskKaren && <Button type="button" size="sm" variant="outline" onClick={onAskKaren}>Open Karen</Button>}
                    </div>
                    {contextMessage && <p role="status" className="mt-2 text-sm">{contextMessage}</p>}
                    {isAdmin && selectedRun.cancellable && (
                      <Button className="mt-4" variant="destructive" size="sm"
                        disabled={isRevalidatingRun || isLoadingRuns || cancellationUncertain || cancellingRunId !== null}
                        onClick={() => void cancelRun(selectedRun.run_id)}>
                        <CircleStop className="mr-2 h-4 w-4" /> Request cancellation
                      </Button>
                    )}
                  </>
                ) : <p className="text-sm text-muted-foreground">{selectedRunId ? "Verifying execution access…" : "Select an execution to inspect its verified status."}</p>}
              </div>
            </div>
            <p className="text-xs text-muted-foreground">{isAdmin ? "Administrative view: tenant-scoped run history." : "Only your verified Medusa runs appear here. Run cancellation is administrator-controlled."}</p>
          </>
        ) : (
          <p className="rounded-lg border p-4 text-sm text-muted-foreground">Sign in to view your authorized work history.</p>
        )}
      </section>

      <section id="mission-approvals" aria-label="Needs your review" className="scroll-mt-4 space-y-3" data-testid="agent-runtime-approvals">
        <h3 className="text-lg font-semibold">Needs your review</h3>
        <p className="text-sm text-muted-foreground">These requests come from Karen&apos;s authorized approval service. A decision alone does not execute an action.</p>
        {approvalDecisionError && <p role="alert" className="text-sm text-destructive">{approvalDecisionError}</p>}
        {approvalsError && <p role="alert" className="text-sm text-destructive">{approvalsError}</p>}
        {!isAuthenticated ? <p className="text-sm text-muted-foreground">Sign in to review authorized approval requests.</p> : isLoadingApprovals ? <p role="status" className="text-sm text-muted-foreground">Loading approval requests…</p> : approvalsError ? <p className="text-sm text-muted-foreground">Approval requests are unavailable. Refresh runtime to try again.</p> : approvals.length === 0 ? (
          <p className="rounded-lg border p-4 text-sm text-muted-foreground">You’re all caught up. No actionable approval requests are available. Karen will show requests here when human review is required.</p>
        ) : approvals.map((approval) => (
          <div key={approval.approval_id} className="rounded-lg border p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="font-medium">{approval.intent}</h4>
              <Badge variant="outline">{approval.risk_level} risk</Badge>
            </div>
            <p className="text-sm text-muted-foreground">Expires {formatTimestamp(approval.expires_at)}</p>
            {approval.conversation_id && (
              <p className="text-xs text-muted-foreground">Related conversation: <span className="font-mono break-all">{approval.conversation_id}</span></p>
            )}
            <p className="text-xs text-muted-foreground">Review this decision in its original conversation before asking Karen to continue. Navigating to Chat does not automatically select a conversation or execute work.</p>
            {approval.reason_codes.length > 0 && <p className="text-sm text-muted-foreground">Reasons: {approval.reason_codes.join(", ")}</p>}
            <div className="flex flex-wrap gap-2">
              {approval.conversation_id && onOpenConversation && <Button size="sm" variant="outline" onClick={() => void onOpenConversation(approval.conversation_id!)}>Open original conversation</Button>}
              {onAskKaren && <Button size="sm" variant="outline" onClick={onAskKaren}>Open Karen chat</Button>}
              <Button size="sm" disabled={decidingApprovalId !== null || approvalDecisionUncertain || isLoadingApprovals}
                onClick={() => setPendingApprovalDecision({ approvalId: approval.approval_id, decision: "approved" })}>Review approval</Button>
              <Button size="sm" variant="outline" disabled={decidingApprovalId !== null || approvalDecisionUncertain || isLoadingApprovals}
                onClick={() => setPendingApprovalDecision({ approvalId: approval.approval_id, decision: "rejected" })}>Review rejection</Button>
            </div>
            {pendingApprovalDecision?.approvalId === approval.approval_id && (
              <section aria-label="Confirm approval decision" className="rounded-lg border border-primary/50 bg-muted/40 p-3 space-y-2">
                <p className="font-medium">Confirm {pendingApprovalDecision.decision === "approved" ? "approval" : "rejection"}</p>
                <p className="text-sm">Request: {approval.intent}. Risk: {approval.risk_level}. Expires: {formatTimestamp(approval.expires_at)}.</p>
                <p className="text-xs text-muted-foreground">This records your decision only. Karen must separately revalidate authorization and execution state.</p>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" disabled={decidingApprovalId !== null || approvalDecisionUncertain || isLoadingApprovals}
                    onClick={() => void decideApproval(approval.approval_id, pendingApprovalDecision.decision)}>
                    Confirm {pendingApprovalDecision.decision === "approved" ? "approval" : "rejection"}
                  </Button>
                  <Button type="button" variant="outline" disabled={decidingApprovalId !== null || approvalDecisionUncertain || isLoadingApprovals}
                    onClick={() => setPendingApprovalDecision(null)}>Back</Button>
                </div>
              </section>
            )}
          </div>
        ))}
      </section>

      <details id="mission-diagnostics" className="scroll-mt-4 rounded-lg border border-border p-3 text-sm"><summary className="cursor-pointer font-medium">Runtime architecture and authorization</summary><Alert className="mt-3">
        <ShieldCheck className="h-4 w-4" />
        <AlertTitle>Canonical ownership</AlertTitle>
        <AlertDescription>
          This surface is read-only for agent definitions. Per-agent daemon
          start/stop controls are intentionally absent. Executions are created
          by ChatRuntime after CORTEX and RuntimePolicy approval; concrete runs
          can be observed and, for administrators, cancelled by run ID.
        </AlertDescription>
      </Alert></details>

      {catalogError && (
        <Alert variant="destructive">
          <AlertTitle>Agent catalog unavailable</AlertTitle>
          <AlertDescription>{catalogError}</AlertDescription>
        </Alert>
      )}

      {actionMessage && (
        <Alert>
          <Activity className="h-4 w-4" />
          <AlertTitle>Runtime action response</AlertTitle>
          <AlertDescription>{actionMessage}</AlertDescription>
        </Alert>
      )}

      <section id="mission-specialists" aria-label="Registered specialists" className="scroll-mt-4 space-y-3 rounded-xl border border-border p-4 sm:p-5">
        <div>
          <h3 className="text-lg font-semibold">Registered specialists</h3>
          <p className="text-sm text-muted-foreground">
            Registration is not a promise that an agent will run. Eligibility is
            evaluated per request by the canonical policy path.
          </p>
        </div>

        {isLoadingCatalog ? (
          <Card>
            <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <RefreshCw className="h-4 w-4 animate-spin" />
              Loading Agent Medusa catalog…
            </CardContent>
          </Card>
        ) : catalogError ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              Registered specialists are unavailable until the catalog contract is verified.
            </CardContent>
          </Card>
        ) : catalog?.agents.length ? (
          <div className="grid gap-4 xl:grid-cols-2">
            {catalog.agents.map((agent) => (
              <Card key={agent.agent_id} data-agent-id={agent.agent_id}>
                <CardHeader>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-base">{agent.name}</CardTitle>
                    <div className="flex gap-2">
                      <Badge variant={agent.healthy ? "default" : "destructive"}>
                        {agent.healthy ? "healthy" : "degraded"}
                      </Badge>
                      <Badge variant="outline">{agent.lifecycle_state}</Badge>
                    </div>
                  </div>
                  <CardDescription>
                    Registered specialist. Execution eligibility is decided for each request by CORTEX and RuntimePolicy.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <dl className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                    <div>
                      <dt className="font-medium text-foreground">Agent ID</dt>
                      <dd className="break-all">{agent.agent_id}</dd>
                    </div>
                    <div>
                      <dt className="font-medium text-foreground">Execution eligibility</dt>
                      <dd>Determined per request</dd>
                    </div>
                  </dl>
                  <p className="text-xs text-muted-foreground">
                    Capabilities, implementation, prompt contract, and version are not exposed by this discovery endpoint.
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              No active Agent Medusa specialists are registered.
            </CardContent>
          </Card>
        )}
      </section>

      {isAdmin && (
        <details className="rounded-lg border border-border p-3 text-sm">
          <summary className="cursor-pointer font-medium">Administrative execution diagnostics</summary>
          <p className="mt-3 text-muted-foreground">Select an execution in Mission history to inspect its verified user, session, policy decision and durability details. Authorized cancellation controls are available in that inspector only.</p>
          <p className="mt-2 text-muted-foreground">Execution snapshot: {runsGeneratedAt ? formatTimestamp(runsGeneratedAt) : "Unavailable"}</p>
        </details>
      )}
    </div>
  );
}
