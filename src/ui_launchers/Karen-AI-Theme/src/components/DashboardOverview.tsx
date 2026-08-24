"use client";

import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  AlertCircle,
  Bot,
  CheckCircle2,
  Database,
  Info,
  Puzzle,
  RefreshCw,
  Server,
  Zap,
  Loader2,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { apiClient } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { NormalizedRuntimeInventory } from '@/lib/model-runtime-inventory';

interface SystemHealthSummary {
  status: string;
  expression_engine: {
    active: string;
    healthy: boolean;
    fallback_level: number;
    degraded: boolean;
  };
  providers: {
    total: number;
    healthy: number;
    configured: number;
  };
  memory: {
    status: string;
    usage_percent: number;
  };
  database: {
    status: string;
    total_operations: number;
  };
  plugins: {
    active: number;
    failed: number;
  };
}

interface RuntimeStatusResponse {
  status?: string;
  expression_engine?: {
    active?: string;
    healthy?: boolean;
    fallback_level?: number;
    degraded?: boolean;
  };
  memory?: {
    status?: string;
    usage_percent?: number;
  };
  plugins?: {
    active?: number;
    failed?: number;
  };
}

interface DatabaseOverviewResponse {
  status?: string;
  total_operations?: number;
}

interface PluginManagementResponse {
  plugins?: unknown[];
}

const fallbackHierarchy = (inventory: NormalizedRuntimeInventory | null): string[] => {
  if (inventory?.fallback_hierarchy && inventory.fallback_hierarchy.length > 0) {
    return inventory.fallback_hierarchy;
  }

  return [];
};

