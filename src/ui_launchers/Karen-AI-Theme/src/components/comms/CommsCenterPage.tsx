
"use client";

import { useState, useEffect } from 'react';
import { KAREN_SUGGESTED_FACTS_LS_KEY } from '@/lib/constants';
import apiClient, { ApiError } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Bell, Bot, Clock, FileText, Info, MessageSquarePlus, Server, AlertCircle, Workflow, Lightbulb, Activity, ShieldAlert, BrainCircuit } from "lucide-react";
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

/**
 * @file CommsCenterPage.tsx
 * @description Communications Center backed by live API data only.
 */
export default function CommsCenterPage() {
    const { isAuthenticated, isLoading: isAuthLoading } = useAuth();
    const [suggestedFacts, setSuggestedFacts] = useState<string[]>([]);
    const [observability, setObservability] = useState<ObservabilitySnapshot | null>(null);
    const [observabilityError, setObservabilityError] = useState<string | null>(null);
    const [observabilityAuthRequired, setObservabilityAuthRequired] = useState(false);
    const [observabilityAccessDenied, setObservabilityAccessDenied] = useState(false);

    // Load suggested facts from localStorage
    useEffect(() => {
        try {
            const storedFacts = localStorage.getItem(KAREN_SUGGESTED_FACTS_LS_KEY);
            setSuggestedFacts(storedFacts ? JSON.parse(storedFacts) : []);
        } catch (error) {
            console.error("Failed to load suggested facts from localStorage:", error);
            setSuggestedFacts([]);
        }
    }, []);

    useEffect(() => {
        let isMounted = true;

        const loadObservability = async () => {
            if (isAuthLoading || !isAuthenticated) {
                return;
            }
            try {
                if (isMounted) {
                    setObservabilityAuthRequired(false);
                    setObservabilityAccessDenied(false);
                }
                const snapshot = await apiClient.get<ObservabilitySnapshot>('/api/communications-center/observability');
                if (isMounted) {
                    setObservability(snapshot);
                    setObservabilityError(null);
                    setObservabilityAuthRequired(false);
                    setObservabilityAccessDenied(false);
                }
            } catch (error) {
                if (isMounted) {
                    if (error instanceof ApiError && error.status === 401) {
                        setObservability(null);
                        setObservabilityAuthRequired(true);
                        setObservabilityAccessDenied(false);
                        setObservabilityError(null);
                    } else if (error instanceof ApiError && error.status === 403) {
                        setObservability(null);
                        setObservabilityAuthRequired(false);
                        setObservabilityAccessDenied(true);
                        setObservabilityError(null);
                    } else {
                        setObservability(null);
                        setObservabilityAuthRequired(false);
                        setObservabilityAccessDenied(false);
                        setObservabilityError(error instanceof Error ? error.message : 'Failed to load observability data');
                    }
                }
            }
        };

        loadObservability();
        return () => {
            isMounted = false;
        };
    }, [isAuthenticated, isAuthLoading]);

    const emitCommsDegradedTelemetry = (surface: string, reason: string) => {
        console.warn(`[comms-center][degraded] ${surface}: ${reason}`);
    };

    useEffect(() => {
        if (observabilityAuthRequired) emitCommsDegradedTelemetry('observability', 'auth_required');
        if (observabilityAccessDenied) emitCommsDegradedTelemetry('observability', 'access_denied');
        if (observabilityError) emitCommsDegradedTelemetry('observability', observabilityError);
    }, [observabilityAuthRequired, observabilityAccessDenied, observabilityError]);

    const getAlertIcon = (type: SystemAlert['type']) => {
        switch (type) {
            case "info": return <Info className="h-4 w-4 text-blue-500" />;
            case "warning": return <AlertCircle className="h-4 w-4 text-yellow-500" />;
            case "update": return <Server className="h-4 w-4 text-primary" />;
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

  return (
    <div className="space-y-6">
        <div>
            <h2 className="text-2xl font-semibold tracking-tight">Communications Center</h2>
            <p className="text-sm text-muted-foreground">
            A central hub for updates from Karen, automation logs, system alerts, and generated notes.
            </p>
        </div>
        <Separator />
        
        <Tabs defaultValue="overview" className="w-full">
            <TabsList className="grid w-full grid-cols-5">
                <TabsTrigger value="overview">
                    <Bell className="mr-2 h-4 w-4" /> Overview
                </TabsTrigger>
                <TabsTrigger value="observability">
                    <Activity className="mr-2 h-4 w-4" /> Observability
                </TabsTrigger>
                <TabsTrigger value="logs">
                    <Bot className="mr-2 h-4 w-4" /> Automation Logs
                </TabsTrigger>
                <TabsTrigger value="notes">
                    <FileText className="mr-2 h-4 w-4" /> Notes & Summaries
                </TabsTrigger>
                <TabsTrigger value="alerts">
                    <Server className="mr-2 h-4 w-4" /> System Alerts
                </TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-4 space-y-6">
                {observabilityAuthRequired && (
                    <Alert variant="default" className="border-primary/20 bg-primary/5">
                        <ShieldAlert className="h-4 w-4 !text-primary" />
                        <AlertTitle>Sign In Required</AlertTitle>
                        <AlertDescription>
                            Live Communications Center telemetry is available, but this session is not authenticated. Sign in to load backend observability data.
                        </AlertDescription>
                    </Alert>
                )}
                {observabilityAccessDenied && (
                    <Alert variant="default" className="border-primary/20 bg-primary/5">
                        <ShieldAlert className="h-4 w-4 !text-primary" />
                        <AlertTitle>Observability Access Restricted</AlertTitle>
                        <AlertDescription>
                            Live Communications Center telemetry is available from the backend, but this account does not have permission to view it.
                        </AlertDescription>
                    </Alert>
                )}
                {observabilityError && (
                    <Alert variant="default" className="border-yellow-500/30 bg-yellow-500/5">
                        <AlertCircle className="h-4 w-4 !text-yellow-600" />
                        <AlertTitle>Observability Fallback</AlertTitle>
                        <AlertDescription>
                            Live observability data could not be loaded. Showing local Communications Center content only.
                        </AlertDescription>
                    </Alert>
                )}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Suggested Facts */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center text-lg">
                                <MessageSquarePlus className="mr-2 h-5 w-5 text-primary"/>
                                Suggested Facts for Review
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                           {suggestedFacts.length > 0 ? (
                                <>
                                 <Alert variant="default" className="bg-primary/5 border-primary/20 mb-4">
                                    <Lightbulb className="h-4 w-4 !text-primary/80" />
                                    <AlertDescription className="text-xs text-primary/90">
                                    Karen has identified new information. Go to <strong>Settings &gt; Facts</strong> to confirm or dismiss these.
                                    </AlertDescription>
                                </Alert>
                                <ScrollArea className="h-48">
                                    <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                                        {suggestedFacts.map((fact, index) => (
                                            <li key={index} className="truncate">{fact}</li>
                                        ))}
                                    </ul>
                                </ScrollArea>
                                </>
                           ) : (
                               <p className="text-sm text-muted-foreground text-center py-10">No new facts suggested by Karen recently.</p>
                           )}
                        </CardContent>
                    </Card>

                     {/* Latest Automation Log */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center text-lg">
                                <Bot className="mr-2 h-5 w-5 text-primary"/>
                                Latest Automation Activity
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                             <ul className="space-y-3">
                                {recentAuditEvents.slice(0, 4).map((event, index) => (
                                    <li key={`${event.timestamp ?? index}-${event.event_type ?? 'event'}`} className="flex items-center space-x-3 text-sm">
                                        <Badge variant="secondary" className="w-20 justify-center">Audit</Badge>
                                        <span className="flex-1 truncate font-medium text-foreground">{event.message || event.event_type || 'Event'}</span>
                                        <span className="text-xs text-muted-foreground">{event.timestamp ? format(new Date(event.timestamp), "HH:mm") : "Unknown"}</span>
                                    </li>
                                ))}
                            </ul>
                        </CardContent>
                    </Card>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center text-lg">
                                <Workflow className="mr-2 h-5 w-5 text-primary" />
                                Writeback Queue
                            </CardTitle>
                            <CardDescription>Governed memory retention status from the backend.</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-2">
                            <div className="text-2xl font-semibold">{memoryStats?.pending_writebacks ?? 0}</div>
                            <p className="text-sm text-muted-foreground">Pending writebacks</p>
                            <Badge variant={(memoryStats?.pending_writebacks ?? 0) > 0 ? "outline" : "secondary"}>
                                {(memoryStats?.pending_writebacks ?? 0) > 0 ? "Needs Processing" : "Healthy"}
                            </Badge>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center text-lg">
                                <FileText className="mr-2 h-5 w-5 text-primary" />
                                Audit Events
                            </CardTitle>
                            <CardDescription>Recent backend audit trail activity.</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-2">
                            <div className="text-2xl font-semibold">{recentAuditEvents.length}</div>
                            <p className="text-sm text-muted-foreground">Buffered recent events</p>
                            <Badge variant="secondary">{Object.keys(auditEventCounts).length} event types</Badge>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center text-lg">
                                <BrainCircuit className="mr-2 h-5 w-5 text-primary" />
                                Training Signals
                            </CardTitle>
                            <CardDescription>Curated learning and training audit telemetry.</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-2">
                            <div className="text-2xl font-semibold">{Object.values(trainingEventCounts).reduce((sum, value) => sum + value, 0)}</div>
                            <p className="text-sm text-muted-foreground">Training audit events</p>
                            <Badge variant={trainingSecurityEvents.length > 0 ? "outline" : "secondary"}>
                                {trainingSecurityEvents.length > 0 ? `${trainingSecurityEvents.length} security events` : "No security events"}
                            </Badge>
                        </CardContent>
                    </Card>
                </div>
            </TabsContent>

            <TabsContent value="observability" className="mt-4 space-y-6">
                {observabilityAuthRequired ? (
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
                ) : (
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
                    <Card className="xl:col-span-1">
                        <CardHeader>
                            <CardTitle>Memory Observability</CardTitle>
                            <CardDescription>Writeback queue, shard linking, and feedback loop state.</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4 text-sm">
                            <div className="flex items-center justify-between">
                                <span className="text-muted-foreground">Memory service</span>
                                <Badge variant={memoryStats?.available ? "secondary" : "outline"}>
                                    {memoryStats?.available ? "Available" : "Unavailable"}
                                </Badge>
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-muted-foreground">Pending writebacks</span>
                                <span className="font-medium">{memoryStats?.pending_writebacks ?? 0}</span>
                            </div>
                            <div className="flex items-center justify-between">
                                <span className="text-muted-foreground">Active shard links</span>
                                <span className="font-medium">{memoryStats?.active_shard_links ?? 0}</span>
                            </div>
                            <div className="rounded-md border bg-muted/40 p-3">
                                <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">Feedback Metrics</p>
                                <pre className="text-xs whitespace-pre-wrap break-words">
{JSON.stringify(memoryStats?.feedback_metrics || {}, null, 2)}
                                </pre>
                            </div>
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
                                                {event.timestamp ? format(new Date(event.timestamp), 'MMM d, HH:mm') : 'Unknown time'}
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
                                                {event.timestamp ? format(new Date(event.timestamp), 'MMM d, HH:mm:ss') : 'Unknown time'}
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
            
            <TabsContent value="logs" className="mt-4">
                 <Card>
                    <CardHeader>
                        <CardTitle>Automation Run History</CardTitle>
                        <CardDescription>A log of all executed tasks and sequences.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <ScrollArea className="h-96">
                            <div className="space-y-4">
                                {recentAuditEvents.length > 0 ? recentAuditEvents.map((event, index) => (
                                    <div key={`${event.timestamp ?? index}-${event.event_type ?? 'event'}`} className="flex items-center space-x-4 p-2 rounded-md border bg-muted/40">
                                        <div className="flex-1 grid grid-cols-4 gap-4 items-center">
                                            <div className="col-span-2">
                                                <p className="font-semibold text-foreground truncate">{event.message || event.event_type || 'Audit event'}</p>
                                                <Badge variant="secondary">Audit</Badge>
                                            </div>
                                            <div className="flex items-center space-x-2">
                                                <Clock className="h-3.5 w-3.5 text-muted-foreground"/>
                                                <span className="text-xs text-muted-foreground">{event.timestamp ? format(new Date(event.timestamp), 'MMM d, HH:mm:ss') : 'Unknown time'}</span>
                                            </div>
                                            <div>
                                                <Badge variant="outline">{event.event_type || 'unknown'}</Badge>
                                            </div>
                                        </div>
                                    </div>
                                )) : (
                                    <Alert variant="default" className="border-yellow-500/30 bg-yellow-500/5">
                                        <AlertCircle className="h-4 w-4 !text-yellow-600" />
                                        <AlertTitle>Automation logs unavailable</AlertTitle>
                                        <AlertDescription>
                                            Live automation run history is unavailable from the backend. No synthetic log data is shown.
                                        </AlertDescription>
                                    </Alert>
                                )}
                            </div>
                        </ScrollArea>
                    </CardContent>
                 </Card>
            </TabsContent>

            <TabsContent value="notes" className="mt-4">
                <Card>
                    <CardHeader>
                        <CardTitle>Generated Notes & Summaries</CardTitle>
                        <CardDescription>A collection of notes and summaries created by Karen from conversations or tasks.</CardDescription>
                    </CardHeader>
                    <CardContent>
                       <ScrollArea className="h-96">
                           <div className="space-y-4">
                                <Alert variant="default" className="border-yellow-500/30 bg-yellow-500/5">
                                    <AlertCircle className="h-4 w-4 !text-yellow-600" />
                                    <AlertTitle>Generated notes unavailable</AlertTitle>
                                    <AlertDescription>
                                        Generated notes are not currently exposed by backend APIs for this view.
                                    </AlertDescription>
                                </Alert>
                            </div>
                        </ScrollArea>
                    </CardContent>
                </Card>
            </TabsContent>

            <TabsContent value="alerts" className="mt-4">
                <Card>
                    <CardHeader>
                        <CardTitle>System Alerts & Notifications</CardTitle>
                        <CardDescription>Important updates and information about the Karen AI system.</CardDescription>
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
                                            <p className="text-xs text-muted-foreground/70 mt-1">{format(alert.timestamp, 'MMM d, HH:mm')}</p>
                                        </div>
                                    </li>
                                )) : (
                                    <Alert variant="default" className="border-yellow-500/30 bg-yellow-500/5">
                                        <AlertCircle className="h-4 w-4 !text-yellow-600" />
                                        <AlertTitle>System alerts unavailable</AlertTitle>
                                        <AlertDescription>
                                            Live system alerts are currently unavailable from the backend.
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
