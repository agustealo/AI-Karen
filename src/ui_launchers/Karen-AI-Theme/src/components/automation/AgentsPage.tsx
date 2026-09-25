"use client";

import { useCallback, useEffect, useState } from "react";
import useAuth from "@/lib/useAuth";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Activity,
  AlertTriangle,
  Bot,
  PlusCircle,
  Settings,
  ShieldCheck,
  Trash2,
  Wrench,
} from "lucide-react";

type AgentExecutionMode = "native" | "langgraph" | "deep_agents";

interface AgentRecord {
  agent_id: string;
  name: string;
  description: string;
  execution_mode: AgentExecutionMode;
  status: string;
  capabilities: string[];
  config: {
    custom_config?: {
      tools?: string[];
    };
    [key: string]: unknown;
  };
  metrics?: Record<string, unknown>;
  created_at?: string;
  last_activity?: string | null;
  version?: string;
  is_healthy?: boolean;
  is_available?: boolean;
}

interface SystemMetrics {
  [key: string]: unknown;
}

interface ToolRecord {
  name: string;
  description: string;
  category: string;
  version: string;
  author: string;
  enabled: boolean;
  tags?: string[];
}

interface PluginRecord {
  id: string;
  name: string;
  display_name?: string;
  description: string;
  category?: string;
  status: string;
  version: string;
  tags?: string[];
}

interface ToolOption {
  id: string;
  label: string;
  description?: string;
  source: "system" | "plugin";
  group: string;
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "Not yet recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function renderMetricValue(value: unknown): string {
  if (value == null) return "None";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export default function AgentsPage() {
  const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics | null>(null);
  const [availableToolGroups, setAvailableToolGroups] = useState<
    Array<[string, ToolOption[]]>
  >([]);
  const [installedPlugins, setInstalledPlugins] = useState<PluginRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [noticeMsg, setNoticeMsg] = useState("");

  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentDescription, setNewAgentDescription] = useState("");
  const [newAgentExecutionMode, setNewAgentExecutionMode] =
    useState<AgentExecutionMode>("native");
  const [newAgentTools, setNewAgentTools] = useState<string[]>([]);

  const isAdmin = user?.roles?.includes("admin") ?? false;

  const isTransientAuthOrRuntimeError = useCallback(
    (message: string): boolean => {
      const lower = message.toLowerCase();
      return (
        lower.includes("database unavailable") ||
        lower.includes("session not found in memory") ||
        lower.includes("503") ||
        lower.includes("gateway") ||
        lower.includes("timeout")
      );
    },
    [],
  );

  const resetCreateForm = () => {
    setNewAgentName("");
    setNewAgentDescription("");
    setNewAgentExecutionMode("native");
    setNewAgentTools([]);
  };

  const loadToolInventory = useCallback(async () => {
    try {
      const { apiClient } = await import("@/lib/api");

      const [toolsResponse, pluginsResponse, publicPluginsResponse] =
        await Promise.allSettled([
          apiClient.get<{ tools?: ToolRecord[] }>("/api/tools"),
          apiClient.get<{ plugins?: PluginRecord[] }>("/api/plugins"),
          apiClient.get<{ plugins?: PluginRecord[] }>("/api/public/plugins"),
        ]);

      const nextGroups = new Map<string, ToolOption[]>();

      if (toolsResponse.status === "fulfilled") {
        for (const tool of toolsResponse.value?.tools || []) {
          const category = tool.category?.trim() || "General Tools";
          const next = nextGroups.get(category) || [];
          next.push({
            id: tool.name,
            label: tool.name,
            description: tool.description,
            source: "system",
            group: category,
          });
          nextGroups.set(category, next);
        }
      }

      let pluginSource: PluginRecord[] = [];
      if (pluginsResponse.status === "fulfilled") {
        pluginSource = pluginsResponse.value?.plugins || [];
      } else if (publicPluginsResponse.status === "fulfilled") {
        pluginSource = publicPluginsResponse.value?.plugins || [];
      }

      const installed = pluginSource
        .filter((plugin) => plugin.status === "installed")
        .sort((left, right) =>
          (left.display_name || left.name).localeCompare(
            right.display_name || right.name,
          ),
        );

      setInstalledPlugins(installed);

      for (const plugin of installed) {
        const category = plugin.category?.trim() || "Plugins";
        const next = nextGroups.get(category) || [];
        next.push({
          id: plugin.name,
          label: plugin.display_name || plugin.name,
          description: plugin.description,
          source: "plugin",
          group: category,
        });
        nextGroups.set(category, next);
      }

      const grouped: [string, ToolOption[]][] = [];
      for (const [groupName, tools] of nextGroups.entries()) {
        grouped.push([
          groupName,
          tools.sort((left, right) => left.label.localeCompare(right.label)),
        ]);
      }

      grouped.sort((left, right) => left[0].localeCompare(right[0]));
      setAvailableToolGroups(grouped);
    } catch (err) {
      console.error("Failed to load tools/plugins:", err);
      setAvailableToolGroups([]);
      setInstalledPlugins([]);
    }
  }, []);

