
"use client";

import { useState, useEffect, useCallback } from "react";
import useAuth from "@/lib/useAuth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ScrollText, PlusCircle, Trash2, Play, Settings, Bot, Info, Users, FileCog } from "lucide-react";
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
};

/**
 * @file TasksPage.tsx
 * @description Page for defining and managing Tasks for AI agents via /api/tasks.
 */
export default function TasksPage() {
  const { isAuthenticated, isLoading: isAuthLoading } = useAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isAgentsLoading, setIsAgentsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState("");
  const [taskName, setTaskName] = useState("");
  const [taskDescription, setTaskDescription] = useState("");

  const fetchLiveData = useCallback(async () => {
    if (!isAuthenticated) {
      setTasks([]);
      setAgents([]);
      setErrorMsg("Sign in to manage tasks.");
      setIsLoading(false);
      setIsAgentsLoading(false);
      return;
    }

    setIsLoading(true);
    setIsAgentsLoading(true);
    setErrorMsg("");
    try {
      const { apiClient } = await import('@/lib/api');
      const [taskResult, agentResult] = await Promise.allSettled([
        apiClient.get<Task[]>('/api/tasks/'),
        apiClient.get<{ agents?: Array<Omit<AgentOption, 'capabilities'> & { capabilities?: string[] }> }>(
          '/api/agent-runtime/catalog',
        ),
      ]);

      if (taskResult.status === "fulfilled") {
        setTasks(taskResult.value || []);
      } else {
        console.error(taskResult.reason);
        setTasks([]);
        setErrorMsg(taskResult.reason instanceof Error ? taskResult.reason.message : 'Failed to fetch tasks.');
      }

      if (agentResult.status === "fulfilled") {
        const catalog = agentResult.value?.agents ?? [];
        setAgents(
          catalog.map((agent) => ({
            ...agent,
            capabilities: (agent.capabilities ?? []).map((name) => ({ name })),
          })),
        );
      } else {
        console.error(agentResult.reason);
        setAgents([]);
        setErrorMsg((current) => current || (agentResult.reason instanceof Error ? agentResult.reason.message : 'Failed to fetch live agents.'));
      }
    } catch (err: unknown) {
      console.error(err);
      setErrorMsg(err instanceof Error ? err.message : 'Failed to fetch tasks.');
    } finally {
      setIsLoading(false);
      setIsAgentsLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }
    fetchLiveData();
  }, [isAuthenticated, isAuthLoading, fetchLiveData]);

  
  const [newPrimaryAgent, setNewPrimaryAgent] = useState<string>("");
  const [newPrimaryAgentInstructions, setNewPrimaryAgentInstructions] = useState("");
  const [newSubAgents, setNewSubAgents] = useState<SubAgent[]>([]);
  
  // State for the instruction editing dialog
  const [editingConfig, setEditingConfig] = useState<{ agentName: string; instructions: string; onSave: (newInstructions: string) => void; } | null>(null);
  const [tempInstructions, setTempInstructions] = useState("");

  const liveAgents = agents || [];
  const getAgentLabel = (agentId?: string) => {
    if (!agentId) {
      return "Unknown";
    }
    return liveAgents.find((agent) => agent.agent_id === agentId)?.name || agentId;
  };

  const handleAddSubAgent = (agentToAdd: AgentOption) => {
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
    if (!isAuthenticated) {
      setErrorMsg("Sign in to manage tasks.");
      return;
    }
    if (!confirm("Are you sure you want to delete this task?")) return;
    try {
      const { apiClient } = await import('@/lib/api');
      await apiClient.delete(`/api/tasks/${taskId}`);
      fetchLiveData();
    } catch (err: unknown) {
      alert("Failed to delete task: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleExecuteTask = async (taskId: string) => {
    if (!isAuthenticated) {
      setErrorMsg("Sign in to manage tasks.");
      return;
    }
    try {
      const { apiClient } = await import('@/lib/api');
      await apiClient.post(`/api/tasks/${taskId}/execute`, {});
      fetchLiveData();
    } catch (err: unknown) {
      alert("Failed to execute task: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleCreateTask = async () => {
    if (!isAuthenticated) {
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
    try {
      const { apiClient } = await import('@/lib/api');
      await apiClient.post('/api/tasks/', {
        name: taskName.trim(),
        description: taskDescription.trim(),
        primaryAgent: newPrimaryAgent,
        primaryAgentInstructions: newPrimaryAgentInstructions,
        taskType: taskName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""),
        subAgents: newSubAgents
      });
      setTaskName("");
      setTaskDescription("");
      setNewPrimaryAgent("");
      setNewPrimaryAgentInstructions("");
      setNewSubAgents([]);
      fetchLiveData();
    } catch (err: unknown) {
      alert("Failed to create task: " + (err instanceof Error ? err.message : String(err)));
    }
  };


  return (
    <TooltipProvider>
    <div className="space-y-8">
      <div className="flex items-center space-x-3">
        <ScrollText className="h-8 w-8 text-primary" />
        <div>
          <h2 className="karen-page-title">Task Management</h2>
          <p className="text-sm text-muted-foreground">
            Define specific, single-objective tasks for your agents and monitor execution.
          </p>
        </div>
      </div>
      
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Task List */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Defined Tasks</h3>
            <Button variant="outline" size="sm" onClick={fetchLiveData} disabled={isAuthLoading || !isAuthenticated}>Refresh</Button>
          </div>
          
          {isAuthLoading ? (
            <div className="text-center p-8 text-muted-foreground animate-pulse">Restoring your session...</div>
          ) : isLoading ? (
            <div className="text-center p-8 text-muted-foreground animate-pulse">Loading tasks from backend...</div>
          ) : tasks.length === 0 ? (
            <div className="p-8 text-center border rounded-xl bg-muted/20 text-muted-foreground">No live task definitions yet.</div>
          ) : tasks.map((task: Task, index: number) => (
            <Card key={task.id || index}>
              <CardHeader>
                <div className="flex justify-between items-start">
                    <div>
                        <CardTitle className="text-base">{task.name}</CardTitle>
                        <CardDescription className="text-xs">{task.description}</CardDescription>
                    </div>
                    <div className="flex items-center space-x-1">
                        <Button variant="ghost" size="icon" onClick={() => handleExecuteTask(task.id)}>
                            <Play className="h-4 w-4 text-muted-foreground hover:text-green-500" />
                        </Button>
                        <Button variant="ghost" size="icon">
                            <Settings className="h-4 w-4 text-muted-foreground" />
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
                    <Badge variant={task.status === "Success" ? "default" : (task.status === "Pending" ? "secondary" : (task.status === "Running" ? "outline" : "destructive"))}>{task.status}</Badge>
                </div>
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
        <div className="lg:col-span-1">
          <Card className="sticky top-20">
            <CardHeader>
            <CardTitle>Create New Task</CardTitle>
              <CardDescription>Configure an agent to perform a live task.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
               <div className="space-y-1.5">
                  <Label htmlFor="task-name">Task Name</Label>
                  <Input id="task-name" placeholder="e.g., Summarize Morning News" value={taskName} onChange={(e) => setTaskName(e.target.value)} />
               </div>
               <div className="space-y-1.5">
                  <Label htmlFor="task-description">Task Description</Label>
                  <Textarea
                    id="task-description"
                    placeholder="Describe what this task should do."
                    value={taskDescription}
                    onChange={(e) => setTaskDescription(e.target.value)}
                    rows={4}
                  />
               </div>
               <div className="space-y-1.5">
                   <Label htmlFor="task-primary-agent">Assign Primary Agent</Label>
                   <div className="flex items-center space-x-2">
                      <Select value={newPrimaryAgent} onValueChange={setNewPrimaryAgent}>
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
                        disabled={!newPrimaryAgent}
                        onClick={() => openInstructionEditor(newPrimaryAgent!, newPrimaryAgentInstructions, setNewPrimaryAgentInstructions)}
                       >
                         <Settings className="h-4 w-4" />
                      </Button>
                   </div>
               </div>
                <div className="space-y-1.5">
                    <Label>Assign Sub-Agents (Optional)</Label>
                    <div className="p-3 border rounded-md h-40 overflow-y-auto space-y-2 bg-muted/30">
                      {newSubAgents.length === 0 ? (
                            <p className="text-xs text-center text-muted-foreground py-1">No sub-agents assigned.</p>
                       ) : newSubAgents.map((agent, index) => (
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
                                          disabled={newSubAgents.some(sa => sa.agentId === agent.agent_id) || newPrimaryAgent === agent.agent_id}
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
              <Button className="w-full" onClick={handleCreateTask} disabled={isAgentsLoading || liveAgents.length === 0}>
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
      <Dialog open={!!editingConfig} onOpenChange={(isOpen) => !isOpen && setEditingConfig(null)}>
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
