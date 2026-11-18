
"use client";

import { useState, useEffect } from 'react';
import apiClient, { ApiError } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Bell, Clock, FileText, Info, Server, AlertCircle, Workflow, Activity, ShieldAlert, BrainCircuit, RefreshCw, Radio } from "lucide-react";
import { Button } from "@/components/ui/button";
import { format } from 'date-fns';

type SystemAlert = {
    id: string;
    title: string;
    description: string;
    type: "info" | "warning" | "update";
    timestamp: Date;
};

type AuditEvent = {
    message?: string;
    event_type?: string;
    timestamp?: string | Date;
    [key: string]: unknown;
};

type TrainingSecurityEvent = {
    event_type?: string;
    message?: string;
    timestamp?: string | Date;
    [key: string]: unknown;
};

type ObservabilitySnapshot = {
    generated_at: string;
    audit: {
        recent_events: AuditEvent[];
        event_counts: Record<string, number>;
    };
    training: {
        event_counts: Record<string, number>;
        security_events: TrainingSecurityEvent[];
    };
    memory: {
        available: boolean;
        pending_writebacks: number;
        active_shard_links: number;
        feedback_metrics: Record<string, unknown>;
        service_metrics: Record<string, unknown>;
    };
    alerts: Array<{
        id: string;
        title: string;
        description: string;
        type: "info" | "warning" | "update";
        timestamp: string;
    }>;
};


const formatEventTime = (
    value: string | Date | undefined,
    pattern = "MMM d, HH:mm",
): string => {
    if (!value) return "Time unavailable";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Time unavailable" : format(date, pattern);
};

const metricValue = (count: number | null): string =>
    count !== null && Number.isFinite(count) && count >= 0
        ? count.toLocaleString()
        : "—";

const isObservabilitySnapshot = (value: unknown): value is ObservabilitySnapshot => {
    if (!value || typeof value !== "object") return false;
    const snapshot = value as Partial<ObservabilitySnapshot>;
    return (
        typeof snapshot.generated_at === "string" &&
        Array.isArray(snapshot.alerts) &&
        snapshot.alerts.every((alert) =>
            !!alert && typeof alert.id === "string" &&
            typeof alert.title === "string" &&
            typeof alert.description === "string" &&
            typeof alert.timestamp === "string" &&
            ["info", "warning", "update"].includes(alert.type)
        ) &&
        !!snapshot.audit &&
        Array.isArray(snapshot.audit.recent_events) &&
        snapshot.audit.recent_events.every((event) =>
            !!event && typeof event === "object" &&
            (event.message === undefined || typeof event.message === "string") &&
            (event.event_type === undefined || typeof event.event_type === "string")
        ) &&
        !!snapshot.audit.event_counts &&
        typeof snapshot.audit.event_counts === "object" &&
        Object.values(snapshot.audit.event_counts).every(
            (count) => typeof count === "number" && Number.isFinite(count) && count >= 0
        ) &&
        !!snapshot.training &&
        !!snapshot.training.event_counts &&
        typeof snapshot.training.event_counts === "object" &&
        Object.values(snapshot.training.event_counts).every(
            (count) => typeof count === "number" && Number.isFinite(count) && count >= 0
        ) &&
        Array.isArray(snapshot.training.security_events) &&
        snapshot.training.security_events.every((event) =>
            !!event && typeof event === "object" &&
            (event.message === undefined || typeof event.message === "string") &&
            (event.event_type === undefined || typeof event.event_type === "string")
        ) &&
        !!snapshot.memory &&
        typeof snapshot.memory.available === "boolean" &&
        typeof snapshot.memory.pending_writebacks === "number" &&
        Number.isFinite(snapshot.memory.pending_writebacks) &&
        snapshot.memory.pending_writebacks >= 0 &&
        typeof snapshot.memory.active_shard_links === "number" &&
        Number.isFinite(snapshot.memory.active_shard_links) &&
        snapshot.memory.active_shard_links >= 0
    );
};

/**
 * @file CommsCenterPage.tsx
 * @description Communications Center backed by live API data only.
 */
