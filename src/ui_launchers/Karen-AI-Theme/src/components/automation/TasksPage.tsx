
"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import useAuth from "@/lib/useAuth";
import { AutomationListNotice } from "@/components/automation/AutomationListNotice";
import { GovernedToolReceiptList, type GovernedToolReceipt } from "./GovernedToolReceipts";
import { AutomationWorkflowHeader } from "@/components/automation/AutomationWorkflowHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ScrollText, PlusCircle, Trash2, Play, Settings, Bot, Info, Users, FileCog, History, ShieldCheck } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

type SubAgent = {
  agentId?: string;
  name: string;
  instructions: string;
};

type AgentOption = {
  agent_id: string;
  name: string;
  description?: string | null;
  status?: string;
  capabilities?: Array<{ name?: string }>;
};

type Task = {
  id: string;
  name: string;
  description?: string;
  acceptanceCriteria?: string;
  verificationContract?: { version: string; schema: Record<string, unknown> };
  instructions?: string;
  agent?: string;
  subAgents?: SubAgent[];
  primaryAgent?: string;
  primaryAgentInstructions?: string;
  taskType?: string;
  lastRun?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  lastError?: string | null;
  runCount?: number;
  runtimeTaskId?: string | null;
  executionId?: string | null;
  resultReceipt?: {
    execution_request_id?: string;
    runtime_status?: string;
    answer_preview?: string;
    answer_text?: string;
    answer_truncated?: boolean;
    attachment_count?: number;
    source_refs_truncated?: boolean;
    sources?: Array<{title?: string | null; url?: string | null}>;
    artifact_count?: number;
    source_count?: number;
    citation_count?: number;
    degraded_mode?: boolean;
    response_id?: string | null;
    correlation_id?: string | null;
    independently_verified?: boolean;
    machine_verification?: {
      status?: "passed" | "failed" | "not_configured";
      reason?: string;
      contract_sha256?: string;
      output_sha256?: string;
    };
  };
  reviewedAt?: string | null;
  reviewedBy?: string | null;
  reviewNote?: string | null;
};

type ReviewHistoryEntry = {
  outcome_id: string;
  execution_id: string;
  decision: "approve" | "reject";
  status: string;
  reviewed_at: string;
  review_note: string;
  acceptance_criteria: string;
  receipt_sha256: string;
  result_receipt?: {
    answer_text?: string;
    answer_truncated?: boolean;
    runtime_status?: string;
    source_count?: number;
    artifact_count?: number;
    attachment_count?: number;
  };
  correlation_id?: string | null;
  human_attestation: boolean;
  independently_verified: boolean;
};

/**
 * @file TasksPage.tsx
 * @description Page for defining and managing Tasks for AI agents via /api/tasks.
 */
