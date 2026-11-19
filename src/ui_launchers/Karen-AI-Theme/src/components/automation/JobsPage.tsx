
"use client";

import React, { useCallback } from "react";
import useAuth from "@/lib/useAuth";
import { AutomationListNotice } from "@/components/automation/AutomationListNotice";
import { AutomationWorkflowHeader } from "@/components/automation/AutomationWorkflowHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Workflow, PlusCircle, Trash2, Info, Play, GripVertical, FilePlus2, Bot, Settings, ScrollText } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";

interface Job {
  id: string;
  name: string;
  description: string;
  tasks?: Task[];
  trigger?: string;
  status?: string;
  created_at?: string;
}

interface Task {
  id: string;
  name: string;
  description?: string;
  instructions?: string;
  agent?: string;
}
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

type SequenceTask = {
  name: string;
  instructions?: string;
  id?: string;
};

/**
 * @file SequencesPage.tsx
 * @description Page for creating and managing multi-step Jobs (formerly Sequences) via /api/automation/jobs.
 */
export default function SequencesPage() {
  const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();
  const principal = isAuthenticated && user?.tenant_id && user.user_id
    ? JSON.stringify([user.tenant_id, user.user_id]) : "";
  const principalRef = React.useRef(principal);
  principalRef.current = principal;
  const jobsRevision = React.useRef(0);
  const tasksRevision = React.useRef(0);
  const [jobsOwner, setJobsOwner] = React.useState<string | null>(null);
  const [formOwner, setFormOwner] = React.useState(principal);
  const [tasksOwner, setTasksOwner] = React.useState<string | null>(null);
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [availableTasks, setAvailableTasks] = React.useState<Task[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [jobsFetchError, setJobsFetchError] = React.useState(false);
  const [isTasksLoading, setIsTasksLoading] = React.useState(true);
  const [errorMsg, setErrorMsg] = React.useState("");

  // State for the creation form
  const [jobName, setJobName] = React.useState("");
  const [jobDescription, setJobDescription] = React.useState("");
  const [jobTrigger, setJobTrigger] = React.useState("Manual Run");

  const fetchJobs = useCallback(async () => {
    const owner = principal;
    if (principalRef.current !== owner) return;
    const revision = ++jobsRevision.current;
    if (!owner) {
      setJobs([]); setJobsOwner(null); setJobsFetchError(false);
      setErrorMsg("Sign in to manage jobs."); setIsLoading(false);
      return;
    }
    setIsLoading(true); setJobsOwner(null); setJobsFetchError(false); setErrorMsg("");
    try {
      const { apiClient } = await import("@/lib/api");
      if (principalRef.current !== owner || jobsRevision.current !== revision) return;
      const data = await apiClient.get<Job[]>("/api/automation/jobs/");
      if (principalRef.current !== owner || jobsRevision.current !== revision) return;
      if (!Array.isArray(data)) throw new Error("Invalid job list from backend.");
      setJobs(data); setJobsOwner(owner);
    } catch (error) {
      if (principalRef.current !== owner || jobsRevision.current !== revision) return;
      setJobs([]); setJobsOwner(owner); setJobsFetchError(true);
      setErrorMsg(error instanceof Error ? error.message : "Failed to fetch jobs.");
    } finally {
      if (principalRef.current === owner && jobsRevision.current === revision) setIsLoading(false);
    }
  }, [principal]);

  const fetchTasks = useCallback(async () => {
    const owner = principal;
    if (principalRef.current !== owner) return;
    const revision = ++tasksRevision.current;
    if (!owner) {
      setAvailableTasks([]); setTasksOwner(null); setIsTasksLoading(false);
      return;
    }
    setIsTasksLoading(true); setTasksOwner(null);
    try {
      const { apiClient } = await import("@/lib/api");
      if (principalRef.current !== owner || tasksRevision.current !== revision) return;
      const data = await apiClient.get<Task[]>("/api/tasks/");
      if (principalRef.current !== owner || tasksRevision.current !== revision) return;
      if (!Array.isArray(data)) throw new Error("Invalid task list from backend.");
      setAvailableTasks(data); setTasksOwner(owner);
    } catch (error) {
      if (principalRef.current !== owner || tasksRevision.current !== revision) return;
      setAvailableTasks([]); setTasksOwner(null);
      console.error("Failed to fetch tasks for sequences", error);
    } finally {
      if (principalRef.current === owner && tasksRevision.current === revision) setIsTasksLoading(false);
    }
  }, [principal]);

  React.useEffect(() => {
    if (isAuthLoading) return;
    void fetchJobs(); void fetchTasks();
    return () => { jobsRevision.current += 1; tasksRevision.current += 1; };
  }, [isAuthLoading, fetchJobs, fetchTasks]);

  React.useEffect(() => {
    setFormOwner(principal);
    setNewJobTasks([]); setJobName(""); setJobDescription(""); setJobTrigger("Manual Run");
    setEditingConfig(null); setTempInstructions("");
  }, [principal]);

  const verifiedJobs = !!principal && jobsOwner === principal;
  const verifiedTasks = !!principal && tasksOwner === principal;
  const visibleTasks = verifiedTasks ? availableTasks : [];

  // State for the task list
  const [newJobTasks, setNewJobTasks] = React.useState<SequenceTask[]>([]);
  const visibleJobTasks = formOwner === principal ? newJobTasks : [];

  // State for the instruction editing dialog
  const [editingConfig, setEditingConfig] = React.useState<{ taskName: string; instructions: string; onSave: (newInstructions: string) => void; } | null>(null);
  const [tempInstructions, setTempInstructions] = React.useState("");

  const handleAddTaskToJob = (task: Task) => {
    if (!verifiedTasks || formOwner !== principal) return;
    setNewJobTasks([...newJobTasks, { name: task.name, instructions: task.instructions || '', id: task.id }]);
  };

  const handleRemoveTaskFromJob = (index: number) => {
    const updated = [...newJobTasks];
    updated.splice(index, 1);
    setNewJobTasks(updated);
  };
  
  const openInstructionEditor = (taskName: string, instructions: string, onSave: (newInstructions: string) => void) => {
    setTempInstructions(instructions);
    setEditingConfig({ taskName, instructions, onSave });
  };
  
  const handleSaveInstructions = () => {
    if (editingConfig) {
      editingConfig.onSave(tempInstructions);
      setEditingConfig(null);
    }
  };

  const handleDeleteJob = async (id: string) => {
    if (!principal || !verifiedJobs) {
      setErrorMsg("Sign in to manage jobs.");
      return;
    }
    if (!confirm("Are you sure you want to delete this job?")) return;
    const actionPrincipal = principal;
    try {
      const { apiClient } = await import('@/lib/api');
      if (principalRef.current !== actionPrincipal) return;
      await apiClient.delete(`/api/automation/jobs/${id}`);
      if (principalRef.current !== actionPrincipal) return;
      void fetchJobs();
    } catch (err: unknown) {
      if (principalRef.current !== actionPrincipal) return;
      alert("Failed to delete job: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleExecuteJob = async (id: string) => {
    if (!principal || !verifiedJobs) {
      setErrorMsg("Sign in to manage jobs.");
      return;
    }
    const actionPrincipal = principal;
    try {
      const { apiClient } = await import('@/lib/api');
      if (principalRef.current !== actionPrincipal) return;
      await apiClient.post(`/api/automation/jobs/${id}/execute`, {});
      if (principalRef.current !== actionPrincipal) return;
      alert("Job execution started.");
      fetchJobs();
    } catch (err: unknown) {
      if (principalRef.current !== actionPrincipal) return;
      alert("Failed to execute job: " + (err as Error).message);
    }
  };

  const handleCreateJob = async () => {
    if (!principal || !verifiedTasks || formOwner !== principal) {
      setErrorMsg("Sign in to manage jobs.");
      return;
    }
    if (!jobName.trim()) {
      alert("Please provide a name for the job.");
      return;
    }
    if (visibleJobTasks.length === 0) {
      alert("Please add at least one task to the job.");
      return;
    }

    const actionPrincipal = principal;
    try {
      const { apiClient } = await import('@/lib/api');
      if (principalRef.current !== actionPrincipal) return;
      await apiClient.post('/api/automation/jobs/', {
        name: jobName,
        description: jobDescription,
        tasks: visibleJobTasks.map(t => ({ name: t.name, agent: "Configured Agent", instructions: t.instructions })),
        trigger: jobTrigger
      });
      if (principalRef.current !== actionPrincipal) return;
      
      // Reset form
      setJobName("");
      setJobDescription("");
      setNewJobTasks([]);
      
      fetchJobs();
    } catch (err: unknown) {
      if (principalRef.current !== actionPrincipal) return;
      alert("Failed to create job: " + (err instanceof Error ? err.message : String(err)));
    }
  };


  return (
    <>
      <div className="karen-automation karen-automation-workflow space-y-6">
        <AutomationWorkflowHeader
          icon={Workflow}
          section="SEQUENCE WORKFLOWS"
          title="Jobs"
          description="Orchestrate multiple tasks into a single persistent workflow."
        />
        
        {errorMsg && (
          <Alert variant="destructive">
            <AlertTitle>Error Loading Jobs</AlertTitle>
            <AlertDescription>{errorMsg}</AlertDescription>
          </Alert>
        )}

        <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-3">
          {/* Job List */}
          <div className="min-w-0 space-y-4 xl:col-span-2">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">Active Job Definitions</h3>
              <Button variant="outline" size="sm" onClick={fetchJobs} disabled={isAuthLoading || !isAuthenticated}>Refresh</Button>
            </div>
            
            {isAuthLoading ? (
              <AutomationListNotice kind="loading" message="Restoring your session..." />
            ) : !isAuthenticated ? (
              <AutomationListNotice kind="authentication" message="Sign in to view job definitions." />
            ) : isLoading || !verifiedJobs ? (
              <AutomationListNotice kind="loading" message="Loading jobs from backend..." />
            ) : jobsFetchError ? (
              <AutomationListNotice kind="unavailable" message="Job definitions could not be verified with the backend." />
            ) : jobs.length === 0 ? (
              <AutomationListNotice kind="empty" message="No jobs defined yet." />
            ) : verifiedJobs && jobs.map((job: Job, index: number) => (
              <Card className="karen-automation-card" key={job.id || index}>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <CardTitle className="text-base">{job.name}</CardTitle>
                        <Badge variant="outline" className="text-[10px]">{job.id}</Badge>
                      </div>
                      <CardDescription className="text-xs">{job.description}</CardDescription>
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                        <Button variant="ghost" size="icon" onClick={() => handleExecuteJob(job.id)}>
                          <Play className="h-4 w-4 text-muted-foreground hover:text-green-500" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDeleteJob(job.id)}>
                          <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                        </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <Label className="text-xs font-semibold">Task & Agent Chain</Label>
                  <div className="relative flex flex-wrap items-start gap-x-2 gap-y-4 mt-3 text-sm">
                    {job.tasks && job.tasks.map((task: Task, i: number) => (
                      <React.Fragment key={i}>
                        <div className="flex flex-col items-center text-center gap-1.5">
                          <Badge variant="secondary" className="px-3 py-1 text-xs">{task.name}</Badge>
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                              <Bot className="h-3 w-3" />
                              <span>{task.agent || "Default Agent"}</span>
                          </div>
                        </div>
                        {job.tasks && i < job.tasks.length - 1 && (
                          <div className="mt-2.5 h-px w-6 bg-border -mx-1" />
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </CardContent>
                <CardFooter className="text-xs text-muted-foreground pt-4 border-t flex justify-between">
                  <span>Trigger: <strong className="text-foreground">{job.trigger}</strong></span>
                  {job.status && (
                    <Badge variant={job.status === 'Success' ? 'default' : job.status === 'Failed' ? 'destructive' : 'secondary'}>
                      {job.status}
                    </Badge>
                  )}
                </CardFooter>
              </Card>
            ))}
          </div>

          {/* Create New Job Form */}
          <div className="min-w-0 xl:col-span-1">
            <Card className="karen-automation-card xl:sticky xl:top-20">
              <CardHeader>
                <CardTitle className="flex items-center"><FilePlus2 className="mr-2 h-5 w-5"/>Define New Job</CardTitle>
                <CardDescription>Chain existing tasks into a sequence.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1.5">
                    <Label htmlFor="job-name">Job Name</Label>
                    <Input 
                      id="job-name" 
                      placeholder="e.g., Daily Content Pipeline" 
                      value={formOwner === principal ? jobName : ""}
                      onChange={(e) => setJobName(e.target.value)}
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="job-desc">Description</Label>
                    <Textarea 
                      id="job-desc" 
                      placeholder="Describe the goal of this job." 
                      rows={2} 
                      value={formOwner === principal ? jobDescription : ""}
                      onChange={(e) => setJobDescription(e.target.value)}
                    />
                </div>
                <div className="space-y-1.5">
                    <Label htmlFor="job-trigger">Trigger Type</Label>
                    <Input 
                      id="job-trigger" 
                      placeholder="Manual Run, Cron, Event..." 
                      value={formOwner === principal ? jobTrigger : "Manual Run"}
                      onChange={(e) => setJobTrigger(e.target.value)}
                    />
                </div>
                <div className="space-y-1.5">
                  <Label>Workflow Chain (Steps)</Label>
                  <div className="p-3 border rounded-md h-64 overflow-y-auto space-y-2 bg-muted/30">
                      {visibleJobTasks.length === 0 ? (
                          <p className="text-xs text-center text-muted-foreground py-2">No tasks in job. Click &quot;Add Task Step&quot; to begin.</p>
                      ) : (
                          visibleJobTasks.map((task, index) => (
                          <div key={`${task.name}-${index}`} className="flex items-center space-x-2 p-2 rounded-md bg-background border">
                              <GripVertical className="h-4 w-4 text-muted-foreground" />
                              <span className="text-sm flex-1 truncate">{task.name}</span>
                              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openInstructionEditor(task.name, task.instructions || '', (newInstructions) => {
                                const updatedTasks = [...newJobTasks];
                                updatedTasks[index].instructions = newInstructions;
                                setNewJobTasks(updatedTasks);
                              })}>
                                <Settings className="h-4 w-4 text-muted-foreground hover:text-primary"/>
                              </Button>
                              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => handleRemoveTaskFromJob(index)}>
                                <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive"/>
                              </Button>
                          </div>
                          ))
                      )}
                  </div>
                  <Dialog>
                    <DialogTrigger asChild>
                        <Button variant="outline" className="w-full mt-2" disabled={isTasksLoading || !verifiedTasks || visibleTasks.length === 0}>
                            <PlusCircle className="mr-2 h-4 w-4" />
                            {isTasksLoading ? "Loading Tasks..." : "Add Task Step"}
                        </Button>
                    </DialogTrigger>
                    <DialogContent>
                        <DialogHeader>
                            <DialogTitle>Add Step to Sequence</DialogTitle>
                            <DialogDescription>
                                Select a live task to add to the chain.
                            </DialogDescription>
                        </DialogHeader>
                        <div className="py-2 max-h-[50vh] overflow-y-auto">
                            <div className="flex flex-col space-y-2">
                                {visibleTasks.map(task => (
                                <div key={task.id} className="flex items-center justify-between p-3 rounded-md border bg-muted/40">
                                    <div className="flex-1 pr-4">
                                        <div className="flex items-center space-x-3">
                                            <ScrollText className="h-4 w-4 text-muted-foreground" />
                                            <p className="text-sm font-medium">{task.name}</p>
                                        </div>
                                        <p className="text-xs text-muted-foreground mt-1 pl-7 truncate">{task.description}</p>
                                    </div>
                                    <Button 
                                    size="sm"
                                    onClick={() => handleAddTaskToJob(task)}
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
                </div>
              </CardContent>
              <CardFooter>
                <Button className="w-full" onClick={handleCreateJob} disabled={!principal || !verifiedTasks || formOwner !== principal || visibleJobTasks.length === 0}>
                  <PlusCircle className="mr-2 h-4 w-4" />
                  Save Job Definition
                </Button>
              </CardFooter>
            </Card>
          </div>
        </div>

        <Alert>
          <Info className="h-4 w-4" />
          <AlertTitle>System Integrity</AlertTitle>
          <AlertDescription>
            This dashboard is synchronized with the AI Karen backend. Job sequences are executed through the live LangGraph runtime and persist across restarts.
          </AlertDescription>
        </Alert>
      </div>

      {/* Instruction Editor Dialog */}
      <Dialog open={formOwner === principal && !!editingConfig} onOpenChange={(isOpen) => !isOpen && setEditingConfig(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Configure Step: <span className="text-primary">{editingConfig?.taskName}</span></DialogTitle>
            <DialogDescription>
               Provide specific instructions or parameters for this task, just for this step in the job. This will override the task&apos;s default instructions.
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
            <Button onClick={handleSaveInstructions}>Save Step Instructions</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