  const fetchAgents = useCallback(async () => {
    if (!isAuthenticated) {
      setAgents([]);
      setSystemMetrics(null);
      setErrorMsg(
        "Authentication is temporarily unavailable. Please retry in a moment.",
      );
      setIsLoading(false);
      return;
    }

    // The legacy registry is installation-wide and has no tenant identifier.
    // Do not call its catalog/metrics endpoints from a non-admin user surface.
    if (!isAdmin) {
      setAgents([]);
      setSystemMetrics(null);
      setAvailableToolGroups([]);
      setInstalledPlugins([]);
      setErrorMsg("");
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setErrorMsg("");
    try {
      const { apiClient } = await import("@/lib/api");
      const data = await apiClient.get<AgentRecord[]>("/api/agents");
      setAgents(data || []);

      try {
        const metrics = await apiClient.get<SystemMetrics>(
          "/api/agents/system/metrics",
        );
        setSystemMetrics(metrics);
      } catch {
        setSystemMetrics(null);
      }
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch agents.";
      console.error(err);
      setErrorMsg(
        isTransientAuthOrRuntimeError(message)
          ? "Agent system is temporarily unavailable (runtime/auth dependency degraded). Please retry shortly."
          : message,
      );
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated, isAdmin, isTransientAuthOrRuntimeError]);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    void fetchAgents();

    if (isAuthenticated && isAdmin) {
      void loadToolInventory();
    } else {
      setAvailableToolGroups([]);
      setInstalledPlugins([]);
    }
  }, [
    isAuthenticated,
    isAdmin,
    isAuthLoading,
    fetchAgents,
    loadToolInventory,
  ]);

