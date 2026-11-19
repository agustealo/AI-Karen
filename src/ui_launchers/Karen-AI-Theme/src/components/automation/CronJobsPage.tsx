
"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { Clock, PlusCircle, Trash2, AlertTriangle, Info } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, SelectGroup, SelectLabel, SelectSeparator } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { useState, useEffect, useCallback, useRef } from "react";
import useAuth from "@/lib/useAuth";
import { AutomationListNotice } from "@/components/automation/AutomationListNotice";
import { AutomationWorkflowHeader } from "@/components/automation/AutomationWorkflowHeader";
import { ApiError, apiClient } from "@/lib/api";

interface CronJob {
  id: string;
  name: string;
  schedule: string;
  target_id: string;
  type: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  taskName?: string;
  nextRun?: string;
}

interface Task {
  id: string;
  name: string;
  [key: string]: unknown;
}

interface Sequence {
  id: string;
  name: string;
  [key: string]: unknown;
}

/**
 * @file CronJobsPage.tsx
 * @description Preview page for scheduling Tasks using cron expressions.
 */
async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function loadCronJobsWithRetry(isCurrent: () => boolean): Promise<CronJob[]> {
  const retryDelaysMs = [250, 750];
  let lastError: unknown;

  for (let attempt = 0; attempt <= retryDelaysMs.length; attempt += 1) {
    if (!isCurrent()) throw new Error("Schedule request superseded by a new principal or revision");
    try {
      // Do not share an in-flight authenticated response across components,
      // principals, or sessions.
      return await apiClient.get<CronJob[]>("/api/automation/cron");
    } catch (error) {
      lastError = error;

      if (error instanceof ApiError && (error.status === 404 || error.status === 429) && attempt < retryDelaysMs.length) {
        await sleep(retryDelaysMs[attempt]);
        if (!isCurrent()) throw new Error("Schedule request superseded before retry");
        continue;
      }

      throw error;
    }
  }

  throw lastError instanceof Error ? lastError : new Error("Failed to load cron jobs");
}

