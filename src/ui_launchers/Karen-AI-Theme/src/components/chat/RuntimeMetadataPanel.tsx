import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AlertCircle, CheckCircle2, ChevronRight, Info } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ProviderAttempt {
  provider: string;
  model: string;
  status: string;
  error_type?: string;
  error_message?: string;
  latency_ms?: number;
}

interface RuntimeMetadataPanelProps {
  requestedProvider?: string;
  actualProvider?: string;
  requestedModel?: string;
  actualModel?: string;
  runtimeEngine?: string;
  fallbackLevel?: string | number;
  correlationId?: string;
  requestId?: string;
  status?: string;
  responseSource?: string;
  degradedMode?: boolean;
  degradationType?: string;
  degradationReason?: string;
  providerAttempts?: ProviderAttempt[];
  latencyMs?: number;
}

const safe = (value?: unknown) => (value !== undefined && value !== null && String(value).trim() ? String(value) : 'n/a');

export default function RuntimeMetadataPanel(props: RuntimeMetadataPanelProps) {
  const isFallback = Number(props.fallbackLevel) > 0 && props.degradedMode !== false;
  const isDegraded = props.degradedMode === true;

  let statusLabel = 'ok';
  let StatusIcon = CheckCircle2;
  let statusColor = 'text-emerald-500';

  if (isDegraded) {
    statusLabel = props.degradationType || 'degraded';
    StatusIcon = AlertCircle;
    statusColor = 'text-amber-500';
  }

  return (
    <Card className="mx-4 mb-3 border-primary/20 bg-card/70 backdrop-blur-sm overflow-hidden">
      <CardHeader className="pb-2 border-b border-primary/10 bg-primary/5">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-bold uppercase tracking-wider flex items-center gap-2">
            <Info className="h-3.5 w-3.5 text-primary" />
            Forensic Execution Truth
          </CardTitle>
          <div className={cn("flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest", statusColor)}>
            <StatusIcon className="h-3 w-3" />
            {statusLabel}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="grid gap-px bg-primary/10 text-[10px] sm:grid-cols-2 lg:grid-cols-4">
          <div className="bg-card p-3 flex flex-col gap-1">
            <span className="text-muted-foreground uppercase font-semibold text-[9px]">Requested Provider</span>
            <strong className="truncate">{safe(props.requestedProvider)}</strong>
          </div>
          <div className="bg-card p-3 flex flex-col gap-1">
            <span className="text-muted-foreground uppercase font-semibold text-[9px]">Actual Provider</span>
            <strong className={cn("truncate", !props.actualProvider && "italic text-muted-foreground")}>
              {props.actualProvider || 'none'}
            </strong>
          </div>
          <div className="bg-card p-3 flex flex-col gap-1">
            <span className="text-muted-foreground uppercase font-semibold text-[9px]">Requested Model</span>
            <strong className="truncate">{safe(props.requestedModel)}</strong>
          </div>
          <div className="bg-card p-3 flex flex-col gap-1">
            <span className="text-muted-foreground uppercase font-semibold text-[9px]">Actual Model</span>
            <strong className={cn("truncate", !props.actualModel && "italic text-muted-foreground")}>
              {props.actualModel || 'none'}
            </strong>
          </div>

          <div className="bg-card p-3 flex flex-col gap-1">
            <span className="text-muted-foreground uppercase font-semibold text-[9px]">Runtime Engine</span>
            <strong>{safe(props.runtimeEngine)}</strong>
          </div>
          <div className="bg-card p-3 flex flex-col gap-1">
            <span className="text-muted-foreground uppercase font-semibold text-[9px]">Fallback Level</span>
            <strong className={cn(isDegraded && "text-amber-500")}>{safe(props.fallbackLevel)}</strong>
          </div>
          <div className="bg-card p-3 flex flex-col gap-1">
            <span className="text-muted-foreground uppercase font-semibold text-[9px]">Latency</span>
            <strong>{props.latencyMs ? `${(props.latencyMs / 1000).toFixed(2)}s` : 'n/a'}</strong>
          </div>
          <div className="bg-card p-3 flex flex-col gap-1">
            <span className="text-muted-foreground uppercase font-semibold text-[9px]">Correlation ID</span>
            <code className="truncate text-[9px] opacity-70">{safe(props.correlationId)}</code>
          </div>
        </div>

        {isDegraded && props.providerAttempts && props.providerAttempts.length > 0 && (
          <div className="p-3 border-t border-primary/10 bg-destructive/5">
            <div className="mb-2 text-[9px] font-bold uppercase tracking-wider text-destructive/80">Provider Attempt Chain</div>
            <div className="space-y-1.5">
              {props.providerAttempts.map((attempt, idx) => (
                <div key={idx} className="flex items-start gap-2 text-[10px]">
                  <ChevronRight className="h-3 w-3 mt-0.5 shrink-0 opacity-50" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-bold">{attempt.provider}</span>
                      <span className="opacity-60">({attempt.model})</span>
                      <Badge variant="outline" className={cn(
                        "h-4 text-[8px] font-bold uppercase px-1 py-0",
                        attempt.status === 'success' ? "text-emerald-500 border-emerald-500/20" : "text-destructive border-destructive/20"
                      )}>
                        {attempt.status}
                      </Badge>
                    </div>
                    {attempt.error_type && (
                      <div className="text-destructive/70 text-[9px] truncate mt-0.5 font-medium">
                        {attempt.error_type}: {attempt.error_message}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {(isDegraded || isFallback) && props.degradationReason && (
          <div className="p-3 border-t border-primary/10 bg-amber-500/5">
             <div className="text-[9px] font-bold uppercase tracking-wider text-amber-600/80 mb-1">Reason</div>
             <div className="text-[10px] leading-relaxed italic">{props.degradationReason}</div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