  const handleCreateAgent = async () => {
    if (!isAuthenticated || !isAdmin) {
      setErrorMsg(
        isAuthenticated
          ? "Admin access is required to create agents."
          : "Sign in to manage agents.",
      );
      return;
    }

    const trimmedName = newAgentName.trim();
    const trimmedDescription = newAgentDescription.trim();
    if (!trimmedName || !trimmedDescription) {
      setErrorMsg("Name and description are required.");
      return;
    }

    setIsSaving(true);
    setErrorMsg("");
    setNoticeMsg("");

    try {
      const { apiClient } = await import("@/lib/api");
      const slug = trimmedName
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
      const agentId = `agent_${slug || "custom"}_${Date.now()}`;

      await apiClient.post<AgentRecord>("/api/agents/", {
        agent_id: agentId,
        name: trimmedName,
        description: trimmedDescription,
        execution_mode: newAgentExecutionMode,
        config: {
          execution_mode: newAgentExecutionMode,
          capabilities: ["text_generation", "tool_use"],
          enable_streaming: true,
          custom_config: {
            tools: newAgentTools,
          },
        },
      });

      setNoticeMsg(`Created agent ${trimmedName}.`);
      resetCreateForm();
      await fetchAgents();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setErrorMsg(`Failed to create agent: ${message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteAgent = async (agentId: string) => {
    if (!isAuthenticated || !isAdmin) {
      setErrorMsg(
        isAuthenticated
          ? "Admin access is required to delete agents."
          : "Sign in to manage agents.",
      );
      return;
    }
    if (!confirm(`Delete agent ${agentId}?`)) {
      return;
    }

    try {
      const { apiClient } = await import("@/lib/api");
      await apiClient.delete(`/api/agents/${agentId}`);
      setNoticeMsg(`Deleted agent ${agentId}.`);
      await fetchAgents();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setErrorMsg(`Failed to delete agent: ${message}`);
    }
  };

  const handleTerminateAgent = async (agentId: string) => {
    if (!isAuthenticated || !isAdmin) {
      setErrorMsg(
        isAuthenticated
          ? "Admin access is required to terminate agents."
          : "Sign in to manage agents.",
      );
      return;
    }

    try {
      const { apiClient } = await import("@/lib/api");
      await apiClient.post(`/api/agents/${agentId}/terminate`);
      setNoticeMsg(`Termination requested for ${agentId}.`);
      await fetchAgents();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setErrorMsg(`Failed to terminate agent: ${message}`);
    }
  };

  const addTool = (tool: string) => {
    if (!newAgentTools.includes(tool)) {
      setNewAgentTools((current) => [...current, tool]);
    }
  };

  const removeTool = (tool: string) => {
    setNewAgentTools((current) => current.filter((item) => item !== tool));
  };

  if (!isAuthLoading && isAuthenticated && !isAdmin) {
    return (
      <div className="space-y-8">
        <div className="flex items-center space-x-3">
          <Bot className="h-8 w-8 text-primary" />
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              Agent Management
            </h2>
            <p className="text-sm text-muted-foreground">
              Installation control-plane management for the legacy agent
              registry.
            </p>
          </div>
        </div>

        <Alert>
          <ShieldCheck className="h-4 w-4" />
          <AlertTitle>Administrator Control Plane</AlertTitle>
          <AlertDescription>
            The legacy agent registry is installation-wide, so its catalog,
            configuration, metrics, and lifecycle controls are restricted to
            administrators. Authorized agent execution remains available
            through KAREN runtime surfaces.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center space-x-3">
        <Bot className="h-8 w-8 text-primary" />
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">
            Agent Management
          </h2>
          <p className="text-sm text-muted-foreground">
            Manage the installation-wide agent registry and its backend
            lifecycle controls.
          </p>
        </div>
      </div>

      {errorMsg && (
        <Alert variant="destructive">
          <AlertTitle>Error Loading Agents</AlertTitle>
          <AlertDescription>{errorMsg}</AlertDescription>
        </Alert>
      )}

      {noticeMsg && (
        <Alert>
          <AlertTitle>Registry Update</AlertTitle>
          <AlertDescription>{noticeMsg}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Available Agents</h3>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void fetchAgents()}
              disabled={isAuthLoading || !isAuthenticated || !isAdmin}
            >
              Refresh
            </Button>
          </div>

          {systemMetrics && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Activity className="h-4 w-4 text-primary" />
                  System Metrics
                </CardTitle>
                <CardDescription>
                  Backend integration metrics for the installation-wide agent
                  registry.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
                {Object.entries(systemMetrics).map(([key, value]) => (
                  <div
                    key={key}
                    className="rounded-md border bg-muted/20 p-3"
                  >
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">
                      {key.replace(/_/g, " ")}
                    </div>
                    <div className="mt-1 break-all font-medium">
                      {renderMetricValue(value)}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {isAuthLoading ? (
            <div className="p-8 text-center text-muted-foreground animate-pulse">
              Restoring your session...
            </div>
          ) : isLoading ? (
            <div className="p-8 text-center text-muted-foreground animate-pulse">
              Loading agents from registry...
            </div>
          ) : !isAuthenticated ? (
            <div className="rounded-xl border bg-muted/20 p-8 text-center text-muted-foreground">
              Sign in with an administrator account to manage the installation
              agent registry.
            </div>
          ) : agents.length === 0 ? (
            <div className="rounded-xl border bg-muted/20 p-8 text-center text-muted-foreground">
              No agents found in the registry.
            </div>
          ) : (
            agents.map((agent) => {
              const tools =
                agent.config?.custom_config?.tools || agent.capabilities || [];
              const availabilityLabel = agent.is_available
                ? "Available"
                : "Unavailable";

              return (
                <Card key={agent.agent_id}>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                          <span>{agent.name}</span>
                          <Badge variant="default" className="text-xs">
                            {agent.status || "Unknown"}
                          </Badge>
                          <Badge
                            variant={
                              agent.is_healthy ? "outline" : "destructive"
                            }
                            className="text-xs"
                          >
                            {agent.is_healthy ? "Healthy" : "Unhealthy"}
                          </Badge>
                          <Badge variant="secondary" className="text-xs">
                            {availabilityLabel}
                          </Badge>
                        </CardTitle>
                        <CardDescription className="mt-1 text-xs">
                          {agent.description}
                        </CardDescription>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={!isAdmin}
                          onClick={() => void handleTerminateAgent(agent.agent_id)}
                          title="Terminate agent"
                        >
                          <Settings className="h-4 w-4 text-muted-foreground" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={!isAdmin}
                          onClick={() => void handleDeleteAgent(agent.agent_id)}
                          title="Delete agent"
                        >
                          <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                        </Button>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
                      <div className="rounded-md border bg-muted/20 p-3">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground">
                          Execution Mode
                        </div>
                        <div className="mt-1 font-medium">
                          {agent.execution_mode}
                        </div>
                      </div>
                      <div className="rounded-md border bg-muted/20 p-3">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground">
                          Version
                        </div>
                        <div className="mt-1 font-medium">
                          {agent.version || "Unknown"}
                        </div>
                      </div>
                      <div className="rounded-md border bg-muted/20 p-3">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground">
                          Created
                        </div>
                        <div className="mt-1 font-medium">
                          {formatTimestamp(agent.created_at)}
                        </div>
                      </div>
                      <div className="rounded-md border bg-muted/20 p-3">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground">
                          Last Activity
                        </div>
                        <div className="mt-1 font-medium">
                          {formatTimestamp(agent.last_activity)}
                        </div>
                      </div>
                    </div>

                    <div>
                      <Label className="text-xs font-semibold">
                        Capabilities / Tools
                      </Label>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {tools.length === 0 && (
                          <span className="text-xs text-muted-foreground">
                            No explicit capabilities exposed.
                          </span>
                        )}
                        {tools.map((tool) => (
                          <div
                            key={tool}
                            className="flex items-center gap-2 rounded-md border bg-muted p-1 px-2 text-xs"
                          >
                            <Wrench className="h-3 w-3 text-muted-foreground" />
                            <code className="font-mono text-xs text-foreground">
                              {tool}
                            </code>
                          </div>
                        ))}
                      </div>
                    </div>

                    {agent.metrics && Object.keys(agent.metrics).length > 0 && (
                      <div>
                        <Label className="text-xs font-semibold">Metrics</Label>
                        <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
                          {Object.entries(agent.metrics).map(([key, value]) => (
                            <div
                              key={key}
                              className="rounded-md border bg-muted/20 p-2 text-xs"
                            >
                              <div className="uppercase tracking-wide text-muted-foreground">
                                {key.replace(/_/g, " ")}
                              </div>
                              <div className="mt-1 break-all">
                                {renderMetricValue(value)}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })
          )}
        </div>

        <div className="lg:col-span-1">
          <Card className="sticky top-20">
            <CardHeader>
              <CardTitle className="text-lg">Create New Agent</CardTitle>
              <CardDescription>
                Register an installation-wide backend agent with its execution
                mode and tool set.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="agent-name">Agent Name</Label>
                <Input
                  id="agent-name"
                  placeholder="e.g., Research Assistant Agent"
                  value={newAgentName}
                  onChange={(event) => setNewAgentName(event.target.value)}
                  disabled={!isAuthenticated || !isAdmin || isSaving}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="agent-description">Description</Label>
                <Textarea
                  id="agent-description"
                  placeholder="Describe what this agent does."
                  rows={3}
                  value={newAgentDescription}
                  onChange={(event) =>
                    setNewAgentDescription(event.target.value)
                  }
                  disabled={!isAuthenticated || !isAdmin || isSaving}
                />
              </div>

              <div className="space-y-1.5">
                <Label>Execution Mode</Label>
                <Select
                  value={newAgentExecutionMode}
                  onValueChange={(value: AgentExecutionMode) =>
                    setNewAgentExecutionMode(value)
                  }
                  disabled={!isAuthenticated || !isAdmin || isSaving}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select an execution mode" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="native">native</SelectItem>
                    <SelectItem value="langgraph">langgraph</SelectItem>
                    <SelectItem value="deep_agents">deep_agents</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Assigned Tools</Label>
                <div className="min-h-24 space-y-2 rounded-md border bg-muted/30 p-3">
                  {newAgentTools.length === 0 ? (
                    <p className="py-1 text-center text-xs text-muted-foreground">
                      No tools assigned.
                    </p>
                  ) : (
                    newAgentTools.map((tool) => (
                      <div
                        key={tool}
                        className="flex items-center space-x-2 rounded-md border bg-background p-2"
                      >
                        <Wrench className="h-4 w-4 text-muted-foreground" />
                        <code className="flex-1 font-mono text-sm">{tool}</code>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6"
                          disabled={!isAuthenticated || !isAdmin || isSaving}
                          onClick={() => removeTool(tool)}
                        >
                          <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="space-y-3">
                <Label>Available Tools</Label>
                {availableToolGroups.length === 0 ? (
                  <div className="rounded-md border bg-muted/20 p-3">
                    <p className="text-xs text-muted-foreground">
                      No live tools were returned by the backend registry.
                    </p>
                  </div>
                ) : (
                  availableToolGroups.map(([groupName, tools]) => (
                    <div key={groupName} className="rounded-md border p-3">
                      <div className="mb-2 text-sm font-medium">{groupName}</div>
                      <div className="space-y-2">
                        {tools.map((tool) => {
                          const assigned = newAgentTools.includes(tool.id);
                          return (
                            <Button
                              key={`${tool.source}:${tool.id}`}
                              type="button"
                              variant={assigned ? "secondary" : "outline"}
                              className="w-full justify-between gap-3"
                              disabled={
                                !isAuthenticated ||
                                !isAdmin ||
                                isSaving ||
                                assigned
                              }
                              onClick={() => addTool(tool.id)}
                            >
                              <span className="flex min-w-0 flex-col items-start text-left">
                                <span className="break-all font-mono text-xs">
                                  {tool.label}
                                </span>
                                {tool.description && (
                                  <span className="line-clamp-2 text-[11px] text-muted-foreground">
                                    {tool.description}
                                  </span>
                                )}
                              </span>
                              <span className="flex shrink-0 items-center gap-2">
                                <Badge
                                  variant={
                                    tool.source === "system"
                                      ? "default"
                                      : "secondary"
                                  }
                                  className="text-[10px]"
                                >
                                  {tool.source}
                                </Badge>
                                <span>{assigned ? "Assigned" : "Add"}</span>
                              </span>
                            </Button>
                          );
                        })}
                      </div>
                    </div>
                  ))
                )}

                <div className="space-y-2 rounded-md border bg-muted/20 p-3">
                  <div className="text-sm font-medium">Installed Plugins</div>
                  {installedPlugins.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      No installed plugins were returned by the backend.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {installedPlugins.map((plugin) => (
                        <div
                          key={plugin.id}
                          className="flex items-start justify-between gap-3 rounded-md border bg-background p-2"
                        >
                          <div className="min-w-0">
                            <div className="text-sm font-medium">
                              {plugin.display_name || plugin.name}
                            </div>
                            <div className="line-clamp-2 text-xs text-muted-foreground">
                              {plugin.description}
                            </div>
                          </div>
                          <Badge variant="secondary" className="shrink-0">
                            {plugin.status}
                          </Badge>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </CardContent>
            <CardFooter>
              <Button
                className="w-full"
                onClick={() => void handleCreateAgent()}
                disabled={!isAuthenticated || !isAdmin || isSaving}
              >
                <PlusCircle className="mr-2 h-4 w-4" />
                {isSaving ? "Creating Agent..." : "Create and Register Agent"}
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>

      {!isAuthenticated && !isAuthLoading && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Authentication Required</AlertTitle>
          <AlertDescription>
            The dashboard is protected. Sign in with an administrator account
            to use Agent Management.
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
