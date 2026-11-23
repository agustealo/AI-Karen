import React from 'react';
import { CheckCircle, XCircle, AlertTriangle, Clock, Globe, Database, Zap, Settings } from 'lucide-react';
import { IntelligentSearchResponse } from '../types';

interface CrawlDiagnosticsPanelProps {
  response: IntelligentSearchResponse;
}

interface CrawlDiagnostics {
  enabled: boolean;
  engine: string;
  status: string;
  pages_requested: number;
  pages_succeeded: number;
  pages_failed: number;
  latency_ms: number;
  capabilities: Record<string, boolean>;
  degraded: boolean;
  degradation_reason?: string;
}

export function CrawlDiagnosticsPanel({ response }: CrawlDiagnosticsPanelProps) {
  const crawl = response.crawl as CrawlDiagnostics | undefined;

  if (!crawl || !crawl.enabled) {
    return null;
  }

  const getStatusIcon = () => {
    if (crawl.degraded) {
      return <AlertTriangle className="h-4 w-4 text-amber-500" />;
    }
    if (crawl.pages_failed > 0) {
      return <XCircle className="h-4 w-4 text-orange-500" />;
    }
    return <CheckCircle className="h-4 w-4 text-green-500" />;
  };

  const getStatusText = () => {
    if (crawl.degraded) {
      return crawl.degradation_reason || 'Degraded';
    }
    if (crawl.pages_failed > 0) {
      return 'Partial Success';
    }
    return 'Success';
  };

  const getStatusColor = () => {
    if (crawl.degraded) {
      return 'text-amber-500 bg-amber-500/10 border-amber-500/20';
    }
    if (crawl.pages_failed > 0) {
      return 'text-orange-500 bg-orange-500/10 border-orange-500/20';
    }
    return 'text-green-500 bg-green-500/10 border-green-500/20';
  };

  const successRate = crawl.pages_requested > 0
    ? Math.round((crawl.pages_succeeded / crawl.pages_requested) * 100)
    : 0;

  return (
    <div
      data-testid="intelligent-search-crawl-diagnostics"
      className="space-y-3 rounded-lg border border-border/60 bg-card/60 p-4"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe className="h-5 w-5 text-primary" />
          <h3 className="font-semibold text-foreground">Crawl Diagnostics</h3>
        </div>
        <div className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border ${getStatusColor()}`}>
          {getStatusIcon()}
          {getStatusText()}
        </div>
      </div>

      {/* Engine Info */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Database className="h-3.5 w-3.5" />
        <span>Engine: {crawl.engine}</span>
        <span className="text-border">|</span>
        <span>Latency: {crawl.latency_ms}ms</span>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3 pt-2">
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Pages Requested</span>
            <span className="font-medium text-foreground">{crawl.pages_requested}</span>
          </div>
          <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
            <div
              className="bg-primary h-full transition-all"
              style={{ width: '100%' }}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Pages Succeeded</span>
            <span className="font-medium text-green-600 dark:text-green-400">
              {crawl.pages_succeeded}
            </span>
          </div>
          <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
            <div
              className="bg-green-500 h-full transition-all"
              style={{ width: `${successRate}%` }}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Pages Failed</span>
            <span className={`font-medium ${crawl.pages_failed > 0 ? 'text-red-600 dark:text-red-400' : 'text-foreground'}`}>
              {crawl.pages_failed}
            </span>
          </div>
          <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full transition-all ${crawl.pages_failed > 0 ? 'bg-red-500' : 'bg-green-500'}`}
              style={{ width: `${crawl.pages_failed > 0 ? ((crawl.pages_failed / crawl.pages_requested) * 100) : 0}%` }}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Success Rate</span>
            <span className={`font-medium ${successRate >= 80 ? 'text-green-600 dark:text-green-400' : successRate >= 50 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'}`}>
              {successRate}%
            </span>
          </div>
          <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full transition-all ${successRate >= 80 ? 'bg-green-500' : successRate >= 50 ? 'bg-amber-500' : 'bg-red-500'}`}
              style={{ width: `${successRate}%` }}
            />
          </div>
        </div>
      </div>

      {/* Capabilities */}
      {Object.keys(crawl.capabilities).length > 0 && (
        <div className="pt-2 border-t border-border/60">
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-2">
            <Zap className="h-3.5 w-3.5" />
            <span>Capabilities Used</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(crawl.capabilities).map(([capability, enabled]) => (
              <span
                key={capability}
                className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium ${
                  enabled
                    ? 'bg-primary/10 text-primary border border-primary/20'
                    : 'bg-muted text-muted-foreground border border-border'
                }`}
              >
                {enabled ? <CheckCircle className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                {capability.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Degradation Reason */}
      {crawl.degraded && crawl.degradation_reason && (
        <div className="pt-2 border-t border-border/60">
          <div className="flex items-start gap-2 text-xs">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-500 mt-0.5 flex-shrink-0" />
            <div className="space-y-1">
              <p className="font-medium text-amber-600 dark:text-amber-400">
                Crawl Degraded
              </p>
              <p className="text-muted-foreground">
                {crawl.degradation_reason}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-2 pt-2 border-t border-border/60">
        <div className="text-center">
          <div className="text-lg font-semibold text-foreground">{crawl.pages_requested}</div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Requested</div>
        </div>
        <div className="text-center">
          <div className="text-lg font-semibold text-green-600 dark:text-green-400">{crawl.pages_succeeded}</div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Succeeded</div>
        </div>
        <div className="text-center">
          <div className={`text-lg font-semibold ${crawl.pages_failed > 0 ? 'text-red-600 dark:text-red-400' : 'text-foreground'}`}>
            {crawl.pages_failed}
          </div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Failed</div>
        </div>
      </div>
    </div>
  );
}
