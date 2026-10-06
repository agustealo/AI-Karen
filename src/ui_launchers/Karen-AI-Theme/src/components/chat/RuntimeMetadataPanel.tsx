'use client';

import { useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Cpu,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
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

const safe = (value?: unknown) =>
  value !== undefined && value !== null && String(value).trim()
    ? String(value)
    : 'n/a';

const Detail = ({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) => (
  <div className="min-w-0 rounded-lg border border-border/60 bg-background/30 p-2.5">
    <p className="karen-panel-label text-[8px]">{label}</p>
    <p
      className={cn(
        'mt-1 truncate text-[11px] font-semibold text-foreground/90',
        mono && 'font-mono font-medium',
      )}
      title={value}
    >
      {value}
    </p>
  </div>
);

export default function RuntimeMetadataPanel(props: RuntimeMetadataPanelProps) {
  const [expanded, setExpanded] = useState(false);

  const isFallback =
    Number(props.fallbackLevel) > 0 && props.degradedMode !== false;
  const isDegraded = props.degradedMode === true;
  const hasRuntimeTruth = Boolean(
    props.requestedProvider ||
      props.actualProvider ||
      props.requestedModel ||
      props.actualModel ||
      props.runtimeEngine ||
      props.responseSource ||
      props.correlationId,
  );

  if (!hasRuntimeTruth) {
    return null;
  }

  const statusLabel = isDegraded
    ? props.degradationType || 'degraded'
    : isFallback
      ? 'fallback'
      : 'primary';
  const StatusIcon = isDegraded ? AlertCircle : CheckCircle2;

  return (
    <section
      className="mx-3 mt-3 overflow-hidden rounded-xl border border-border/70 bg-card/60 shadow-sm backdrop-blur-md md:mx-4"
      aria-label="Execution truth"
      data-testid="runtime-metadata-panel"
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/50"
        aria-expanded={expanded}
        aria-controls="runtime-execution-details"
      >
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-primary/20 bg-primary/10">
          <Cpu className="h-3.5 w-3.5 text-primary" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="karen-panel-label text-foreground/90">
              Execution truth
            </span>
            <Badge
              variant="outline"
              className={cn(
                'h-5 px-1.5 text-[8px]',
                isDegraded
                  ? 'border-amber-500/30 text-amber-500'
                  : 'border-emerald-500/25 text-emerald-500',
              )}
            >
              <StatusIcon className="mr-1 h-2.5 w-2.5" />
              {statusLabel}
            </Badge>
          </div>

          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] text-muted-foreground">
            <span className="truncate">
              {safe(props.actualProvider || props.requestedProvider)}
            </span>
            <span className="text-border">/</span>
            <span className="truncate">
              {safe(props.actualModel || props.requestedModel)}
            </span>
            {props.responseSource && (
              <>
                <span className="text-border">•</span>
                <span>{props.responseSource}</span>
              </>
            )}
            {props.latencyMs ? (
              <>
                <span className="text-border">•</span>
                <span>{Math.round(props.latencyMs)} ms</span>
              </>
            ) : null}
          </div>
        </div>

        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div
          id="runtime-execution-details"
          className="border-t border-border/60 bg-background/20 p-3"
        >
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <Detail
              label="Requested provider"
              value={safe(props.requestedProvider)}
            />
            <Detail
              label="Actual provider"
              value={safe(props.actualProvider || 'none')}
            />
            <Detail label="Requested model" value={safe(props.requestedModel)} />
            <Detail
              label="Actual model"
              value={safe(props.actualModel || 'none')}
            />
            <Detail label="Runtime engine" value={safe(props.runtimeEngine)} />
            <Detail
              label="Fallback level"
              value={safe(props.fallbackLevel ?? 0)}
            />
            <Detail
              label="Response source"
              value={safe(props.responseSource)}
            />
            <Detail
              label="Correlation"
              value={safe(props.correlationId)}
              mono
            />
          </div>

          {props.providerAttempts && props.providerAttempts.length > 0 && (
            <div className="mt-3 rounded-lg border border-border/60 bg-background/30 p-3">
              <p className="karen-panel-label">Provider attempts</p>
              <div className="mt-2 space-y-1.5">
                {props.providerAttempts.map((attempt, index) => (
                  <div
                    key={`${attempt.provider}-${attempt.model}-${index}`}
                    className="flex items-start gap-2 text-[10px]"
                  >
                    <ChevronRight className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-semibold">
                          {attempt.provider}
                        </span>
                        <span className="truncate text-muted-foreground">
                          {attempt.model || 'auto'}
                        </span>
                        <span
                          className={
                            attempt.status === 'success'
                              ? 'ml-auto font-mono text-emerald-500'
                              : 'ml-auto font-mono text-destructive'
                          }
                        >
                          {attempt.status}
                        </span>
                      </div>
                      {attempt.error_type && (
                        <p className="mt-0.5 truncate text-[9px] text-destructive/80">
                          {attempt.error_type}
                          {attempt.error_message
                            ? `: ${attempt.error_message}`
                            : ''}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(isDegraded || isFallback) && props.degradationReason && (
            <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
              <p className="karen-panel-label text-amber-500">Reason</p>
              <p className="mt-1 text-[11px] leading-5 text-foreground/80">
                {props.degradationReason}
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