export default function CronJobsPage() {

  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [sequences, setSequences] = useState<Sequence[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();
  const principal = isAuthenticated && user?.tenant_id && user.user_id
    ? JSON.stringify([user.tenant_id, user.user_id])
    : "";
  // Synchronous render-time principal check prevents an old account response
  // committing between identity change and the next effect cleanup.
  const currentPrincipal = useRef(principal);
  currentPrincipal.current = principal;
  const jobsRevision = useRef(0);
  const dependenciesRevision = useRef(0);
  const [jobsOwner, setJobsOwner] = useState<string | null>(null);
  const [dependenciesOwner, setDependenciesOwner] = useState<string | null>(null);
  
  // Form State
  const [taskName, setTaskName] = useState("");
  const [schedule, setSchedule] = useState("");
  const [targetId, setTargetId] = useState("");
  const [type, setType] = useState("Sequence"); // "Sequence" or "Task"
  const [enabled, setEnabled] = useState(true);

  const fetchDependencies = useCallback(async () => {
    const requestPrincipal = principal;
    const revision = ++dependenciesRevision.current;
    if (!requestPrincipal) {
      setTasks([]);
      setSequences([]);
      setDependenciesOwner(null);
      return;
    }

    setDependenciesOwner(null);
    try {
      const [tasksRes, seqsRes] = await Promise.all([
        apiClient.get<Task[]>("/api/tasks"),
        apiClient.get<Sequence[]>("/api/automation/jobs"),
      ]);
      if (currentPrincipal.current !== requestPrincipal ||
          dependenciesRevision.current !== revision) return;
      setTasks(tasksRes || []);
      setSequences(seqsRes || []);
      setDependenciesOwner(requestPrincipal);
    } catch (error) {
      if (currentPrincipal.current !== requestPrincipal ||
          dependenciesRevision.current !== revision) return;
      setTasks([]);
      setSequences([]);
      setDependenciesOwner(null);
      console.error("Failed to fetch schedule dependencies", error);
    }
  }, [principal]);

  const fetchJobs = useCallback(async () => {
    const requestPrincipal = principal;
    const revision = ++jobsRevision.current;
    if (!requestPrincipal) {
      setFetchError(false);
      setJobs([]);
      setJobsOwner(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setFetchError(false);
    setJobsOwner(null);
    try {
      const res = await loadCronJobsWithRetry(() =>
        currentPrincipal.current === requestPrincipal &&
        jobsRevision.current === revision,
      );
      if (currentPrincipal.current !== requestPrincipal ||
          jobsRevision.current !== revision) return;
      setJobs(res);
      setJobsOwner(requestPrincipal);
    } catch (error) {
      if (currentPrincipal.current !== requestPrincipal ||
          jobsRevision.current !== revision) return;
      setJobs([]);
      setFetchError(true);
      setJobsOwner(requestPrincipal);
      if (!(error instanceof ApiError &&
            (error.status === 401 || error.status === 404 || error.status === 429))) {
        console.error("Failed to fetch cron jobs", error);
      }
    } finally {
      if (currentPrincipal.current === requestPrincipal &&
          jobsRevision.current === revision) {
        setLoading(false);
      }
    }
  }, [principal]);

  useEffect(() => {
    if (isAuthLoading) return;

    void fetchJobs();
    void fetchDependencies();
    return () => {
      // Invalidate any requests still pending when the principal changes
      // or the workspace unmounts.
      jobsRevision.current += 1;
      dependenciesRevision.current += 1;
    };
  }, [fetchJobs, fetchDependencies, isAuthLoading]);

  useEffect(() => {
    // Form selections belong to the active principal and cannot be reused
    // after switching accounts or tenants.
    setTargetId("");
    setTaskName("");
    setSchedule("");
    setType("Sequence");
  }, [principal]);

  const verifiedJobs = jobsOwner === principal && !!principal;
  const verifiedDependencies = dependenciesOwner === principal && !!principal;
  const visibleTasks = verifiedDependencies ? tasks : [];
  const visibleSequences = verifiedDependencies ? sequences : [];

  const handleCreateJob = async () => {
    if (!principal || !verifiedDependencies) return;
    if (!taskName || !schedule || !targetId) return;

    try {
      await apiClient.post("/api/automation/cron", {
        taskName,
        schedule,
        type,
        targetId,
        enabled,
      });
      setTaskName("");
      setSchedule("");
      setTargetId("");
      fetchJobs();
    } catch (error) {
      console.error("Failed to create cron job", error);
      alert("Failed to create cron Job. Ensure schedule is valid.");
    }
  };

  const handleToggle = async (id: string, currentEnabled: boolean) => {
    if (!principal || !verifiedJobs) return;
    try {
      await apiClient.put(`/api/automation/cron/${id}/toggle`, { enabled: !currentEnabled });
      fetchJobs();
    } catch (error) {
      console.error("Failed to toggle cron job", error);
    }
  };

  const handleDelete = async (id: string) => {
    if (!principal || !verifiedJobs) return;
    try {
      await apiClient.delete(`/api/automation/cron/${id}`);
      fetchJobs();
    } catch (error) {
      console.error("Failed to delete cron job", error);
    }
  };

  return (
    <div className="karen-automation karen-automation-workflow space-y-6">
      <AutomationWorkflowHeader
          icon={Clock}
          section="SCHEDULE CONTROL"
          title="Cron Job Assignments"
          description="Manage live scheduled automations executing on the backend."
        />
      
      <Alert>
        <Clock className="h-4 w-4" />
        <AlertTitle>Scheduler Controls</AlertTitle>
        <AlertDescription>
          Manage saved schedules through the authenticated backend. A visible schedule does not independently verify scheduler health or execution.
        </AlertDescription>
      </Alert>

      {!isAuthLoading && !isAuthenticated && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Authentication Required</AlertTitle>
          <AlertDescription>
            Sign in to manage cron jobs. Your session must be active to sync with the backend scheduler.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Cron Job List */}
        <div className="min-w-0 space-y-4 xl:col-span-2">
          <h3 className="text-lg font-semibold">Scheduled Jobs {loading && <span className="text-sm font-normal text-muted-foreground ml-2">(Syncing...)</span>}</h3>
          {isAuthLoading ? (
            <AutomationListNotice kind="loading" message="Restoring your session..." />
          ) : !isAuthenticated ? (
            <AutomationListNotice kind="authentication" message="Sign in to view scheduled jobs." />
          ) : loading || !verifiedJobs ? (
            <AutomationListNotice kind="loading" message="Loading scheduled jobs from backend..." />
          ) : fetchError ? (
            <AutomationListNotice kind="unavailable" message="Schedules unavailable: the backend could not verify saved schedules." />
          ) : jobs.length === 0 ? (
            <AutomationListNotice kind="empty" message="No cron jobs configured yet." />
          ) : null}
          {!isAuthLoading && isAuthenticated && !loading && !fetchError && verifiedJobs && jobs.map((job, index) => (
            <Card className="karen-automation-card" key={job.id || index}>
              <CardHeader>
                 <div className="flex flex-wrap items-start justify-between gap-3">
                   <div>
                     <CardTitle className="text-base flex items-center">
                         <Badge variant="outline" className="mr-3 text-sm font-mono">{job.schedule}</Badge>
                         {job.taskName || 'Unnamed Task'}
                         <Badge variant={job.type === 'Sequence' ? "default" : "secondary"} className="ml-3 text-xs">{job.type}</Badge>
                     </CardTitle>
                     <CardDescription className="text-xs mt-1">
                         Next scheduled run: {job.nextRun || 'Not scheduled'}
                     </CardDescription>
                   </div>
                  <div className="flex flex-wrap items-center gap-1">
                      <Switch 
                        checked={job.enabled} 
                        onCheckedChange={() => handleToggle(job.id, job.enabled)}
                        aria-label={`Toggle ${job.taskName || job.name} schedule`}
                      />
                      <Button variant="ghost" size="icon" onClick={() => handleDelete(job.id)}>
                        <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                      </Button>
                  </div>
                </div>
              </CardHeader>
            </Card>
          ))}
        </div>

        {/* Create New Cron Job Form */}
        <div className="min-w-0 xl:col-span-1">
           <Card className="karen-automation-card xl:sticky xl:top-20">
            <CardHeader>
              <CardTitle>Schedule a New Job</CardTitle>
              <CardDescription>Assign a task or sequence to a schedule.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
               <div className="space-y-1.5">
                  <Label htmlFor="cron-task">Task or Sequence to Schedule</Label>
                   <Select value={targetId} onValueChange={(val) => {
                     const selectedSeq = visibleSequences.find(t => t.id === val);
                     const selectedTask = visibleTasks.find(t => t.id === val);
                     if (selectedSeq) {
                       setTargetId(val);
                       setTaskName(selectedSeq.name || selectedSeq.id);
                       setType("Sequence");
                     } else if (selectedTask) {
                       setTargetId(val);
                       setTaskName(selectedTask.name || selectedTask.id);
                       setType("Task");
                     }
                   }}>
                    <SelectTrigger id="cron-task">
                      <SelectValue placeholder="Select a task or sequence" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectLabel>Sequences</SelectLabel>
                        {visibleSequences.map(t => (
                           <SelectItem key={t.id} value={t.id}>{t.name || t.id}</SelectItem>
                        ))}
                      </SelectGroup>
                      <SelectSeparator />
                      <SelectGroup>
                        <SelectLabel>Tasks</SelectLabel>
                        {visibleTasks.map(t => (
                           <SelectItem key={t.id} value={t.id}>{t.name || t.id}</SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
               </div>
               <div className="space-y-1.5">
                  <Label htmlFor="cron-schedule">Cron Schedule</Label>
                  <Input 
                    id="cron-schedule" 
                    placeholder="e.g., 0 9 * * 1-5" 
                    value={schedule}
                    onChange={(e) => setSchedule(e.target.value)}
                  />
                   <p className="text-xs text-muted-foreground">
                     Standard cron syntax. E.g., &quot;*/5 * * * *&quot; for every 5 minutes.
                   </p>
               </div>
               <div className="flex items-center space-x-2 pt-2">
                  <Switch 
                    id="cron-enabled" 
                    checked={enabled}
                    onCheckedChange={(c) => setEnabled(c as boolean)}
                  />
                  <Label htmlFor="cron-enabled">Enable this job upon creation</Label>
               </div>
            </CardContent>
            <CardFooter>
              <Button onClick={handleCreateJob} className="w-full" disabled={!principal || !verifiedDependencies || !targetId || !schedule}>
                <PlusCircle className="mr-2 h-4 w-4" />
                Schedule Job
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>
      
      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>Developer Insight</AlertTitle>
        <AlertDescription>
         The backend scheduler evaluates due runs natively using `croniter`. Creating a job dynamically enqueues it to the live polling system without restarts. Execution and persistence guarantees must be verified through backend receipts.
        </AlertDescription>
      </Alert>
    </div>
  );
}
