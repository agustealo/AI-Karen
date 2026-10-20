"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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

interface AgentCatalogRecord {
  agent_id: string;
  name: string;
  description: string;
  version: string;
  lifecycle_state: string;
  status: string;
  capabilities: string[];
  implementation_id?: string | null;
  prompt_contract_id?: string | null;
  prompt_version?: string | null;
  healthy: boolean;
  missing_dependencies: string[];
  eligibility: "runtime_decided_per_request";
}

interface AgentCatalogResponse {
  agents: AgentCatalogRecord[];
  total: number;
  selection_authority: string;
  execution_authority: string;
  orchestrator: string;
}

interface AgentRunRecord {
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

interface RuntimeApproval {
  approval_id: string;
  conversation_id?: string | null;
  intent: string;
  risk_level: string;
  reason_codes: string[];
  status: string;
  expires_at: string;
}

interface AgentRunsResponse {
  runs: AgentRunRecord[];
  total: number;
  generated_at: string;
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

export default function AgentsPage({ onAskKaren }: { onAskKaren?: () => void }) {
  const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();
  const isAdmin = user?.roles?.includes("admin") ?? false;

  const [catalog, setCatalog] = useState<AgentCatalogResponse | null>(null);
  const [runs, setRuns] = useState<AgentRunRecord[]>([]);
  const [approvals, setApprovals] = useState<RuntimeApproval[]>([]);
  const [approvalsError, setApprovalsError] = useState("");
  const [decidingApprovalId, setDecidingApprovalId] = useState<string | null>(null);
  const [isLoadingCatalog, setIsLoadingCatalog] = useState(true);
  const [isLoadingRuns, setIsLoadingRuns] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [runsError, setRunsError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [workFilter, setWorkFilter] = useState<"all" | "active" | "completed" | "failed">("all");

  const activeRuns = useMemo(
    () =>
      runs.filter((run) =>
        ["running", "cancelling"].includes(run.status.toLowerCase()),
      ),
    [runs],
  );

  const selectedRun = runs.find((run) => run.run_id === selectedRunId) ?? runs[0] ?? null;
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
      const response = await apiClient.get<AgentCatalogResponse>(
        "/api/agent-runtime/catalog",
      );
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

  const loadRuns = useCallback(async () => {
    if (!isAuthenticated) {
      setRuns([]);
      setRunsError("");
      return;
    }

    setIsLoadingRuns(true);
    setRunsError("");
    try {
      const response = await apiClient.get<AgentRunsResponse>(
        isAdmin ? "/api/admin/agents/runs?include_terminal=true" : "/api/agent-runtime/my-runs",
      );
      setRuns(response.runs || []);
    } catch (error) {
      setRuns([]);
      setRunsError(
        error instanceof Error
          ? error.message
          : "Failed to load tenant-scoped Medusa runs.",
      );
    } finally {
      setIsLoadingRuns(false);
    }
  }, [isAuthenticated, isAdmin]);

  const loadApprovals = useCallback(async () => {
    if (!isAuthenticated) {
      setApprovals([]);
      return;
    }
    try {
      const records = await apiClient.get<RuntimeApproval[]>("/api/approvals/");
      setApprovals(records);
      setApprovalsError("");
    } catch (error) {
      setApprovals([]);
      setApprovalsError(error instanceof Error ? error.message : "Could not load approval requests.");
    }
  }, [isAuthenticated]);

  const decideApproval = useCallback(async (approvalId: string, decision: "approved" | "rejected") => {
    setDecidingApprovalId(approvalId);
    setApprovalsError("");
    try {
      const result = await apiClient.post<RuntimeApproval>(
        `/api/approvals/${encodeURIComponent(approvalId)}/decision`,
        { decision },
      );
      setActionMessage(
        result.status === decision
          ? `Decision recorded: ${decision}. Karen must still revalidate and resume the original request.`
          : `Approval status: ${result.status}. No action has been executed by this decision.`,
      );
      await loadApprovals();
    } catch (error) {
      setApprovalsError(error instanceof Error ? error.message : "Approval decision was not recorded.");
    } finally {
      setDecidingApprovalId(null);
    }
  }, [loadApprovals]);

  const refresh = useCallback(async () => {
    setActionMessage("");
    await Promise.all([loadCatalog(), loadRuns(), loadApprovals()]);
  }, [loadCatalog, loadRuns, loadApprovals]);

  useEffect(() => {
    if (isAuthLoading) return;
    void refresh();
  }, [isAuthLoading, refresh]);

  const cancelRun = useCallback(
    async (runId: string) => {
      if (!isAdmin) return;

      setCancellingRunId(runId);
      setActionMessage("");
      setRunsError("");
      try {
        const response = await apiClient.post<AgentRunRecord>(
          `/api/admin/agents/runs/${encodeURIComponent(runId)}/cancel`,
        );
        setActionMessage(
          `Cancellation requested for ${runId}. Runtime status: ${response.status}.`,
        );
        await loadRuns();
      } catch (error) {
        setRunsError(
          error instanceof Error
            ? error.message
            : `Failed to cancel Medusa run ${runId}.`,
        );
      } finally {
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
            <h3 className="text-lg font-semibold">Your AI workspace</h3>
            <p className="text-sm text-muted-foreground">Ask Karen to work on a goal, then return to review real progress and results.</p>
          </div>
          <Button type="button" onClick={onAskKaren} disabled={!onAskKaren}>
            <Bot className="mr-2 h-4 w-4" /> Ask Karen
          </Button>
        </div>
        {isAuthenticated ? (
          <>
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
                {isLoadingRuns ? <p className="text-sm text-muted-foreground">Loading verified work…</p> :
                  visibleRuns.length ? visibleRuns.map((run) => (
                    <button type="button" key={run.run_id}
                      className="w-full rounded-lg border border-border p-3 text-left hover:bg-muted/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                      aria-pressed={selectedRun?.run_id === run.run_id}
                      onClick={() => setSelectedRunId(run.run_id)}>
                      <span className="block text-sm font-medium">Execution {run.run_id.slice(0, 8)}</span>
                      <span className="text-xs text-muted-foreground">{run.status} · {formatTimestamp(run.started_at)}</span>
                    </button>
                  )) : <p className="rounded-lg border p-4 text-sm text-muted-foreground">No verified executions match this view.</p>}
              </div>
              <div className="rounded-xl border border-border p-4" aria-label="Selected execution details">
                {selectedRun ? (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h4 className="font-semibold">Execution details</h4>
                      <Badge variant={statusVariant(selectedRun.status)}>{selectedRun.status}</Badge>
                    </div>
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
                    {selectedRun.cancellable && (
                      <Button className="mt-4" variant="destructive" size="sm"
                        disabled={cancellingRunId === selectedRun.run_id}
                        onClick={() => void cancelRun(selectedRun.run_id)}>
                        <CircleStop className="mr-2 h-4 w-4" /> Request cancellation
                      </Button>
                    )}
                  </>
                ) : <p className="text-sm text-muted-foreground">Select an execution to inspect its verified status.</p>}
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
        <p className="text-sm text-muted-foreground">These requests come from Karen's authorized approval service. A decision alone does not execute an action.</p>
        {approvalsError && <p role="alert" className="text-sm text-destructive">{approvalsError}</p>}
        {approvals.length === 0 && !approvalsError ? (
          <p className="rounded-lg border p-4 text-sm text-muted-foreground">No actionable approval requests are available.</p>
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
              {onAskKaren && <Button size="sm" variant="outline" onClick={onAskKaren}>Open Karen chat</Button>}
              <Button size="sm" disabled={decidingApprovalId !== null}
                onClick={() => void decideApproval(approval.approval_id, "approved")}>Approve</Button>
              <Button size="sm" variant="outline" disabled={decidingApprovalId !== null}
                onClick={() => void decideApproval(approval.approval_id, "rejected")}>Reject</Button>
            </div>
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
                  <CardDescription>{agent.description}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    {agent.capabilities.map((capability) => (
                      <Badge key={capability} variant="secondary">
                        {capability}
                      </Badge>
                    ))}
                  </div>

                  <dl className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                    <div>
                      <dt className="font-medium text-foreground">Agent ID</dt>
                      <dd className="break-all">{agent.agent_id}</dd>
                    </div>
                    <div>
                      <dt className="font-medium text-foreground">Version</dt>
                      <dd>{agent.version}</dd>
                    </div>
                    <div>
                      <dt className="font-medium text-foreground">Implementation</dt>
                      <dd className="break-all">{agent.implementation_id || "Not exposed"}</dd>
                    </div>
                    <div>
                      <dt className="font-medium text-foreground">Prompt contract</dt>
                      <dd className="break-all">
                        {agent.prompt_contract_id
                          ? `${agent.prompt_contract_id}@${agent.prompt_version || "unversioned"}`
                          : "Not exposed"}
                      </dd>
                    </div>
                  </dl>

                  {!agent.healthy && agent.missing_dependencies.length > 0 && (
                    <Alert variant="destructive">
                      <AlertTitle>Missing dependencies</AlertTitle>
                      <AlertDescription>
                        {agent.missing_dependencies.join(", ")}
                      </AlertDescription>
                    </Alert>
                  )}
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
                : "Run-level operational controls are administrator-only. Your chat still uses Medusa automatically when policy selects multi-agent execution."}
            </p>
          </div>
        </div>

        {!isAdmin ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              Agent execution activity is surfaced directly in Chat when a
              multi-agent plan runs. Administrative run history is intentionally
              hidden from ordinary users.
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
                  <CardTitle>{runs.length}</CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardDescription>Active runs</CardDescription>
                  <CardTitle>{activeRuns.length}</CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardDescription>Registered specialists</CardDescription>
                  <CardTitle>{catalog?.total ?? 0}</CardTitle>
                </CardHeader>
              </Card>
            </div>

            {isLoadingRuns ? (
              <Card>
                <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Loading Medusa run history…
                </CardContent>
              </Card>
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
                          disabled={cancellingRunId === run.run_id}
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
