"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bot,
  CircleStop,
  RefreshCw,
  ShieldCheck,
  Workflow,
} from "lucide-react";

import useAuth from "@/lib/useAuth";
import { apiClient } from "@/lib/api";
import { isAgentCatalogResponse, type AgentCatalogResponse } from "./agentCatalog";
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
  error_type?: string | null;
  cancellable?: boolean;
  durable?: boolean;
  response_source?: string | null;
  distributed_control?: {
    supported?: boolean;
    [key: string]: unknown;
  } | null;
}

export interface RuntimeApproval {
  approval_id: string;
  conversation_id?: string | null;
  intent: string;
  risk_level: string;
  reason_codes: string[];
  status: string;
  expires_at: string;
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
    && ["correlation_id", "request_id", "session_id", "policy_decision_id", "tenant_id", "user_id", "started_at", "completed_at", "error_type", "response_source"].every((key) => value[key] == null || typeof value[key] === "string")
    && ["cancellable", "durable"].every((key) => value[key] === undefined || typeof value[key] === "boolean")
    && (value.distributed_control == null || (isObject(value.distributed_control) && (value.distributed_control.supported === undefined || typeof value.distributed_control.supported === "boolean")));
}

export function isAgentRunsResponse(value: unknown): value is AgentRunsResponse {
  return isObject(value) && Array.isArray(value.runs) && value.runs.every(isAgentRunRecord)
    && value.total === value.runs.length && new Set(value.runs.map((run) => run.run_id)).size === value.runs.length
    && nonemptyString(value.generated_at) && Number.isFinite(Date.parse(value.generated_at));
}

