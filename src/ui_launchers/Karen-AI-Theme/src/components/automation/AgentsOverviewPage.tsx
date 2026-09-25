
"use client";

import React, { useEffect, useState, useCallback } from "react";
import useAuth from "@/lib/useAuth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Bot, Clock, Info, ArrowRight, LayoutDashboard, Lightbulb, PlusCircle, Workflow, Puzzle, Settings, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface AutomationStats {
  activeAgents: string;
  tasksToday: string;
  activeSequences: string;
  nextJob: string;
  nextJobTime: string;
}

/**
 * @file AutomationOverviewPage.tsx
 * @description An overview of the Agents & Workflows, providing live statistics for Agents, Tasks, and Cron Jobs.
 */
export default function AutomationOverviewPage() {
  const { isAuthenticated, isLoading: isAuthLoading } = useAuth();
  const [stats, setStats] = useState<AutomationStats>({
    activeAgents: "0 / 0",
    tasksToday: "0",
    activeSequences: "0",
    nextJob: "None Scheduled",
    nextJobTime: "N/A",
  });
  const [isLoading, setIsLoading] = useState(true);

  const fetchStats = useCallback(async () => {
    if (!isAuthenticated) {
      setIsLoading(false);
      return;
    }
    
    try {
      const { apiClient } = await import('@/lib/api');
      const data = await apiClient.get<AutomationStats>('/api/automation/stats/');
      if (data) {
        setStats({
          activeAgents: data.activeAgents || "0 / 0",
          tasksToday: data.tasksToday || "0",
          activeSequences: data.activeSequences || "0",
          nextJob: data.nextJob || "None Scheduled",
          nextJobTime: data.nextJobTime || "N/A",
        });
      }
    } catch (err) {
      console.error("Failed to fetch automation stats:", err);
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthLoading) {
      fetchStats();
    }
  }, [isAuthLoading, fetchStats]);
  
  return (
    <div className="space-y-8">
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
            <Button variant="outline" onClick={() => window.location.hash = "#sequences"}>
                <Workflow className="mr-2 h-4 w-4" />
                Manage Sequences
            </Button>
            <Button variant="outline" onClick={() => window.location.hash = "#tasks"}>
                <PlusCircle className="mr-2 h-4 w-4" />
                Manage Tasks
            </Button>
        </div>
      </div>

      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>System Operational</AlertTitle>
        <AlertDescription>
          The Agents & Workflows section of Karen AI is connected to the live backend. All metrics below represent real-time activity across your agents and scheduled jobs.
        </AlertDescription>
      </Alert>

      {/* Live Dashboard Section */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold flex items-center"><LayoutDashboard className="mr-2 h-5 w-5"/>Dashboard</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium">Active Agents</CardTitle>
                    <Bot className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                    <div className="text-2xl font-bold">{isLoading ? "..." : stats.activeAgents}</div>
                    <p className="text-xs text-muted-foreground">Connected agents ready to work.</p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium">Tasks Executed Today</CardTitle>
                    <FileText className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                    <div className="text-2xl font-bold">{isLoading ? "..." : stats.tasksToday}</div>
                    <p className="text-xs text-muted-foreground">Successful task runs since midnight.</p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium">Defined Sequences</CardTitle>
                    <Workflow className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                    <div className="text-2xl font-bold">{isLoading ? "..." : stats.activeSequences}</div>
                    <p className="text-xs text-muted-foreground">Multi-step persistent workflows.</p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                    <CardTitle className="text-sm font-medium">Next Scheduled Run</CardTitle>
                    <Clock className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                    <div className="text-lg font-bold truncate">{isLoading ? "..." : stats.nextJob}</div>
                    <p className="text-xs text-muted-foreground">{stats.nextJobTime}</p>
                </CardContent>
            </Card>
        </div>
      </div>

      <Separator />

      {/* Use Cases Section */}
       <div className="space-y-4">
        <h3 className="text-lg font-semibold flex items-center"><Lightbulb className="mr-2 h-5 w-5"/>Live Capabilities</h3>
         <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <Card className="bg-muted/20 border-primary/20">
              <CardHeader>
                <CardTitle className="text-base">Persistent Execution</CardTitle>
                <CardDescription>Jobs continue running even if the browser is closed.</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                    Sequences and Tasks are executed on the backend runtime, ensuring reliability for long-running processes like research and content generation.
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
                    Assign a team of agents to a single task. The primary agent manages the delegation and synthesizes the results for you.
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
                    Use the Cron scheduler to wire tasks to specific times, or trigger sequences manually via the Jobs interface.
                </p>
              </CardContent>
            </Card>
        </div>
      </div>
      
      <Separator />

      {/* How it connects section */}
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
