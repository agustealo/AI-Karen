"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  Bot,
  Clock,
  FileText,
  Info,
  LayoutDashboard,
  Lightbulb,
  PlusCircle,
  Puzzle,
  RefreshCw,
  Settings,
  Workflow,
} from "lucide-react";

import useAuth from "@/lib/useAuth";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  automationStatsReadinessIssue,
  parseAutomationStats,
  type AutomationStats,
} from "./automationStats";

type StatsState = "loading" | "ready" | "unavailable";

/**
 * @file AgentsOverviewPage.tsx
 * @description Live tenant-scoped overview of Agents & Workflows.
 */
export default function AutomationOverviewPage() {
  const { isAuthenticated, isLoading: isAuthLoading } = useAuth();
  const [stats, setStats] = useState<AutomationStats | null>(null);
  const [statsState, setStatsState] = useState<StatsState>("loading");
  const [statsError, setStatsError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    if (!isAuthenticated) {
      setStats(null);
      setStatsState("unavailable");
      setStatsError("Sign in is required to load tenant-scoped automation metrics.");
      return;
    }

    setStats(null);
    setStatsState("loading");
    setStatsError(null);

    try {
      const { apiClient } = await import("@/lib/api");
      const payload = await apiClient.get<unknown>("/api/automation/stats/");
      const parsed = parseAutomationStats(payload);
      if (!parsed) {
        throw new Error("Automation statistics response did not match the live contract");
      }

      setStats(parsed);
      const readinessIssue = automationStatsReadinessIssue(parsed);
      if (readinessIssue) {
        setStatsState("unavailable");
        setStatsError(readinessIssue);
        return;
      }

      setStatsState("ready");
    } catch (error) {
      console.error("Failed to fetch automation stats:", error);
      setStats(null);
      setStatsState("unavailable");
      setStatsError(
        "Live automation metrics could not be verified. No fallback values are being shown.",
      );
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthLoading) {
      void fetchStats();
    }
  }, [isAuthLoading, fetchStats]);

  const metric = (value: string | undefined) => {
    if (statsState === "loading") {
      return "…";
    }
    return value ?? "Unavailable";
  };

  return (
    <div className="space-y-8" data-showcase-state={statsState}>
      <div className="flex justify-between items-start">
        <div className="flex items-center space-x-3">
          <Settings className="h-8 w-8 text-primary" />
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">Agents Overview</h2>
            <p className="text-sm text-muted-foreground">
              Orchestrate autonomous operations with persistent agents and workflows.
            </p>
          </div>
        </div>
        <div className="flex space-x-2">
          <Button variant="outline" onClick={() => (window.location.hash = "#sequences")}>
            <Workflow className="mr-2 h-4 w-4" />
            Manage Sequences
          </Button>
          <Button variant="outline" onClick={() => (window.location.hash = "#tasks")}>
            <PlusCircle className="mr-2 h-4 w-4" />
            Manage Tasks
          </Button>
        </div>
      </div>

      {statsState === "ready" && (
        <Alert data-automation-stats-state="ready">
          <Info className="h-4 w-4" />
          <AlertTitle>Live Runtime Connected</AlertTitle>
          <AlertDescription>
            KAREN Agents & Workflows is connected to the tenant-scoped backend. The dashboard metrics below are the values returned by the live automation runtime.
          </AlertDescription>
        </Alert>
      )}

      {statsState === "loading" && (
        <Alert data-automation-stats-state="loading">
          <Info className="h-4 w-4" />
          <AlertTitle>Loading Automation Runtime</AlertTitle>
          <AlertDescription>
            Waiting for verified tenant-scoped automation metrics from the backend.
          </AlertDescription>
        </Alert>
      )}

      {statsState === "unavailable" && (
        <Alert variant="destructive" data-automation-stats-state="unavailable">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Automation Metrics Unavailable</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>{statsError}</p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void fetchStats()}
              disabled={!isAuthenticated}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry live metrics
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <div className="space-y-4">
        <h3 className="text-lg font-semibold flex items-center">
          <LayoutDashboard className="mr-2 h-5 w-5" />Dashboard
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Active Agents</CardTitle>
              <Bot className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold" data-automation-metric="active-agents">
                {metric(stats?.activeAgents)}
              </div>
              <p className="text-xs text-muted-foreground">Connected agents in active runtime states.</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Tasks Executed Today</CardTitle>
              <FileText className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold" data-automation-metric="tasks-today">
                {metric(stats?.tasksToday)}
              </div>
              <p className="text-xs text-muted-foreground">Task runs recorded since midnight.</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Defined Sequences</CardTitle>
              <Workflow className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold" data-automation-metric="active-sequences">
                {metric(stats?.activeSequences)}
              </div>
              <p className="text-xs text-muted-foreground">Durable automation jobs visible to this tenant.</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Next Scheduled Run</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-lg font-bold truncate" data-automation-metric="next-job">
                {metric(stats?.nextJob)}
              </div>
              <p className="text-xs text-muted-foreground" data-automation-metric="next-job-time">
                {metric(stats?.nextJobTime)}
              </p>
            </CardContent>
          </Card>
        </div>
      </div>

      <Separator />

      <div className="space-y-4">
        <h3 className="text-lg font-semibold flex items-center">
          <Lightbulb className="mr-2 h-5 w-5" />Live Capabilities
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <Card className="bg-muted/20 border-primary/20">
            <CardHeader>
              <CardTitle className="text-base">Persistent Execution</CardTitle>
              <CardDescription>Jobs continue running even if the browser is closed.</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Sequences and Tasks are executed on the backend runtime, supporting long-running work without browser ownership.
              </p>
            </CardContent>
          </Card>
          <Card className="bg-muted/20 border-primary/20">
            <CardHeader>
              <CardTitle className="text-base">Agent Collaboration</CardTitle>
              <CardDescription>Primary agents can orchestrate sub-agents.</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Assign delegated agents to a task while the primary agent coordinates execution and synthesizes the result.
              </p>
            </CardContent>
          </Card>
          <Card className="bg-muted/20 border-primary/20">
            <CardHeader>
              <CardTitle className="text-base">Event-Driven Toggles</CardTitle>
              <CardDescription>Enable or disable live workflows instantly.</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Use the Cron scheduler to wire tasks to specific times, or trigger sequences manually through the Jobs interface.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>

      <Separator />

      <Card className="bg-muted/30">
        <CardHeader>
          <CardTitle className="text-lg">The Operational Flow</CardTitle>
          <CardDescription>Leverage modular components to build sophisticated autonomous systems.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col md:flex-row items-center justify-center space-y-4 md:space-y-0 md:space-x-4 text-center">
            <div className="flex flex-col items-center max-w-[10rem]">
              <div className="flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 mb-2">
                <Puzzle className="h-6 w-6 text-primary" />
              </div>
              <p className="font-semibold">1. Tools</p>
              <p className="text-xs text-muted-foreground">Foundational functions provided by plugins.</p>
            </div>
            <ArrowRight className="h-6 w-6 text-muted-foreground hidden md:block" />
            <div className="flex flex-col items-center max-w-[10rem]">
              <div className="flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 mb-2">
                <Bot className="h-6 w-6 text-primary" />
              </div>
              <p className="font-semibold">2. Agents</p>
              <p className="text-xs text-muted-foreground">Autonomous workers with specialized skills.</p>
            </div>
            <ArrowRight className="h-6 w-6 text-muted-foreground hidden md:block" />
            <div className="flex flex-col items-center max-w-[10rem]">
              <div className="flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 mb-2">
                <FileText className="h-6 w-6 text-primary" />
              </div>
              <p className="font-semibold">3. Tasks</p>
              <p className="text-xs text-muted-foreground">Specific objectives assigned to primary agents.</p>
            </div>
            <ArrowRight className="h-6 w-6 text-muted-foreground hidden md:block" />
            <div className="flex flex-col items-center max-w-[10rem]">
              <div className="flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 mb-2">
                <Workflow className="h-6 w-6 text-primary" />
              </div>
              <p className="font-semibold">4. Sequences</p>
              <p className="text-xs text-muted-foreground">Chained tasks forming a persistent workflow.</p>
            </div>
            <ArrowRight className="h-6 w-6 text-muted-foreground hidden md:block" />
            <div className="flex flex-col items-center max-w-[10rem]">
              <div className="flex items-center justify-center w-12 h-12 rounded-full bg-primary/10 mb-2">
                <Clock className="h-6 w-6 text-primary" />
              </div>
              <p className="font-semibold">5. Schedules</p>
              <p className="text-xs text-muted-foreground">Automated triggers via cron expressions.</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