export function isRuntimeApproval(value: unknown): value is RuntimeApproval {
  return isObject(value) && nonemptyString(value.approval_id) && nonemptyString(value.intent)
    && nonemptyString(value.risk_level) && nonemptyString(value.status)
    && (value.conversation_id == null || typeof value.conversation_id === "string")
    && Array.isArray(value.reason_codes) && value.reason_codes.every((reason) => typeof reason === "string")
    && nonemptyString(value.expires_at) && Number.isFinite(Date.parse(value.expires_at));
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
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
  const [approvals, setApprovals] = useState<RuntimeApproval[]>([]);
  const [approvalsError, setApprovalsError] = useState("");
  const [decidingApprovalId, setDecidingApprovalId] = useState<string | null>(null);
  const [pendingApprovalDecision, setPendingApprovalDecision] = useState<{ approvalId: string; decision: "approved" | "rejected" } | null>(null);
  const [isLoadingCatalog, setIsLoadingCatalog] = useState(true);
  const [isLoadingRuns, setIsLoadingRuns] = useState(true);
  const [runsGeneratedAt, setRunsGeneratedAt] = useState<string | null>(null);
  const [isRevalidatingRun, setIsRevalidatingRun] = useState(false);
  const [isLoadingApprovals, setIsLoadingApprovals] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [runsError, setRunsError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [cancellationError, setCancellationError] = useState("");
  const [approvalDecisionError, setApprovalDecisionError] = useState("");
  const [approvalDecisionUncertain, setApprovalDecisionUncertain] = useState(false);
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);
  const cancellationInFlightRef = useRef(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [verifiedRun, setVerifiedRun] = useState<AgentRunRecord | null>(null);
  const [runListRevision, setRunListRevision] = useState(0);
  const [hasActiveRunPolling, setHasActiveRunPolling] = useState(false);
  const approvalDecisionInFlightRef = useRef(false);
  const approvalReadRevision = useRef(0);
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
            const response = await apiClient.get<unknown>(
              isAdmin ? "/api/admin/agents/runs?include_terminal=true" : "/api/agent-runtime/my-runs",
            );
            if (!workspaceLive.current) return;
            if (!isAgentRunsResponse(response)) throw new Error("Execution history response does not match the runtime contract.");
            setRuns(response.runs);
            setRunsGeneratedAt(response.generated_at);
            setRunsError("");
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

  const loadApprovals = useCallback(async () => {
    if (!workspaceLive.current) return;
    const revision = ++approvalReadRevision.current;
    if (!isAuthenticated) {
      setApprovals([]);
      setApprovalsError("");
      setApprovalDecisionUncertain(false);
      setIsLoadingApprovals(false);
      return;
    }
    setIsLoadingApprovals(true);
    try {
      const records = await apiClient.get<unknown>("/api/approvals/");
      if (!workspaceLive.current || revision !== approvalReadRevision.current) return;
      if (!Array.isArray(records) || !records.every(isRuntimeApproval) || new Set(records.map((record) => record.approval_id)).size !== records.length) throw new Error("Approval response does not match the runtime contract.");
      setApprovals(records);
      setApprovalsError("");
      setApprovalDecisionUncertain(false);
    } catch (error) {
      if (!workspaceLive.current || revision !== approvalReadRevision.current) return;
      setApprovals([]);
      setApprovalsError(error instanceof Error ? error.message : "Could not load approval requests.");
    } finally {
      if (workspaceLive.current && revision === approvalReadRevision.current) setIsLoadingApprovals(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const discover = () => {
      if (document.visibilityState === "visible" && !approvalDecisionInFlightRef.current) void loadApprovals();
    };
    const timer = window.setInterval(discover, 60000);
    document.addEventListener("visibilitychange", discover);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", discover); };
  }, [isAuthenticated, loadApprovals]);

  const decideApproval = useCallback(async (approvalId: string, decision: "approved" | "rejected") => {
    if (!workspaceLive.current || !isAuthenticated || approvalDecisionInFlightRef.current || decidingApprovalId !== null || isLoadingApprovals || approvalsError || approvalDecisionUncertain) return;
    const approval = approvals.find((item) => item.approval_id === approvalId);
    if (!approval || Date.parse(approval.expires_at) <= Date.now()) {
      setApprovalDecisionError("This approval is unavailable or expired. Refresh the list before deciding.");
      setPendingApprovalDecision(null);
      return;
    }
    approvalDecisionInFlightRef.current = true;
    setDecidingApprovalId(approvalId);
    setPendingApprovalDecision(null);
    setApprovalDecisionError("");
    try {
      const result = await apiClient.post<unknown>(
        `/api/approvals/${encodeURIComponent(approvalId)}/decision`,
        { decision },
      );
      if (!workspaceLive.current) return;
      if (!isRuntimeApproval(result) || result.approval_id !== approvalId) throw new Error("Approval response could not be verified. Refresh before deciding again.");
      setActionMessage(
        result.status === decision
          ? `Decision recorded: ${decision}. Karen must still revalidate and resume the original request.`
          : `Approval status: ${result.status}. No action has been executed by this decision.`,
      );
      await loadApprovals();
    } catch (error) {
      if (!workspaceLive.current) return;
      setApprovalDecisionUncertain(true);
      setApprovalDecisionError("Decision outcome could not be verified. Refresh before attempting another decision.");
    } finally {
      approvalDecisionInFlightRef.current = false;
      setDecidingApprovalId(null);
    }
  }, [loadApprovals, approvals, decidingApprovalId, isLoadingApprovals, approvalsError, approvalDecisionUncertain, isAuthenticated]);

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
      if (!workspaceLive.current || !isAdmin || cancellationInFlightRef.current) return;
      cancellationInFlightRef.current = true;

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
        setCancellationError("Cancellation outcome could not be verified. Refresh to inspect current execution status.");
      } finally {
        cancellationInFlightRef.current = false;
        setCancellingRunId(null);
      }
    },
    [isAdmin, loadRuns],
  );

  if (isAuthLoading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center">
        <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="agent-runtime-page">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <Bot className="mt-1 h-8 w-8 text-primary" />
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              Agent Runtime
            </h2>
            <p className="karen-page-description mt-1">
              Delegate work to Karen, monitor verified execution progress, and inspect outcomes. Agent diagnostics are available below.
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
      </div>

      <section aria-label="Your AI work" className="space-y-4" data-testid="agent-workspace">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
          <div>
            <h3 className="text-lg font-semibold">{isAdmin ? "Tenant execution workspace" : "Your AI workspace"}</h3>
            <p className="text-sm text-muted-foreground">Ask Karen to work on a goal, then return to review real progress and results.</p>
          </div>
          <Button type="button" onClick={onAskKaren} disabled={!onAskKaren}>
            <Bot className="mr-2 h-4 w-4" /> Ask Karen
          </Button>
        </div>
        {isAuthenticated ? (
          <>
            {cancellationError && <p role="alert" className="text-sm text-destructive">{cancellationError}</p>}
            {runsError && <p role="alert" className="rounded-lg border border-destructive/50 p-3 text-sm text-destructive">Run status refresh failed: {runsError}</p>}
            {runsGeneratedAt && <p className="text-xs text-muted-foreground" role="status">Execution snapshot: {formatTimestamp(runsGeneratedAt)}{isLoadingRuns ? " · Refreshing…" : ""}</p>}
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filter visible runs">
              {(["all", "active", "completed", "failed"] as const).map((filter) => (
                <Button key={filter} type="button" size="sm"
                  variant={workFilter === filter ? "default" : "outline"}
                  aria-pressed={workFilter === filter}
                  onClick={() => { setWorkFilter(filter); setSelectedRunId(null); setVerifiedRun(null); setContextMessage(""); }}>
                  {filter === "all" ? "All work" : filter === "active" ? "In progress" : filter === "completed" ? "Completed" : "Failed or cancelled"}
                </Button>
              ))}
            </div>
            <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_minmax(0,2fr)]">
              <div className="space-y-2" aria-label="Execution list">
                {isLoadingRuns && !runsGeneratedAt && !runsError ? <p role="status" className="text-sm text-muted-foreground">Loading verified work…</p> : runsError ? <p className="text-sm text-muted-foreground">Execution history is unavailable. Refresh runtime to try again.</p> :
                  visibleRuns.length ? visibleRuns.map((run) => (
                    <button type="button" key={run.run_id}
                      className="w-full rounded-lg border border-border p-3 text-left hover:bg-muted/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                      aria-pressed={selectedRunId === run.run_id}
                      onClick={() => setSelectedRunId(run.run_id)}>
                      <span className="block text-sm font-medium">Execution {run.run_id.slice(0, 8)}</span>
                      <span className="text-xs text-muted-foreground">{run.status} · {formatTimestamp(run.started_at)}</span>
                    </button>
                  )) : <div className="rounded-lg border p-4 space-y-2 text-sm text-muted-foreground"><p>{workFilter === "active" ? "No work is currently in progress." : workFilter === "completed" ? "No completed executions are recorded." : workFilter === "failed" ? "No failed or cancelled executions are recorded." : "No verified executions match this view."}</p><p>{workFilter === "all" ? "Use Ask Karen to describe an objective. Verified agent executions will appear here when recorded." : "Choose All work to review other execution states, or use Ask Karen to start a new objective."}</p></div>}
              </div>
              <div className="rounded-xl border border-border p-4" aria-label="Selected execution details">
                {runsError ? <p className="text-sm text-muted-foreground">Execution details unavailable until history is verified.</p> : runDetailError ? <p role="alert" className="text-sm text-destructive">{runDetailError}</p> : selectedRun ? (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h4 className="font-semibold">Execution details</h4>
                      <Badge variant={statusVariant(selectedRun.status)}>{selectedRun.status}</Badge>
                    </div>
                    {(isRevalidatingRun || isLoadingRuns) && <p role="status" className="mt-2 text-xs text-muted-foreground">Revalidating execution status…</p>}
                    <p className="mt-2 text-sm text-muted-foreground">Started {formatTimestamp(selectedRun.started_at)}</p>
                    {selectedRun.completed_at && <p className="mt-1 text-sm text-muted-foreground">Ended {formatTimestamp(selectedRun.completed_at)}</p>}
                    <p className="mt-2 text-sm text-muted-foreground">{selectedRun.status.toLowerCase() === "completed" ? "Execution completed. A saved artifact is not implied by this status." : selectedRun.status.toLowerCase() === "cancelling" ? "Cancellation requested, awaiting confirmed terminal status." : "This status comes from the Medusa run ledger, not a simulated progress estimate."}</p>
                    {selectedRun.error_type && <p role="alert" className="mt-3 text-sm text-destructive">Reported failure: {selectedRun.error_type}</p>}
                    <details className="mt-4 text-sm">
                      <summary className="cursor-pointer font-medium">Technical details</summary>
                      <dl className="mt-2 space-y-2 text-xs text-muted-foreground">
                        <div><dt>Run ID</dt><dd className="break-all">{selectedRun.run_id}</dd></div>
                        <div><dt>Correlation ID</dt><dd className="break-all">{selectedRun.correlation_id || "Not recorded"}</dd></div>
                        <div><dt>Response source</dt><dd>{selectedRun.response_source || "Not recorded"}</dd></div>
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
                        disabled={isRevalidatingRun || isLoadingRuns || cancellingRunId !== null}
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

      <section aria-label="Needs your review" className="space-y-3" data-testid="agent-runtime-approvals">
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

      <details className="rounded-lg border border-border p-3 text-sm"><summary className="cursor-pointer font-medium">Runtime architecture and authorization</summary><Alert className="mt-3">
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
          <AlertTitle>Runtime action accepted</AlertTitle>
          <AlertDescription>{actionMessage}</AlertDescription>
        </Alert>
      )}

      <details className="space-y-3 rounded-lg border border-border p-3"><summary className="cursor-pointer font-medium">Registered specialists and diagnostics</summary><section className="mt-3 space-y-3">
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
      </section></details>

      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer font-medium">Administrative execution diagnostics</summary><section className="mt-3 space-y-3">
        <div className="flex items-center gap-2">
          <Workflow className="h-5 w-5 text-primary" />
          <div>
            <h3 className="text-lg font-semibold">Execution control</h3>
            <p className="text-sm text-muted-foreground">
              {isAdmin
                ? "Tenant-scoped Medusa run history and cancellation authority."
                : "Run-level operational controls are available only in the authorized tenant administration workspace. Your chat still uses Medusa automatically when policy selects multi-agent execution."}
            </p>
          </div>
        </div>

        {!isAdmin ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              Agent execution activity is surfaced directly in Chat when a
              multi-agent plan runs. Administrative run history is intentionally
              excluded from personal work.
            </CardContent>
          </Card>
        ) : (
          <>
            {runsError && (
              <Alert variant="destructive">
                <AlertTitle>Run control unavailable</AlertTitle>
                <AlertDescription>{runsError}</AlertDescription>
              </Alert>
            )}

            <div className="grid gap-3 md:grid-cols-3">
              <Card>
                <CardHeader className="pb-2">
                  <CardDescription>Total visible runs</CardDescription>
                  <CardTitle>{runsError ? "Unavailable" : !runsGeneratedAt ? "Loading" : runs.length}</CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardDescription>Active runs</CardDescription>
                  <CardTitle>{runsError ? "Unavailable" : !runsGeneratedAt ? "Loading" : activeRuns.length}</CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardDescription>Registered specialists</CardDescription>
                  <CardTitle>{isLoadingCatalog ? "Loading" : catalogError || !catalog ? "Unavailable" : catalog.total}</CardTitle>
                </CardHeader>
              </Card>
            </div>

            {isLoadingRuns && !runsGeneratedAt && !runsError ? (
              <Card>
                <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Loading Medusa run history…
                </CardContent>
              </Card>
            ) : runsError ? (
              <p className="text-sm text-muted-foreground">Run history is unavailable. Refresh runtime to try again.</p>
            ) : runs.length ? (
              <div className="space-y-3">
                {runs.map((run) => (
                  <Card key={run.run_id} data-run-id={run.run_id}>
                    <CardHeader>
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <CardTitle className="break-all text-sm">
                            {run.run_id}
                          </CardTitle>
                          <CardDescription>
                            Started {formatTimestamp(run.started_at)}
                          </CardDescription>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Badge variant={statusVariant(run.status)}>
                            {run.status}
                          </Badge>
                          {run.durable && <Badge variant="outline">durable</Badge>}
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <dl className="grid gap-2 text-xs text-muted-foreground md:grid-cols-2 xl:grid-cols-3">
                        <div>
                          <dt className="font-medium text-foreground">User</dt>
                          <dd className="break-all">{run.user_id || "Unknown"}</dd>
                        </div>
                        <div>
                          <dt className="font-medium text-foreground">Session</dt>
                          <dd className="break-all">{run.session_id || "Unknown"}</dd>
                        </div>
                        <div>
                          <dt className="font-medium text-foreground">Policy decision</dt>
                          <dd className="break-all">
                            {run.policy_decision_id || "Not recorded"}
                          </dd>
                        </div>
                        <div>
                          <dt className="font-medium text-foreground">Correlation ID</dt>
                          <dd className="break-all">
                            {run.correlation_id || "Not recorded"}
                          </dd>
                        </div>
                        <div>
                          <dt className="font-medium text-foreground">Completed</dt>
                          <dd>{formatTimestamp(run.completed_at)}</dd>
                        </div>
                        <div>
                          <dt className="font-medium text-foreground">Response source</dt>
                          <dd>{run.response_source || "Not recorded"}</dd>
                        </div>
                      </dl>

                      {run.error_type && (
                        <Alert variant="destructive">
                          <AlertTitle>Run failure</AlertTitle>
                          <AlertDescription>{run.error_type}</AlertDescription>
                        </Alert>
                      )}

                      {run.cancellable && (
                        <Button
                          type="button"
                          variant="destructive"
                          size="sm"
                          disabled={isLoadingRuns || cancellingRunId !== null}
                          onClick={() => void cancelRun(run.run_id)}
                        >
                          <CircleStop className="mr-2 h-4 w-4" />
                          {cancellingRunId === run.run_id
                            ? "Requesting cancellation…"
                            : "Cancel run"}
                        </Button>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            ) : (
              <Card>
                <CardContent className="p-6 text-sm text-muted-foreground">
                  No Medusa execution runs are visible for this tenant.
                </CardContent>
              </Card>
            )}
          </>
        )}
      </section></details>
    </div>
  );
}