export default function TasksPage() {
  const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();
  const principal = isAuthenticated && user?.tenant_id && user.user_id
    ? JSON.stringify([user.tenant_id, user.user_id]) : "";
  const principalRef = useRef(principal);
  principalRef.current = principal;
  const dataRevision = useRef(0);
  const [tasksOwner, setTasksOwner] = useState<string | null>(null);
  const [agentsOwner, setAgentsOwner] = useState<string | null>(null);
  const [formOwner, setFormOwner] = useState(principal);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isAgentsLoading, setIsAgentsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");
  const [tasksFetchError, setTasksFetchError] = useState(false);
  const historyRequestId = useRef(0);
  const toolReceiptRequestId = useRef(0);
  const [openToolReceiptsTask, setOpenToolReceiptsTask] = useState<string | null>(null);
  const [toolReceipts, setToolReceipts] = useState<GovernedToolReceipt[]>([]);
  const [toolReceiptError, setToolReceiptError] = useState("");
  const [toolReceiptsLoading, setToolReceiptsLoading] = useState(false);
  const [openHistoryTask, setOpenHistoryTask] = useState<string | null>(null);
  const [reviewHistory, setReviewHistory] = useState<ReviewHistoryEntry[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [taskName, setTaskName] = useState("");
  const [taskDescription, setTaskDescription] = useState("");
  const [acceptanceCriteria, setAcceptanceCriteria] = useState("");
  const [verificationSchemaJson, setVerificationSchemaJson] = useState("");

  const fetchLiveData = useCallback(async () => {
    const owner = principal;
    if (principalRef.current !== owner) return;
    const revision = ++dataRevision.current;
    if (!owner) {
      setTasks([]); setAgents([]); setTasksOwner(null); setAgentsOwner(null);
      setTasksFetchError(false);
      setErrorMsg("Sign in to manage tasks.");
      setIsLoading(false); setIsAgentsLoading(false);
      return;
    }
    setIsLoading(true); setIsAgentsLoading(true);
    setTasksOwner(null); setAgentsOwner(null);
    historyRequestId.current += 1; toolReceiptRequestId.current += 1;
    setOpenToolReceiptsTask(null); setToolReceipts([]); setToolReceiptError("");
    setOpenHistoryTask(null); setReviewHistory([]); setHistoryError("");
    setErrorMsg(""); setTasksFetchError(false);

    try {
      const { apiClient } = await import("@/lib/api");
      if (principalRef.current !== owner || dataRevision.current !== revision) return;
      const [taskResult, agentResult] = await Promise.allSettled([
        apiClient.get<Task[]>("/api/tasks/"),
        apiClient.get<{ agents?: Array<Omit<AgentOption, "capabilities"> & { capabilities?: string[] }> }>(
          "/api/agent-runtime/catalog",
        ),
      ]);
      if (principalRef.current !== owner || dataRevision.current !== revision) return;
      if (taskResult.status === "fulfilled" && Array.isArray(taskResult.value)) {
        setTasks(taskResult.value);
        setTasksFetchError(false);
      } else {
        setTasks([]); setTasksFetchError(true);
        setErrorMsg(taskResult.status === "rejected" && taskResult.reason instanceof Error
          ? taskResult.reason.message : "Failed to verify task definitions.");
      }
      setTasksOwner(owner);
      if (agentResult.status === "fulfilled" &&
          Array.isArray(agentResult.value?.agents)) {
        setAgents(agentResult.value.agents.map(agent => ({
          ...agent,
          capabilities: (agent.capabilities ?? []).map(name => ({ name })),
        })));
        setAgentsOwner(owner);
      } else {
        setAgents([]); setAgentsOwner(null);
        setErrorMsg(current => current || "Failed to verify available agents.");
      }
    } catch (error) {
      if (principalRef.current !== owner || dataRevision.current !== revision) return;
      setTasks([]); setAgents([]);
      setTasksOwner(owner); setAgentsOwner(null);
      setTasksFetchError(true);
      setErrorMsg(error instanceof Error ? error.message : "Failed to fetch tasks.");
    } finally {
      if (principalRef.current === owner && dataRevision.current === revision) {
        setIsLoading(false); setIsAgentsLoading(false);
      }
    }
  }, [principal]);

  useEffect(() => {
    if (isAuthLoading) return;
    void fetchLiveData();
    return () => {
      dataRevision.current += 1;
      historyRequestId.current += 1;
      toolReceiptRequestId.current += 1;
    };
  }, [isAuthLoading, fetchLiveData]);

  const verifiedTasks = !!principal && tasksOwner === principal;
  const verifiedAgents = !!principal && agentsOwner === principal;

  
  const [newPrimaryAgent, setNewPrimaryAgent] = useState<string>("");
  const [newPrimaryAgentInstructions, setNewPrimaryAgentInstructions] = useState("");
  const [newSubAgents, setNewSubAgents] = useState<SubAgent[]>([]);
  const visibleSubAgents = formOwner === principal ? newSubAgents : [];
  
  // State for the instruction editing dialog
  const [editingConfig, setEditingConfig] = useState<{ agentName: string; instructions: string; onSave: (newInstructions: string) => void; } | null>(null);
  const [tempInstructions, setTempInstructions] = useState("");

  useEffect(() => {
    setFormOwner(principal);
    setTaskName(""); setTaskDescription(""); setAcceptanceCriteria("");
    setVerificationSchemaJson(""); setNewPrimaryAgent("");
    setNewPrimaryAgentInstructions(""); setNewSubAgents([]);
    setEditingConfig(null); setTempInstructions("");
    setOpenHistoryTask(null); setReviewHistory([]); setHistoryError("");
    setOpenToolReceiptsTask(null); setToolReceipts([]); setToolReceiptError("");
  }, [principal]);

  const liveAgents = verifiedAgents ? agents : [];
  const getAgentLabel = (agentId?: string) => {
    if (!agentId) {
      return "Unknown";
    }
    return liveAgents.find((agent) => agent.agent_id === agentId)?.name || agentId;
  };

  const handleAddSubAgent = (agentToAdd: AgentOption) => {
    if (!verifiedAgents || formOwner !== principal) return;
    if (!newSubAgents.some(agent => agent.agentId === agentToAdd.agent_id)) {
      setNewSubAgents([
        ...newSubAgents,
        { agentId: agentToAdd.agent_id, name: agentToAdd.name, instructions: '' },
      ]);
    }
  };

  const handleRemoveSubAgent = (agentToRemove: string) => {
    setNewSubAgents(newSubAgents.filter(agent => agent.agentId !== agentToRemove));
  };
  
  const openInstructionEditor = (agentName: string, instructions: string, onSave: (newInstructions: string) => void) => {
    setTempInstructions(instructions);
    setEditingConfig({ agentName, instructions, onSave });
  };
  
  const handleSaveInstructions = () => {
    if (editingConfig) {
      editingConfig.onSave(tempInstructions);
      setEditingConfig(null);
    }
  };

  const handleDeleteTask = async (taskId: string) => {
    if (!principal || !verifiedTasks) {
      setErrorMsg("Sign in to manage tasks.");
      return;
    }
    if (!confirm("Are you sure you want to delete this task?")) return;
    const actionPrincipal = principal;
    try {
      const { apiClient } = await import('@/lib/api');
      if (principalRef.current !== actionPrincipal) return;
      await apiClient.delete(`/api/tasks/${taskId}`);
      if (principalRef.current !== actionPrincipal) return;
      void fetchLiveData();
    } catch (err: unknown) {
      if (principalRef.current !== actionPrincipal) return;
      alert("Failed to delete task: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleExecuteTask = async (taskId: string) => {
    if (!principal || !verifiedTasks) {
      setErrorMsg("Sign in to manage tasks.");
      return;
    }
    const actionPrincipal = principal;
    try {
      const { apiClient } = await import('@/lib/api');
      if (principalRef.current !== actionPrincipal) return;
      await apiClient.post(`/api/tasks/${taskId}/execute`, {});
      if (principalRef.current !== actionPrincipal) return;
      void fetchLiveData();
    } catch (err: unknown) {
      if (principalRef.current !== actionPrincipal) return;
      alert("Failed to execute task: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleShowToolReceipts = async (task: Task) => {
    if (!principal || !verifiedTasks) return;
    const actionPrincipal = principal;
    const reqId = ++toolReceiptRequestId.current;
    if (openToolReceiptsTask === task.id) {
      setOpenToolReceiptsTask(null);
      return;
    }
    if (!task.executionId) {
      setToolReceiptError("No completed execution was recorded for this task.");
      return;
    }
    setOpenToolReceiptsTask(task.id);
    setToolReceipts([]);
    setToolReceiptError("");
    setToolReceiptsLoading(true);
    try {
      const { apiClient } = await import("@/lib/api");
      if (principalRef.current !== actionPrincipal) return;
      const rows = await apiClient.get<GovernedToolReceipt[]>(
        `/api/tasks/${encodeURIComponent(task.id)}/tool-receipts?execution_id=${encodeURIComponent(task.executionId)}&limit=50`,
      );
      if (principalRef.current === actionPrincipal && reqId === toolReceiptRequestId.current) setToolReceipts(rows);
    } catch (err: unknown) {
      if (reqId === toolReceiptRequestId.current) {
        setToolReceiptError(err instanceof Error ? err.message : "Governed tool receipts unavailable.");
      }
    } finally {
      if (reqId === toolReceiptRequestId.current) setToolReceiptsLoading(false);
    }
  };

  const handleShowHistory = async (taskId: string) => {
    if (!principal || !verifiedTasks) return;
    const actionPrincipal = principal;
    // Fence stale responses from another task or a completed refresh.
    const currentRequestId = ++historyRequestId.current;
    if (openHistoryTask === taskId) {
      setOpenHistoryTask(null);
      return;
    }
    setOpenHistoryTask(taskId);
    setReviewHistory([]);
    setHistoryError("");
    setHistoryLoading(true);
    try {
      const { apiClient } = await import("@/lib/api");
      if (principalRef.current !== actionPrincipal) return;
      const records = await apiClient.get<ReviewHistoryEntry[]>(
        `/api/tasks/${encodeURIComponent(taskId)}/reviews?limit=50`,
      );
      if (principalRef.current === actionPrincipal && currentRequestId === historyRequestId.current) {
        setReviewHistory(records);
      }
    } catch (err: unknown) {
      if (currentRequestId === historyRequestId.current) {
        setHistoryError(err instanceof Error ? err.message : "Task review history is unavailable.");
      }
    } finally {
      if (currentRequestId === historyRequestId.current) {
        setHistoryLoading(false);
      }
    }
  };

  const handleReviewTask = async (task: Task, decision: "approve" | "reject") => {
    if (!principal || !verifiedTasks || task.status !== "ReviewRequired" || !task.executionId) {
      setErrorMsg("This execution does not have a reviewable result.");
      return;
    }
    const receipt = task.resultReceipt;
    if (decision === "approve" && task.verificationContract?.version &&
        receipt?.machine_verification?.status !== "passed") {
      setErrorMsg("This output did not pass the declared schema. Reject it or rerun the task.");
      return;
    }
    if (
      decision === "approve" &&
      (
        !receipt?.answer_text ||
        receipt.answer_truncated ||
        receipt.source_refs_truncated ||
        (receipt.artifact_count ?? 0) > 0 ||
        (receipt.attachment_count ?? 0) > 0 ||
        (receipt.sources?.length ?? 0) !== (receipt.source_count ?? 0)
      )
    ) {
      setErrorMsg("This result lacks complete, reviewer-accessible evidence. Reject it and request a new output.");
      return;
    }
    const description = decision === "approve"
      ? "Confirm that you reviewed the actual result and accept this task as completed?"
      : "Reject this result as not meeting the task objective?";
    if (!window.confirm(description)) return;
    const actionPrincipal = principal;
    try {
      const { apiClient } = await import("@/lib/api");
      if (principalRef.current !== actionPrincipal) return;
      await apiClient.post(`/api/tasks/${encodeURIComponent(task.id)}/review`, {
        execution_id: task.executionId,
        decision,
        note: "",
      });
      if (principalRef.current !== actionPrincipal) return;
      await fetchLiveData();
    } catch (err: unknown) {
      if (principalRef.current !== actionPrincipal) return;
      setErrorMsg(err instanceof Error ? err.message : "Unable to review task.");
    }
  };

  const handleCreateTask = async () => {
    if (!principal || !verifiedAgents || formOwner !== principal) {
      setErrorMsg("Sign in to manage tasks.");
      return;
    }
    if (!taskName.trim()) {
      alert("Please enter a task name.");
      return;
    }
    if (!taskDescription.trim()) {
      alert("Please enter a task description.");
      return;
    }
    if (!newPrimaryAgent) {
      alert("Please select a primary agent first.");
      return;
    }
    const actionPrincipal = principal;
    try {
      let verificationContract: Record<string, unknown> = {};
      if (verificationSchemaJson.trim()) {
        const schema: unknown = JSON.parse(verificationSchemaJson);
        if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
          throw new Error("Verification schema must be a JSON object.");
        }
        verificationContract = {
          version: "structured-output.v1",
          schema: schema as Record<string, unknown>,
        };
      }
      const { apiClient } = await import('@/lib/api');
      if (principalRef.current !== actionPrincipal) return;
      await apiClient.post('/api/tasks/', {
        name: taskName.trim(),
        description: taskDescription.trim(),
        acceptanceCriteria: acceptanceCriteria.trim(),
        verificationContract,
        primaryAgent: newPrimaryAgent,
        primaryAgentInstructions: newPrimaryAgentInstructions,
        taskType: taskName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""),
        subAgents: visibleSubAgents
      });
      if (principalRef.current !== actionPrincipal) return;
      setTaskName("");
      setTaskDescription("");
      setAcceptanceCriteria("");
      setVerificationSchemaJson("");
      setNewPrimaryAgent("");
      setNewPrimaryAgentInstructions("");
      setNewSubAgents([]);
      fetchLiveData();
    } catch (err: unknown) {
      if (principalRef.current !== actionPrincipal) return;
      alert("Failed to create task: " + (err instanceof Error ? err.message : String(err)));
    }
  };


  return (
    <TooltipProvider>
    <div className="karen-automation karen-automation-workflow space-y-6">
      <AutomationWorkflowHeader
          icon={ScrollText}
          section="TASK DEFINITIONS"
          title="Task Management"
          description="Define specific, single-objective tasks for your agents and monitor execution."
        />
      
      {errorMsg && (
        <Alert variant="destructive">
          <AlertTitle>Error Loading Tasks</AlertTitle>
          <AlertDescription>{errorMsg}</AlertDescription>
        </Alert>
      )}

        <Alert>
            <Users className="h-4 w-4" />
            <AlertTitle>Primary and Sub-Agent Model</AlertTitle>
            <AlertDescription>
            Each Task is assigned a <strong>Primary Agent</strong> that is responsible for the final outcome. You can provide it with specific instructions. You can also assign <strong>Sub-Agents</strong>, which the primary agent can delegate specific parts of the task to, each with their own instructions. For orchestrating multiple independent tasks, use a <strong>Sequence</strong>.
            </AlertDescription>
        </Alert>

      <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Task List */}
        <div className="min-w-0 space-y-4 xl:col-span-2">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Defined Tasks</h3>
            <Button variant="outline" size="sm" onClick={fetchLiveData} disabled={isAuthLoading || !isAuthenticated}>Refresh</Button>
          </div>
          
          {isAuthLoading ? (
            <AutomationListNotice kind="loading" message="Restoring your session..." />
          ) : !isAuthenticated ? (
            <AutomationListNotice kind="authentication" message="Sign in to view task definitions." />
          ) : isLoading || !verifiedTasks ? (
            <AutomationListNotice kind="loading" message="Loading tasks from backend..." />
          ) : tasksFetchError ? (
            <AutomationListNotice kind="unavailable" message="Task definitions could not be verified with the backend." />
          ) : tasks.length === 0 ? (
            <AutomationListNotice kind="empty" message="No live task definitions yet." />
          ) : verifiedTasks && tasks.map((task: Task, index: number) => (
            <Card className="karen-automation-card" key={task.id || index}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <CardTitle className="text-base">{task.name}</CardTitle>
                        <CardDescription className="text-xs">{task.description}</CardDescription>
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                        <Button variant="ghost" size="icon" onClick={() => handleExecuteTask(task.id)}>
                            <Play className="h-4 w-4 text-muted-foreground hover:text-green-500" />
                        </Button>
                        <Button variant="ghost" size="icon"
                          aria-label={`Show review history for ${task.name}`}
                          title="Review history" onClick={() => handleShowHistory(task.id)}>
                          <History className="h-4 w-4 text-muted-foreground" />
                        </Button>
                        <Button variant="ghost" size="icon"
                          aria-label={`Show governed tool receipts for ${task.name}`}
                          title="Governed tool receipts" disabled={!task.executionId}
                          onClick={() => handleShowToolReceipts(task)}>
                          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDeleteTask(task.id)}>
                            <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                        </Button>
                    </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3 text-xs text-muted-foreground">
                <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
                    <div className="flex items-center gap-2">
                        <Bot className="h-4 w-4" />
                        <span>Primary: <strong className="font-semibold text-foreground">{getAgentLabel(task.primaryAgent)}</strong></span>
                        {task.primaryAgentInstructions && (
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <FileCog className="h-3.5 w-3.5 cursor-help" />
                                </TooltipTrigger>
                                <TooltipContent side="top" className="max-w-xs">
                                    <p className="text-xs font-semibold">Primary Agent Instructions:</p>
                                    <p className="text-xs font-mono bg-muted p-1.5 rounded-md mt-1">{task.primaryAgentInstructions}</p>
                                </TooltipContent>
                            </Tooltip>
                        )}
                    </div>
                    {task.subAgents && task.subAgents.length > 0 && (
                        <div className="flex items-center gap-2">
                            <Users className="h-4 w-4" />
                            <span>Sub-Agents: <strong className="font-semibold text-foreground">{task.subAgents.map((sa: SubAgent) => sa.name).join(', ')}</strong></span>
                        </div>
                    )}
                </div>
                <div className="flex items-center justify-between pt-1">
                    <span>Last Run: {task.lastRun || "Never"}</span>
                    <Badge variant={task.status === "Success" ? "default" : (task.status === "Pending" || task.status === "ReviewRequired" || task.status === "LegacyUnverified" ? "secondary" : (task.status === "Running" ? "outline" : "destructive"))}>
                      {task.status === "ReviewRequired" ? "Awaiting verification" : task.status === "LegacyUnverified" ? "Historical, unverified" : task.status === "Success" ? "Human-verified" : task.status}
                    </Badge>
                </div>
                {task.acceptanceCriteria && (
                  <p className="whitespace-pre-wrap break-words">
                    Acceptance criteria: {task.acceptanceCriteria}
                  </p>
                )}
                {task.verificationContract?.version && (
                  <p>Machine output check: {task.resultReceipt?.machine_verification?.status ?? "not run"}.
                    A passing check verifies structure, not real-world completion.
                  </p>
                )}
                {task.status === "ReviewRequired" && task.executionId && (
                  <div className="rounded-lg border p-3 space-y-2">
                    <p className="font-semibold text-foreground">Result awaiting your review</p>
                    <p className="whitespace-pre-wrap break-words text-foreground">
                      {task.resultReceipt?.answer_text || "No answer text was recorded."}
                    </p>
                    {task.resultReceipt?.answer_truncated && (
                      <p>The captured text is truncated. Completion cannot be approved from incomplete evidence.</p>
                    )}
                    <p>
                      Execution: {task.executionId} · Sources: {task.resultReceipt?.source_count ?? 0} ·
                      Artifacts: {task.resultReceipt?.artifact_count ?? 0} ·
                      Attachments: {task.resultReceipt?.attachment_count ?? 0}
                    </p>
                    {(task.resultReceipt?.sources ?? []).length > 0 && (
                      <div className="space-y-1">
                        <p className="font-semibold">Reported sources (not independently verified)</p>
                        {(task.resultReceipt?.sources ?? []).map((source, index) => (
                          <p key={`${source.url ?? source.title ?? "source"}-${index}`} className="break-all">
                            {source.url ? (
                              <a className="underline" href={source.url} target="_blank" rel="noopener noreferrer">
                                {source.title || source.url}
                              </a>
                            ) : (source.title || "Unresolved source")}
                          </p>
                        ))}
                      </div>
                    )}
                    {((task.resultReceipt?.artifact_count ?? 0) > 0 ||
                      (task.resultReceipt?.attachment_count ?? 0) > 0 ||
                      task.resultReceipt?.source_refs_truncated) && (
                      <p className="text-destructive">
                        This task includes inaccessible work products or incomplete sources. Approval is blocked.
                        You may reject the result and request a reviewer-accessible output.
                      </p>
                    )}
                    {task.resultReceipt?.machine_verification?.status === "failed" && (
                      <p className="text-destructive">
                        Structured output check failed: {task.resultReceipt.machine_verification.reason || "Unknown cause"}.
                        Approval is blocked until a new attempt passes.
                      </p>
                    )}
                    {task.resultReceipt?.degraded_mode && (
                      <p className="text-destructive">The runtime reported degraded execution.</p>
                    )}
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => handleReviewTask(task, "approve")}
                        disabled={
                          (Boolean(task.verificationContract?.version) &&
                            task.resultReceipt?.machine_verification?.status !== "passed") ||
                          !task.resultReceipt?.answer_text ||
                          !!task.resultReceipt?.answer_truncated ||
                          !!task.resultReceipt?.source_refs_truncated ||
                          (task.resultReceipt?.artifact_count ?? 0) > 0 ||
                          (task.resultReceipt?.attachment_count ?? 0) > 0 ||
                          (task.resultReceipt?.sources?.length ?? 0) !== (task.resultReceipt?.source_count ?? 0)
                        }>
                        Verify completion
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => handleReviewTask(task, "reject")}>
                        Reject result
                      </Button>
                    </div>
                  </div>
                )}
                {openHistoryTask === task.id && (
                  <div className="rounded-lg border p-3 space-y-2">
                    <p className="font-semibold text-foreground">Previous human reviews</p>
                    {historyLoading ? <p>Loading review history...</p>
                      : historyError ? <p className="text-destructive">{historyError}</p>
                      : reviewHistory.length === 0 ? <p>No review events recorded.</p>
                      : reviewHistory.map((review) => (
                        <div key={review.outcome_id} className="border-t pt-2 space-y-1">
                          <p className="font-semibold text-foreground">
                            {review.decision === "approve" ? "Accepted by task creator" : "Rejected by task creator"}
                          </p>
                          <p>{new Date(review.reviewed_at).toLocaleString()}</p>
                          {review.acceptance_criteria && (
                            <p className="whitespace-pre-wrap">Criteria: {review.acceptance_criteria}</p>
                          )}
                          {review.review_note && (
                            <p className="whitespace-pre-wrap">Review note: {review.review_note}</p>
                          )}
                          <p className="break-all">Execution: {review.execution_id}</p>
                          <details className="rounded border p-2">
                            <summary className="cursor-pointer font-semibold text-foreground">
                              View captured runtime output
                            </summary>
                            <p className="mt-2 whitespace-pre-wrap break-words text-foreground">
                              {review.result_receipt?.answer_text || "No retained output"}
                            </p>
                            {review.result_receipt?.answer_truncated && (
                              <p>Original runtime response was truncated.</p>
                            )}
                          </details>
                          <p>
                            Sources: {review.result_receipt?.source_count ?? 0} ·
                            Artifacts: {review.result_receipt?.artifact_count ?? 0} ·
                            Attachments: {review.result_receipt?.attachment_count ?? 0}
                          </p>
                          <p className="break-all">Receipt SHA-256: {review.receipt_sha256}</p>
                          <p>Human attestation, not independently verified.</p>
                        </div>
                      ))}
                  </div>
                )}
                {openToolReceiptsTask === task.id && (
                  <div className="rounded-lg border p-3 space-y-2">
                    <p className="font-semibold text-foreground">Governed tool execution receipts</p>
                    <p>These are authenticated tool-runtime acknowledgments, not independently confirmed external outcomes.</p>
                    {toolReceiptsLoading ? <p>Loading backend receipts...</p>
                      : toolReceiptError ? <p className="text-destructive">{toolReceiptError}</p>
                      : toolReceipts.length === 0 ? <p>No governed Medusa tool receipts are recorded for this attempt.</p>
                      : <GovernedToolReceiptList receipts={toolReceipts} />}
                  </div>
                )}
                {task.lastError && (
                  <div className="text-[11px] text-destructive">
                    Last error: {task.lastError}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Create New Task Form */}
        <div className="min-w-0 xl:col-span-1">
          <Card className="karen-automation-card xl:sticky xl:top-20">
            <CardHeader>
            <CardTitle>Create New Task</CardTitle>
              <CardDescription>Configure an agent to perform a live task.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
               <div className="space-y-1.5">
                  <Label htmlFor="task-name">Task Name</Label>
                  <Input id="task-name" placeholder="e.g., Summarize Morning News" value={formOwner === principal ? taskName : ""} onChange={(e) => setTaskName(e.target.value)} />
               </div>
               <div className="space-y-1.5">
                  <Label htmlFor="task-description">Task Description</Label>
                  <Textarea
                    id="task-description"
                    placeholder="Describe what this task should do."
                    value={formOwner === principal ? taskDescription : ""}
                    onChange={(e) => setTaskDescription(e.target.value)}
                    rows={4}
                  />
               </div>
               <div className="space-y-1.5">
                 <Label htmlFor="task-acceptance-criteria">Acceptance criteria (for human verification)</Label>
                 <Textarea id="task-acceptance-criteria" maxLength={4000}
                   placeholder="What must be true before you consider this task completed?"
                   value={formOwner === principal ? acceptanceCriteria : ""}
                   onChange={(e) => setAcceptanceCriteria(e.target.value)}
                   rows={3}
                 />
               </div>
               <div className="space-y-1.5">
                 <Label htmlFor="task-machine-schema">Optional machine-checkable JSON output schema</Label>
                 <Textarea id="task-machine-schema" maxLength={8192}
                   placeholder='{"type":"object","required":["summary"],"properties":{"summary":{"type":"string"}}}'
                   value={formOwner === principal ? verificationSchemaJson : ""}
                   onChange={(e) => setVerificationSchemaJson(e.target.value)}
                   rows={4}
                 />
                 <p className="text-xs text-muted-foreground">
                   Checks ChatRuntime structured output only. This does not verify real-world completion. Human approval remains required.
                 </p>
               </div>
               <div className="space-y-1.5">
                   <Label htmlFor="task-primary-agent">Assign Primary Agent</Label>
                   <div className="flex items-center space-x-2">
                      <Select value={formOwner === principal ? newPrimaryAgent : ""} onValueChange={setNewPrimaryAgent}>
                        <SelectTrigger id="task-primary-agent">
                          <SelectValue placeholder={isAgentsLoading ? "Loading live agents..." : "Select a primary agent"} />
                        </SelectTrigger>
                        <SelectContent>
                          {liveAgents.map(agent => (
                            <SelectItem key={agent.agent_id} value={agent.agent_id}>
                              {agent.name || agent.agent_id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button 
                        variant="outline" 
                        size="icon" 
                        disabled={formOwner !== principal || !verifiedAgents || !newPrimaryAgent}
                        onClick={() => openInstructionEditor(newPrimaryAgent!, newPrimaryAgentInstructions, setNewPrimaryAgentInstructions)}
                       >
                         <Settings className="h-4 w-4" />
                      </Button>
                   </div>
               </div>
                <div className="space-y-1.5">
                    <Label>Assign Sub-Agents (Optional)</Label>
                    <div className="p-3 border rounded-md h-40 overflow-y-auto space-y-2 bg-muted/30">
                      {visibleSubAgents.length === 0 ? (
                            <p className="text-xs text-center text-muted-foreground py-1">No sub-agents assigned.</p>
                       ) : visibleSubAgents.map((agent, index) => (
                         <div key={agent.agentId || agent.name} className="flex items-center space-x-2 p-2 rounded-md bg-background border">
                             <Bot className="h-4 w-4 text-muted-foreground" />
                             <span className="text-sm flex-1">{agent.name}</span>
                              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openInstructionEditor(agent.name, agent.instructions, (newInstructions) => {
                                 const updatedAgents = [...newSubAgents];
                                 updatedAgents[index].instructions = newInstructions;
                                 setNewSubAgents(updatedAgents);
                              })}>
                                <Settings className="h-4 w-4 text-muted-foreground hover:text-primary"/>
                             </Button>
                             <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => handleRemoveSubAgent(agent.agentId || agent.name)}>
                                <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive"/>
                             </Button>
                         </div>
                       ))}
                    </div>
                    <Dialog>
                        <DialogTrigger asChild>
                            <Button variant="outline" className="w-full mt-2">
                                <PlusCircle className="mr-2 h-4 w-4" />
                                Add Sub-Agent
                            </Button>
                        </DialogTrigger>
                        <DialogContent>
                            <DialogHeader>
                                <DialogTitle>Add Sub-Agent</DialogTitle>
                                <DialogDescription>
                                    Select from available agents to assign as sub-agents for this task.
                                </DialogDescription>
                            </DialogHeader>
                            <div className="py-2 max-h-[50vh] overflow-y-auto">
                                <div className="flex flex-col space-y-2">
                                    {liveAgents.map(agent => (
                                      <div key={agent.agent_id} className="flex items-center justify-between p-2 rounded-md border bg-muted/40">
                                        <div className="flex items-center space-x-3">
                                          <Bot className="h-4 w-4 text-muted-foreground" />
                                          <div className="flex flex-col">
                                            <span className="text-sm">{agent.name || agent.agent_id}</span>
                                            <span className="text-[11px] text-muted-foreground">{agent.agent_id}</span>
                                          </div>
                                        </div>
                                        <Button 
                                          size="sm"
                                          onClick={() => handleAddSubAgent(agent)}
                                          disabled={!verifiedAgents || formOwner !== principal || visibleSubAgents.some(sa => sa.agentId === agent.agent_id) || newPrimaryAgent === agent.agent_id}
                                          variant="secondary"
                                        >
                                          <PlusCircle className="mr-2 h-4 w-4" />
                                          Add
                                        </Button>
                                      </div>
                                    ))}
                                </div>
                            </div>
                            <DialogFooter>
                                <DialogClose asChild>
                                    <Button type="button">Done</Button>
                                </DialogClose>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                    <p className="text-xs text-muted-foreground">
                        Agents that the primary agent can delegate to, loaded from the live agent registry.
                    </p>
                </div>
            </CardContent>
            <CardFooter>
              <Button className="w-full" onClick={handleCreateTask} disabled={!principal || !verifiedAgents || formOwner !== principal || isAgentsLoading || liveAgents.length === 0}>
                <PlusCircle className="mr-2 h-4 w-4" />
                Create Task
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>
       <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>Developer Insight: Live Wiring</AlertTitle>
        <AlertDescription>
          This dashboard is wired to the live `/api/tasks` endpoint and the live `/api/agents` registry. Tasks are created from real inputs and executed through the backend runtime.
        </AlertDescription>
      </Alert>

       {/* Instruction Editor Dialog */}
      <Dialog open={formOwner === principal && !!editingConfig} onOpenChange={(isOpen) => !isOpen && setEditingConfig(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Configure Instructions for <span className="text-primary">{editingConfig?.agentName}</span></DialogTitle>
            <DialogDescription>
              Provide specific instructions, parameters, or JSON configuration for this agent.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Textarea
              value={tempInstructions}
              onChange={(e) => setTempInstructions(e.target.value)}
              placeholder="e.g., {'topic': 'AI in 2024', 'tone': 'formal'} or 'Summarize the attached document.'"
              rows={10}
              className="font-mono text-xs"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingConfig(null)}>Cancel</Button>
            <Button onClick={handleSaveInstructions}>Save Instructions</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
    </TooltipProvider>
  );
}