export default function DashboardOverview() {
  const [health, setHealth] = useState<SystemHealthSummary | null>(null);
  const [modelSettings, setModelSettings] = useState<NormalizedRuntimeInventory | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const [settingsRes, runtimeRes, dbRes, pluginsRes] = await Promise.all([
        apiClient.get<NormalizedRuntimeInventory>('/api/settings/model'),
        apiClient.get<RuntimeStatusResponse>('/api/system/status').catch(() => ({} as RuntimeStatusResponse)),
        apiClient.get<DatabaseOverviewResponse>('/api/system/database/health').catch(() => ({} as DatabaseOverviewResponse)),
        apiClient.get<PluginManagementResponse>('/api/plugins/management/').catch(() => ({ plugins: [] })),
      ]);

      setModelSettings(settingsRes);

      const providers = settingsRes.providers || [];
      const configuredProviders = providers.filter((provider) => provider.is_configured);
      const healthyProviders = configuredProviders.filter((provider) => provider.healthy);

      setHealth({
        status: runtimeRes.status || 'ok',
        expression_engine: {
          active: runtimeRes.expression_engine?.active || settingsRes.selected_provider || 'unknown',
          healthy: runtimeRes.expression_engine?.healthy ?? true,
          fallback_level: runtimeRes.expression_engine?.fallback_level ?? 0,
          degraded: runtimeRes.expression_engine?.degraded ?? false,
        },
        providers: {
          total: providers.length,
          healthy: healthyProviders.length,
          configured: configuredProviders.length,
        },
        memory: {
          status: runtimeRes.memory?.status || 'unknown',
          usage_percent: runtimeRes.memory?.usage_percent ?? 0,
        },
        database: {
          status: dbRes.status || 'unknown',
          total_operations: dbRes.total_operations || 0,
        },
        plugins: {
          active: runtimeRes.plugins?.active ?? (pluginsRes.plugins?.length || 0),
          failed: runtimeRes.plugins?.failed ?? 0,
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard overview');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
    const interval = setInterval(() => void loadData(), 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  if (isLoading && !health) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="border-destructive/20 bg-destructive/5">
        <CardContent className="pt-6">
          <div className="flex items-center gap-3 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <p className="font-semibold">{error}</p>
          </div>
          <Button variant="outline" size="sm" className="mt-4" onClick={() => void loadData()}>
            Retry Connection
          </Button>
        </CardContent>
      </Card>
    );
  }

  const fallbackPath = fallbackHierarchy(modelSettings);

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Dashboard Overview</h2>
          <p className="text-muted-foreground italic">
            Real-time status of Karen&apos;s cognitive and runtime infrastructure.
          </p>
        </div>
        <Button variant="ghost" size="sm" className="gap-2" onClick={() => void loadData()}>
          <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="bg-gradient-to-br from-background to-primary/5">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-bold uppercase tracking-widest text-muted-foreground">
              Logic Engine
            </CardTitle>
            <Zap className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold truncate uppercase">
              {health?.expression_engine.active}
            </div>
            <div className="mt-1 flex items-center gap-2">
              <Badge
                variant={health?.expression_engine.healthy ? 'default' : 'destructive'}
                className="h-4 text-[8px]"
              >
                {health?.expression_engine.healthy ? 'HEALTHY' : 'UNHEALTHY'}
              </Badge>
              {health?.expression_engine.degraded && (
                <Badge variant="outline" className="h-4 border-amber-500 bg-amber-50 text-[8px] text-amber-600">
                  DEGRADED
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-bold uppercase tracking-widest text-muted-foreground">
              Providers
            </CardTitle>
            <Server className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {health?.providers.healthy} / {health?.providers.configured}
            </div>
            <p className="mt-1 text-[10px] font-semibold uppercase text-muted-foreground">
              {health?.providers.total} Total Registered
            </p>
            <Progress
              value={
                ((health?.providers.healthy || 0) / (health?.providers.configured || 1)) * 100
              }
              className="mt-2 h-1"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-bold uppercase tracking-widest text-muted-foreground">
              Cognitive Memory
            </CardTitle>
            <Bot className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold uppercase">{health?.memory.status}</div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[10px] uppercase text-muted-foreground">Usage</span>
              <span className="font-mono text-[10px]">{health?.memory.usage_percent}%</span>
            </div>
            <Progress value={health?.memory.usage_percent} className="mt-2 h-1" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-bold uppercase tracking-widest text-muted-foreground">
              Storage Tiers
            </CardTitle>
            <Database className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold uppercase">{health?.database.status}</div>
            <p className="mt-1 text-[10px] font-semibold uppercase text-muted-foreground">
              {health?.database.total_operations.toLocaleString()} Ops handled
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-7">
        <Card className="md:col-span-4">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Bot className="h-5 w-5 text-primary" /> Active Runtime Truth
            </CardTitle>
            <CardDescription>
              Primary model and fallback hierarchy currently being used for chat.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-xl border bg-muted/10 p-4">
                <p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                  Active Provider
                </p>
                <p className="text-lg font-bold uppercase">{modelSettings?.selected_provider}</p>
              </div>
              <div className="rounded-xl border bg-muted/10 p-4">
                <p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                  Active Model
                </p>
                <p className="truncate text-lg font-bold" title={modelSettings?.selected_model}>
                  {modelSettings?.selected_model}
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <p className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                <Activity className="h-3 w-3" /> Fallback Hierarchy
              </p>
              <div className="flex flex-wrap gap-2">
                {fallbackPath.length > 0 ? (
                  fallbackPath.map((provider, index) => (
                    <div key={provider} className="flex items-center gap-2">
                      <Badge variant={index === 0 ? 'default' : 'outline'} className="h-6 font-mono text-[10px]">
                        {provider}
                      </Badge>
                      {index < fallbackPath.length - 1 && (
                        <span className="text-muted-foreground">→</span>
                      )}
                    </div>
                  ))
                ) : (
                  <span className="text-xs text-muted-foreground">Default system policy active</span>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 pt-2">
              <div className="space-y-2">
                <p className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                  <CheckCircle2 className="h-3 w-3 text-green-500" /> Configured
                </p>
                <div className="flex flex-wrap gap-1">
                  {modelSettings?.providers?.filter((provider) => provider.is_configured).map((provider) => (
                    <Badge key={provider.id} variant="secondary" className="h-4 text-[8px] uppercase">
                      {provider.display_name}
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <p className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                  <AlertCircle className="h-3 w-3 text-muted-foreground" /> Needs Setup
                </p>
                <div className="flex flex-wrap gap-1">
                  {modelSettings?.providers?.filter((provider) => !provider.is_configured).map((provider) => (
                    <Badge key={provider.id} variant="outline" className="h-4 text-[8px] uppercase opacity-60">
                      {provider.display_name}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="md:col-span-3">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Puzzle className="h-5 w-5 text-primary" /> Extension Ecosystem
            </CardTitle>
            <CardDescription>Status of loaded plugins and automated tools.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex items-center justify-between">
              <div className="space-y-1">
                <p className="text-sm font-bold">Active Plugins</p>
                <p className="text-[10px] text-muted-foreground">Extensions successfully loaded</p>
              </div>
              <div className="text-2xl font-bold">{health?.plugins.active}</div>
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-1">
                <p className="text-sm font-bold">Failed Loads</p>
                <p className="text-[10px] text-muted-foreground">Plugins requiring attention</p>
              </div>
              <div className="text-2xl font-bold text-destructive">{health?.plugins.failed}</div>
            </div>

            <div className="flex items-start gap-3 rounded-lg bg-primary/5 p-3">
              <Info className="mt-0.5 h-4 w-4 text-primary" />
              <p className="text-[10px] leading-relaxed italic">
                Tools are automatically discovered from the `src/ai_karen_engine/tools` registry and mapped to active
                agent capabilities.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