export default function CommsCenterPage() {
    const { isAuthenticated, isLoading: isAuthLoading, user } = useAuth();
    const principal = user?.tenant_id && user?.user_id
        ? user.tenant_id + ":" + user.user_id
        : null;
    const [snapshot, setSnapshot] = useState<{ principal: string; value: ObservabilitySnapshot } | null>(null);
    // Never render a previous principal's snapshot across an account switch.
    const observability = principal && snapshot?.principal === principal
        ? snapshot.value : null;
    const [observabilityError, setObservabilityError] = useState<string | null>(null);
    const [observabilityAuthRequired, setObservabilityAuthRequired] = useState(false);
    const [observabilityAccessDenied, setObservabilityAccessDenied] = useState(false);
    const [observabilityLoading, setObservabilityLoading] = useState(true);
    const [refreshRevision, setRefreshRevision] = useState(0);

    // Render only backend-confirmed observability, never synthetic metrics.
    useEffect(() => {
        if (isAuthLoading) return;

        if (!isAuthenticated || !principal) {
            setSnapshot(null);
            setObservabilityLoading(false);
            setObservabilityAuthRequired(true);
            setObservabilityAccessDenied(false);
            setObservabilityError(null);
            return;
        }

        let active = true;
        setObservabilityLoading(true);
        setSnapshot(null);
        setObservabilityError(null);
        setObservabilityAuthRequired(false);
        setObservabilityAccessDenied(false);

        const load = async () => {
            try {
                const result: unknown = await apiClient.get<unknown>(
                    "/api/communications-center/observability",
                );
                if (!isObservabilitySnapshot(result)) {
                    throw new Error("Live observability response did not match the backend contract");
                }
                if (active) setSnapshot({ principal, value: result });
            } catch (error) {
                if (!active) return;
                setSnapshot(null);
                if (error instanceof ApiError && error.status === 401) {
                    setObservabilityAuthRequired(true);
                } else if (error instanceof ApiError && error.status === 403) {
                    setObservabilityAccessDenied(true);
                } else {
                    setObservabilityError(
                        error instanceof Error ? error.message : "Live observability is unavailable",
                    );
                }
            } finally {
                if (active) setObservabilityLoading(false);
            }
        };

        void load();
        return () => { active = false; };
    }, [isAuthenticated, isAuthLoading, principal, refreshRevision]);

    const getAlertIcon = (type: SystemAlert['type']) => {
        switch (type) {
            case "info": return <Info aria-hidden="true" className="h-4 w-4 text-accent" />;
            case "warning": return <AlertCircle aria-hidden="true" className="h-4 w-4 text-warning" />;
            case "update": return <Server aria-hidden="true" className="h-4 w-4 text-primary" />;
        }
    };

    const liveAlerts: SystemAlert[] = (observability?.alerts || []).map((alert) => ({
        id: alert.id,
        title: alert.title,
        description: alert.description,
        type: alert.type,
        timestamp: new Date(alert.timestamp),
    }));

    const recentAuditEvents = observability?.audit.recent_events || [];
    const memoryStats = observability?.memory;
    const trainingEventCounts = observability?.training.event_counts || {};
    const auditEventCounts = observability?.audit.event_counts || {};
    const trainingSecurityEvents = observability?.training.security_events || [];
    const trainingSignalCount = observability
        ? Object.values(trainingEventCounts).reduce(
            (total, count) => total + (Number.isFinite(count) ? count : 0),
            0,
        )
        : null;
    const liveStatus = observabilityLoading || isAuthLoading
        ? "Connecting"
        : observability
            ? "Live snapshot"
            : observabilityAccessDenied
                ? "Access restricted"
                : observabilityAuthRequired
                    ? "Sign in required"
                    : "Unavailable";

  return (
    <div data-kari-root className="space-y-6 pb-8" data-testid="comms-center">
        <header className="karen-surface relative isolate overflow-hidden rounded-2xl bg-gradient-to-br from-card via-card to-primary/10 p-5 shadow-lg md:p-8">
            <div aria-hidden="true" className="karen-workspace-grid pointer-events-none absolute inset-0 opacity-35" />
            <div aria-hidden="true" className="pointer-events-none absolute -right-10 -top-20 h-64 w-64 rounded-full bg-primary/10 blur-3xl" />
            <div className="relative flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
                <div className="min-w-0 max-w-2xl">
                    <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 text-xs font-semibold tracking-wide text-primary">
                        <Radio aria-hidden="true" className="h-3.5 w-3.5" />
                        Communications Center
                    </div>
                    <h2 className="kari-display karen-page-title text-balance md:text-[2.25rem]">Activity &amp; Notifications</h2>
                    <p className="karen-page-description mt-3">
                        A clear view of backend audit activity, system alerts, memory operations and
                        training signals. Only verified information is shown.
                    </p>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-3 lg:flex-col lg:items-end">
                    <div role="status" className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-card/80 px-3 py-2 text-xs font-medium text-foreground">
                        <span aria-hidden="true" className={observability ? "h-2 w-2 rounded-full bg-success" : "h-2 w-2 rounded-full bg-muted-foreground/50"} />
                        {liveStatus}
                    </div>
                    <span className="karen-metric">
                        {observability ? "Updated " + formatEventTime(observability.generated_at) : "No verified snapshot"}
                    </span>
                    <Button type="button" size="sm" variant="outline" className="gap-2 bg-card/80" disabled={!isAuthenticated || isAuthLoading || observabilityLoading} onClick={() => setRefreshRevision((value) => value + 1)}>
                        <RefreshCw aria-hidden="true" className="h-4 w-4" />
                        Refresh
                    </Button>
                </div>
            </div>
        </header>

        <Tabs defaultValue="overview" className="w-full">
            <div className="overflow-x-auto pb-1" aria-label="Communications Center sections">
                <TabsList className="flex h-auto w-max min-w-full items-center justify-start gap-1 border-border/70 bg-muted/50 p-1.5">
                    <TabsTrigger value="overview" className="min-h-10 gap-2 px-3 sm:px-4">
                        <Bell aria-hidden="true" className="h-4 w-4 shrink-0" /> Overview
                    </TabsTrigger>
                    <TabsTrigger value="observability" className="min-h-10 gap-2 px-3 sm:px-4">
                        <Activity aria-hidden="true" className="h-4 w-4 shrink-0" /> Observability
                    </TabsTrigger>
                    <TabsTrigger value="logs" className="min-h-10 gap-2 px-3 sm:px-4">
                        <Clock aria-hidden="true" className="h-4 w-4 shrink-0" /> Audit timeline
                    </TabsTrigger>
                    <TabsTrigger value="notes" className="min-h-10 gap-2 px-3 sm:px-4">
                        <FileText aria-hidden="true" className="h-4 w-4 shrink-0" /> Notes
                    </TabsTrigger>
                    <TabsTrigger value="alerts" className="min-h-10 gap-2 px-3 sm:px-4">
                        <ShieldAlert aria-hidden="true" className="h-4 w-4 shrink-0" /> System alerts
                    </TabsTrigger>
                </TabsList>
            </div>

            <TabsContent value="overview" className="mt-6 space-y-6">
                {observabilityLoading && (
                    <Alert role="status" className="border-primary/20 bg-primary/5">
                        <Activity aria-hidden="true" className="h-4 w-4 text-primary" />
                        <AlertTitle>Connecting to live operations</AlertTitle>
                        <AlertDescription>Waiting for the authenticated backend snapshot. No estimated counts are shown.</AlertDescription>
                    </Alert>
                )}
                {observabilityAuthRequired && !observabilityLoading && (
                    <Alert className="border-border/70 bg-muted/40">
                        <ShieldAlert aria-hidden="true" className="h-4 w-4" />
                        <AlertTitle>Sign in required</AlertTitle>
                        <AlertDescription>Sign in to access the backend audit and operational event feed.</AlertDescription>
                    </Alert>
                )}
                {observabilityAccessDenied && !observabilityLoading && (
                    <Alert className="border-border/70 bg-muted/40">
                        <ShieldAlert aria-hidden="true" className="h-4 w-4" />
                        <AlertTitle>Observability access restricted</AlertTitle>
                        <AlertDescription>Your session is authenticated, but this account is not authorized to view these events.</AlertDescription>
                    </Alert>
                )}
                {observabilityError && !observabilityLoading && (
                    <Alert className="border-warning/30 bg-warning/5">
                        <AlertCircle aria-hidden="true" className="h-4 w-4 text-warning" />
                        <AlertTitle>Live activity unavailable</AlertTitle>
                        <AlertDescription>{observabilityError}. No fallback or synthetic activity is displayed.</AlertDescription>
                    </Alert>
                )}

                <section aria-label="Operational snapshot" className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
                    <Card className="overflow-hidden border-primary/25 bg-gradient-to-br from-card to-primary/10">
                        <CardContent className="space-y-4 p-5">
                            <div className="flex items-center justify-between">
                                <span className="karen-panel-label">Audit events</span>
                                <span className="rounded-lg bg-primary/10 p-2 text-primary"><Activity aria-hidden="true" className="h-5 w-5" /></span>
                            </div>
                            <div className="text-3xl font-semibold tracking-tight tabular-nums" data-testid="comms-metric-audit">
                                {metricValue(observability ? recentAuditEvents.length : null)}
                            </div>
                            <p className="text-sm text-muted-foreground">Events in the current backend snapshot</p>
                        </CardContent>
                    </Card>
                    <Card className="overflow-hidden bg-gradient-to-br from-card to-accent/5">
                        <CardContent className="space-y-4 p-5">
                            <div className="flex items-center justify-between">
                                <span className="karen-panel-label">System alerts</span>
                                <span className="rounded-lg bg-accent/10 p-2 text-accent"><Bell aria-hidden="true" className="h-5 w-5" /></span>
                            </div>
                            <div className="text-3xl font-semibold tracking-tight tabular-nums" data-testid="comms-metric-alerts">
                                {metricValue(observability ? liveAlerts.length : null)}
                            </div>
                            <p className="text-sm text-muted-foreground">Alerts reported by the backend</p>
                        </CardContent>
                    </Card>
                    <Card className="overflow-hidden bg-gradient-to-br from-card to-primary/5">
                        <CardContent className="space-y-4 p-5">
                            <div className="flex items-center justify-between">
                                <span className="karen-panel-label">Writeback queue</span>
                                <span className="rounded-lg bg-primary/10 p-2 text-primary"><Workflow aria-hidden="true" className="h-5 w-5" /></span>
                            </div>
                            <div className="text-3xl font-semibold tracking-tight tabular-nums" data-testid="comms-metric-writebacks">
                                {metricValue(observability && memoryStats?.available ? memoryStats.pending_writebacks : null)}
                            </div>
                            <p className="text-sm text-muted-foreground">{memoryStats?.available && observability ? "Pending governed memory writebacks" : "Memory service status not verified"}</p>
                        </CardContent>
                    </Card>
                    <Card className="overflow-hidden bg-gradient-to-br from-card to-accent/5">
                        <CardContent className="space-y-4 p-5">
                            <div className="flex items-center justify-between">
                                <span className="karen-panel-label">Training signals</span>
                                <span className="rounded-lg bg-accent/10 p-2 text-accent"><BrainCircuit aria-hidden="true" className="h-5 w-5" /></span>
                            </div>
                            <div className="text-3xl font-semibold tracking-tight tabular-nums" data-testid="comms-metric-training">
                                {metricValue(trainingSignalCount)}
                            </div>
                            <p className="text-sm text-muted-foreground">Reported training audit events</p>
                        </CardContent>
                    </Card>
                </section>

                <section className="grid gap-5 xl:grid-cols-12" aria-label="Recent operational activity">
                    <Card className="overflow-hidden xl:col-span-7">
                        <CardHeader className="border-b border-border/60 bg-muted/20">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <CardTitle className="text-lg">Recent audit activity</CardTitle>
                                    <CardDescription className="mt-1">Backend audit events, not a substitute for automation run receipts.</CardDescription>
                                </div>
                                <span aria-hidden="true" className="rounded-lg bg-primary/10 p-2 text-primary"><Activity className="h-5 w-5" /></span>
                            </div>
                        </CardHeader>
                        <CardContent className="p-5">
                            {recentAuditEvents.length > 0 ? (
                                <ol className="space-y-4">
                                    {recentAuditEvents.slice(0, 6).map((event, index) => (
                                        <li key={String(event.timestamp || index) + "-" + String(event.event_type || "event")} className="flex gap-3">
                                            <span aria-hidden="true" className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-primary shadow-[0_0_0_4px_hsl(var(--primary)/0.12)]" />
                                            <div className="min-w-0 flex-1 border-b border-border/50 pb-3 last:border-b-0">
                                                <div className="flex flex-wrap items-start justify-between gap-2">
                                                    <p className="break-words text-sm font-medium text-foreground">{event.message || event.event_type || "Audit event"}</p>
                                                    <span className="karen-metric shrink-0">{formatEventTime(event.timestamp)}</span>
                                                </div>
                                                <p className="mt-1 text-xs text-muted-foreground">{event.event_type || "Audit"}</p>
                                            </div>
                                        </li>
                                    ))}
                                </ol>
                            ) : (
                                <div className="flex min-h-44 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border/80 bg-muted/20 p-6 text-center">
                                    <Activity aria-hidden="true" className="h-7 w-7 text-muted-foreground/60" />
                                    <p className="text-sm font-medium">{observability ? "No audit events in this snapshot" : "Audit activity not available"}</p>
                                    <p className="max-w-xs text-xs text-muted-foreground">{observability ? "The backend returned an empty recent-event buffer." : "An authenticated, authorized snapshot is required."}</p>
                                </div>
                            )}
                        </CardContent>
                    </Card>

                    <Card className="overflow-hidden xl:col-span-5">
                        <CardHeader className="border-b border-border/60 bg-muted/20">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <CardTitle className="text-lg">Latest system alerts</CardTitle>
                                    <CardDescription className="mt-1">System-reported updates that may need attention.</CardDescription>
                                </div>
                                <span aria-hidden="true" className="rounded-lg bg-accent/10 p-2 text-accent"><Bell className="h-5 w-5" /></span>
                            </div>
                        </CardHeader>
                        <CardContent className="p-5">
                            {liveAlerts.length > 0 ? (
                                <ul className="space-y-3">
                                    {liveAlerts.slice(0, 5).map((alert) => (
                                        <li key={alert.id} className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 p-3">
                                            <span className="mt-0.5">{getAlertIcon(alert.type)}</span>
                                            <div className="min-w-0 flex-1">
                                                <p className="text-sm font-semibold">{alert.title}</p>
                                                <p className="mt-1 break-words text-sm text-muted-foreground">{alert.description}</p>
                                                <p className="karen-metric mt-2">{formatEventTime(alert.timestamp)}</p>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="flex min-h-44 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border/80 bg-muted/20 p-6 text-center">
                                    <Bell aria-hidden="true" className="h-7 w-7 text-muted-foreground/60" />
                                    <p className="text-sm font-medium">{observability ? "No system alerts in this snapshot" : "System alerts not available"}</p>
                                    <p className="max-w-xs text-xs text-muted-foreground">{observability ? "No alert records were returned by the backend." : "Live alerts require an authorized backend response."}</p>
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </section>
                <div className="flex items-start gap-3 rounded-xl border border-border/60 bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
                    <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    <p>Automation execution history and generated notes require their own verified backend records. This view does not manufacture either from generic audit events.</p>
                </div>
            </TabsContent>

            <TabsContent value="observability" className="mt-6 space-y-6">
                {observabilityLoading ? (
                    <Card><CardHeader><CardTitle>Loading observability</CardTitle><CardDescription>Waiting for the authenticated backend snapshot.</CardDescription></CardHeader></Card>
                ) : observabilityError ? (
                    <Card><CardHeader><CardTitle>Observability unavailable</CardTitle><CardDescription>{observabilityError}</CardDescription></CardHeader></Card>
                ) : observabilityAuthRequired ? (
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <ShieldAlert className="h-5 w-5 text-primary" />
                                Sign In Required
                            </CardTitle>
                            <CardDescription>
                                The backend observability surface is live, but this session is not authenticated.
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-3 text-sm text-muted-foreground">
                            <p>
                                Communications Center is still available, but backend-derived observability panels require an authenticated session.
                            </p>
                            <div className="rounded-md border bg-muted/40 p-3">
                                Sign in, then reload this tab to inspect live memory, audit, and training telemetry.
                            </div>
                        </CardContent>
                    </Card>
                ) : observabilityAccessDenied ? (
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <ShieldAlert className="h-5 w-5 text-primary" />
                                Observability Access Restricted
                            </CardTitle>
                            <CardDescription>
                                The backend observability surface is live, but this session is not authorized to inspect memory, audit, and training telemetry.
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-3 text-sm text-muted-foreground">
                            <p>
                                Communications Center is still available, but backend-derived observability panels require the appropriate permissions.
                            </p>
                            <div className="rounded-md border bg-muted/40 p-3">
                                Request elevated access if you need live writeback, audit, or training-governance visibility.
                            </div>
                        </CardContent>
                    </Card>
                ) : !observability ? (
                    <Card><CardHeader><CardTitle>No verified observability</CardTitle><CardDescription>Live metrics are unavailable from the backend.</CardDescription></CardHeader></Card>
                ) : (
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
                    <Card className="xl:col-span-1">
                        <CardHeader>
                            <CardTitle>Memory Observability</CardTitle>
                            <CardDescription>Account-scoped feedback and verified queue status only.</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4 text-sm">
                            <div className="flex items-center justify-between">
                                <span className="text-muted-foreground">Account-scoped queue metrics</span>
                                <Badge variant={memoryStats?.available ? "secondary" : "outline"}>
                                    {memoryStats?.available ? "Verified" : "Not verified"}
                                </Badge>
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-muted-foreground">Pending writebacks</span>
                                <span className="font-medium" data-testid="comms-observability-pending">{metricValue(memoryStats?.available ? memoryStats.pending_writebacks : null)}</span>
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-muted-foreground">Active shard links</span>
                                <span className="font-medium" data-testid="comms-observability-shards">{metricValue(memoryStats?.available ? memoryStats.active_shard_links : null)}</span>
                            </div>
                            <details className="rounded-md border bg-muted/40 p-3">
                                <summary className="cursor-pointer text-xs font-semibold text-muted-foreground">Feedback diagnostics</summary>
                                <pre className="text-xs whitespace-pre-wrap break-words">
{JSON.stringify(memoryStats?.feedback_metrics || {}, null, 2)}
                                </pre>
                            </details>
                        </CardContent>
                    </Card>

                    <Card className="xl:col-span-1">
                        <CardHeader>
                            <CardTitle>Training Governance</CardTitle>
                            <CardDescription>Event counts and training security telemetry.</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="rounded-md border bg-muted/40 p-3">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">Training Event Counts</p>
                                <div className="space-y-2">
                                    {Object.entries(trainingEventCounts).length > 0 ? Object.entries(trainingEventCounts).map(([key, value]) => (
                                        <div key={key} className="flex items-center justify-between text-sm">
                                            <span className="text-muted-foreground">{key}</span>
                                            <span className="font-medium">{value}</span>
                                        </div>
                                    )) : (
                                        <p className="text-sm text-muted-foreground">No training audit events captured yet.</p>
                                    )}
                                </div>
                            </div>
                            <div className="rounded-md border bg-muted/40 p-3">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">Security Events</p>
                                <div className="space-y-3">
                                    {trainingSecurityEvents.length > 0 ? trainingSecurityEvents.slice(-5).map((event, index) => (
                                        <div key={`${event.timestamp ?? index}`} className="text-sm">
                                            <div className="font-medium">{event.message || event.event_type}</div>
                                            <div className="text-xs text-muted-foreground">
                                                {event.timestamp ? formatEventTime(event.timestamp) : 'Unknown time'}
                                            </div>
                                        </div>
                                    )) : (
                                        <p className="text-sm text-muted-foreground">No recent training security events.</p>
                                    )}
                                </div>
                            </div>
                        </CardContent>
                    </Card>

                    <Card className="xl:col-span-1">
                        <CardHeader>
                            <CardTitle>Audit Trail</CardTitle>
                            <CardDescription>Recent backend audit events visible to the Communications Center.</CardDescription>
                        </CardHeader>
                        <CardContent>
                            <ScrollArea className="h-96">
                                <div className="space-y-3">
                                    {recentAuditEvents.length > 0 ? recentAuditEvents.map((event, index) => (
                                        <div key={`${event.timestamp ?? index}-${event.event_type ?? 'event'}`} className="rounded-md border bg-muted/40 p-3 text-sm">
                                            <div className="flex items-center justify-between gap-3">
                                                <span className="font-medium">{event.message || event.event_type || 'Audit event'}</span>
                                                <Badge variant="outline">{event.event_type || 'unknown'}</Badge>
                                            </div>
                                            <div className="mt-1 text-xs text-muted-foreground">
                                                {event.timestamp ? formatEventTime(event.timestamp, 'MMM d, HH:mm:ss') : 'Unknown time'}
                                            </div>
                                        </div>
                                    )) : (
                                        <p className="text-sm text-muted-foreground">No buffered audit events available.</p>
                                    )}
                                </div>
                            </ScrollArea>
                        </CardContent>
                    </Card>
                </div>
                )}
            </TabsContent>
            
            <TabsContent value="logs" className="mt-6">
                 <Card>
                    <CardHeader>
                        <CardTitle>Audit event timeline</CardTitle>
                        <CardDescription>Recent backend audit events. For actual task execution receipts, use the automation workspace.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <ScrollArea className="h-96">
                            <div className="space-y-4">
                                {recentAuditEvents.length > 0 ? recentAuditEvents.map((event, index) => (
                                    <div key={`${event.timestamp ?? index}-${event.event_type ?? 'event'}`} className="flex items-center space-x-4 p-2 rounded-md border bg-muted/40">
                                        <div className="min-w-0 flex-1 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
                                            <div className="min-w-0 sm:flex-1">
                                                <p className="font-semibold text-foreground truncate">{event.message || event.event_type || 'Audit event'}</p>
                                                <Badge variant="secondary">Audit</Badge>
                                            </div>
                                            <div className="flex items-center space-x-2">
                                                <Clock className="h-3.5 w-3.5 text-muted-foreground"/>
                                                <span className="text-xs text-muted-foreground">{event.timestamp ? formatEventTime(event.timestamp, 'MMM d, HH:mm:ss') : 'Unknown time'}</span>
                                            </div>
                                            <div>
                                                <Badge variant="outline">{event.event_type || 'unknown'}</Badge>
                                            </div>
                                        </div>
                                    </div>
                                )) : (
                                    <Alert variant="default" className="border-yellow-500/30 bg-yellow-500/5">
                                        <AlertCircle className="h-4 w-4 !text-yellow-600" />
                                        <AlertTitle>{observability ? "No audit events in this snapshot" : "Audit events unavailable"}</AlertTitle>
                                        <AlertDescription>
                                            {observability ? "The backend returned no recent audit events." : "The backend audit feed is not available. No synthetic log data is shown."}
                                        </AlertDescription>
                                    </Alert>
                                )}
                            </div>
                        </ScrollArea>
                    </CardContent>
                 </Card>
            </TabsContent>

            <TabsContent value="notes" className="mt-6">
                <Card>
                    <CardHeader>
                        <CardTitle>Generated notes & summaries</CardTitle>
                        <CardDescription>Notes and summaries are displayed here only when a governed backend source is available.</CardDescription>
                    </CardHeader>
                    <CardContent>
                       <ScrollArea className="h-96">
                           <div className="space-y-4">
                                <Alert variant="default" className="border-yellow-500/30 bg-yellow-500/5">
                                    <AlertCircle className="h-4 w-4 !text-yellow-600" />
                                    <AlertTitle>Generated notes unavailable</AlertTitle>
                                    <AlertDescription>
                                        Generated notes are not currently exposed by an authorized backend API for this view. No placeholder notes are displayed.
                                    </AlertDescription>
                                </Alert>
                            </div>
                        </ScrollArea>
                    </CardContent>
                </Card>
            </TabsContent>

            <TabsContent value="alerts" className="mt-6">
                <Card>
                    <CardHeader>
                        <CardTitle>System alerts & notifications</CardTitle>
                        <CardDescription>Important updates and information about the KAREN system.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <ScrollArea className="h-96">
                            <ul className="space-y-3">
                                {liveAlerts.length > 0 ? liveAlerts.map(alert => (
                                    <li key={alert.id} className="flex items-start space-x-4 p-3 rounded-lg border bg-muted/40">
                                        <div className="mt-1">{getAlertIcon(alert.type)}</div>
                                        <div className="flex-1">
                                            <p className="font-semibold text-foreground">{alert.title}</p>
                                            <p className="text-sm text-muted-foreground">{alert.description}</p>
                                            <p className="text-xs text-muted-foreground/70 mt-1">{formatEventTime(alert.timestamp)}</p>
                                        </div>
                                    </li>
                                )) : (
                                    <Alert variant="default" className="border-yellow-500/30 bg-yellow-500/5">
                                        <AlertCircle className="h-4 w-4 !text-yellow-600" />
                                        <AlertTitle>{observability ? "No system alerts in this snapshot" : "System alerts unavailable"}</AlertTitle>
                                        <AlertDescription>
                                            {observability ? "The backend returned no current alerts." : "Live system alerts are currently unavailable from the backend."}
                                        </AlertDescription>
                                    </Alert>
                                )}
                            </ul>
                        </ScrollArea>
                    </CardContent>
                </Card>
            </TabsContent>
        </Tabs>
    </div>
  );
}
