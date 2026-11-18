
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
import { useState, useEffect, useCallback } from "react";
import useAuth from "@/lib/useAuth";
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
let cronJobsFetchPromise: Promise<CronJob[]> | null = null;

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function loadCronJobsWithRetry(): Promise<CronJob[]> {
  const retryDelaysMs = [250, 750];
  let lastError: unknown;

  for (let attempt = 0; attempt <= retryDelaysMs.length; attempt += 1) {
    try {
      if (!cronJobsFetchPromise) {
        cronJobsFetchPromise = apiClient
          .get<CronJob[]>("/api/automation/cron")
          .finally(() => {
            cronJobsFetchPromise = null;
          });
      }

      return await cronJobsFetchPromise;
    } catch (error) {
      lastError = error;

      if (error instanceof ApiError && (error.status === 404 || error.status === 429) && attempt < retryDelaysMs.length) {
        await sleep(retryDelaysMs[attempt]);
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
  const { isAuthenticated, isLoading: isAuthLoading } = useAuth();
  
  // Form State
  const [taskName, setTaskName] = useState("");
  const [schedule, setSchedule] = useState("");
  const [targetId, setTargetId] = useState("");
  const [type, setType] = useState("Sequence"); // "Sequence" or "Task"
  const [enabled, setEnabled] = useState(true);

  const fetchDependencies = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const [tasksRes, seqsRes] = await Promise.all([
        apiClient.get<Task[]>("/api/tasks"),
        apiClient.get<Sequence[]>("/api/automation/jobs")
      ]);
      setTasks(tasksRes || []);
      setSequences(seqsRes || []);
    } catch (e) {
      console.error("Failed to fetch dependencies", e);
    }
  }, [isAuthenticated]);

  const fetchJobs = useCallback(async () => {
    if (!isAuthenticated) {
      setFetchError(false);
      setJobs([]);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      const res = await loadCronJobsWithRetry();
      setFetchError(false);
      setJobs(res);
    } catch (error) {
      setFetchError(true);
      if (error instanceof ApiError && (error.status === 401 || error.status === 404 || error.status === 429)) {
        setJobs([]);
      } else {
        console.error("Failed to fetch cron jobs", error);
      }
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    fetchJobs();
    fetchDependencies();
  }, [fetchJobs, fetchDependencies, isAuthLoading]);

  const handleCreateJob = async () => {
    if (!isAuthenticated) return;
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
    if (!isAuthenticated) return;
    try {
      await apiClient.put(`/api/automation/cron/${id}/toggle`, { enabled: !currentEnabled });
      fetchJobs();
    } catch (error) {
      console.error("Failed to toggle cron job", error);
    }
  };

  const handleDelete = async (id: string) => {
    if (!isAuthenticated) return;
    try {
      await apiClient.delete(`/api/automation/cron/${id}`);
      fetchJobs();
    } catch (error) {
      console.error("Failed to delete cron job", error);
    }
  };

  return (
    <div className="karen-automation karen-automation-workflow space-y-6">
      <header className="karen-automation-hero karen-surface relative overflow-hidden rounded-2xl px-5 py-6 sm:px-8 sm:py-8">
          <div className="relative z-10 flex min-w-0 items-start gap-4">
            <div className="rounded-xl border border-primary/20 bg-primary/10 p-3 text-primary"><Clock className="h-6 w-6" aria-hidden="true" /></div>
            <div className="min-w-0 space-y-2">
              <p className="karen-panel-label">KARI OS / AUTOMATIONS / SCHEDULE CONTROL</p>
              <h2 className="karen-page-title">Cron Job Assignments</h2>
              <p className="karen-page-description">Manage live scheduled automations executing on the backend.</p>
            </div>
          </div>
        </header>
      
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
          {fetchError && !loading && (
             <Alert variant="destructive"><AlertTitle>Schedules unavailable</AlertTitle><AlertDescription>Could not verify the saved schedules with the backend. Retry after the connection is restored.</AlertDescription></Alert>
          )}
          {jobs.length === 0 && !loading && !fetchError && (
             <p className="text-sm text-muted-foreground">No cron jobs configured yet.</p>
          )}
          {!fetchError && jobs.map((job, index) => (
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
                     const selectedSeq = sequences.find(t => t.id === val);
                     const selectedTask = tasks.find(t => t.id === val);
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
                        {sequences.map(t => (
                           <SelectItem key={t.id} value={t.id}>{t.name || t.id}</SelectItem>
                        ))}
                      </SelectGroup>
                      <SelectSeparator />
                      <SelectGroup>
                        <SelectLabel>Tasks</SelectLabel>
                        {tasks.map(t => (
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
              <Button onClick={handleCreateJob} className="w-full" disabled={!targetId || !schedule}>
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
