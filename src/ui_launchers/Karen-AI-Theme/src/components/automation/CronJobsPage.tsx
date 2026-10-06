
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
      setJobs([]);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      const res = await loadCronJobsWithRetry();
      setJobs(res);
    } catch (error) {
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
    <div className="space-y-8">
      <div className="flex items-center space-x-3">
        <Clock className="h-8 w-8 text-primary" />
        <div>
          <h2 className="karen-page-title">Cron Job Assignments</h2>
          <p className="text-sm text-muted-foreground">
            Manage live scheduled automations executing on the backend.
          </p>
        </div>
      </div>
      
      <Alert>
        <Clock className="h-4 w-4" />
        <AlertTitle>Scheduler Connected</AlertTitle>
        <AlertDescription>
          Jobs created below are saved to backend memory and evaluated in real-time. Use the toggles to enable or disable live workflows.
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Cron Job List */}
        <div className="lg:col-span-2 space-y-4">
          <h3 className="text-lg font-semibold">Scheduled Jobs {loading && <span className="text-sm font-normal text-muted-foreground ml-2">(Syncing...)</span>}</h3>
          {jobs.length === 0 && !loading && (
             <p className="text-sm text-muted-foreground">No cron jobs configured yet.</p>
          )}
          {jobs.map((job, index) => (
            <Card key={job.id || index}>
              <CardHeader>
                 <div className="flex justify-between items-start">
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
                  <div className="flex items-center space-x-1">
                      <Switch 
                        checked={job.enabled} 
                        onCheckedChange={() => handleToggle(job.id, job.enabled)}
                        className="data-[state=checked]:bg-green-600"
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
        <div className="lg:col-span-1">
           <Card className="sticky top-20">
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
         The backend scheduler evaluates due runs natively using `croniter`. Creating a job dynamically enqueues it to the live polling system without restarts. Future scope includes duckdb durability to survive restarts.
        </AlertDescription>
      </Alert>
    </div>
  );
}
