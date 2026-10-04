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

export default function AgentsPage() {
  const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();
  const isAdmin = user?.roles?.includes("admin") ?? false;

  const [catalog, setCatalog] = useState<AgentCatalogResponse | null>(null);
  const [runs, setRuns] = useState<AgentRunRecord[]>([]);
  const [isLoadingCatalog, setIsLoadingCatalog] = useState(true);
  const [isLoadingRuns, setIsLoadingRuns] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [runsError, setRunsError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);

  const activeRuns = useMemo(
    () =>
      runs.filter((run) =>
        ["running", "cancelling"].includes(run.status.toLowerCase()),
      ),
    [runs],
  );

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
    if (!isAuthenticated || !isAdmin) {
      setRuns([]);
      setRunsError("");
      return;
    }

    setIsLoadingRuns(true);
    setRunsError("");
    try {
      const response = await apiClient.get<AgentRunsResponse>(
        "/api/admin/agents/runs?include_terminal=true",
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

  const refresh = useCallback(async () => {
    setActionMessage("");
    await Promise.all([loadCatalog(), loadRuns()]);
  }, [loadCatalog, loadRuns]);

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
            <p className="max-w-3xl text-sm text-muted-foreground">
              Agent Medusa is KAREN&apos;s canonical multi-agent coordinator.
              Chat remains the execution entry point: CORTEX decides when
              specialist delegation is required, RuntimePolicy authorizes it,
              and Medusa coordinates only the approved plan.
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

      <Alert>
        <ShieldCheck className="h-4 w-4" />
        <AlertTitle>Canonical ownership</AlertTitle>
        <AlertDescription>
          This surface is read-only for agent definitions. Per-agent daemon
          start/stop controls are intentionally absent. Executions are created
          by ChatRuntime after CORTEX and RuntimePolicy approval; concrete runs
          can be observed and, for administrators, cancelled by run ID.
        </AlertDescription>
      </Alert>

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

      <section className="space-y-3">
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
      </section>

      <section className="space-y-3">
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
      </section>
    </div>
  );
}
