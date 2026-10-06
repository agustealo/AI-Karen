'use client';

import { Activity, BrainCircuit, Database, GitBranch, ServerCog } from 'lucide-react';

import type { AgentStepEvent } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

import AgentActivityPanel from './AgentActivityPanel';

interface ChatIntelligenceSidecarProps {
  metadata: Record<string, unknown>;
  agentSteps: AgentStepEvent[];
  configuredProvider?: string;
  configuredModel?: string;
  streamingStatus?: string;
  isLoading?: boolean;
  isBackendOffline?: boolean;
}

const text = (value: unknown): string => {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
};

const numberValue = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const booleanValue = (value: unknown): boolean | null => {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === 1 || value === '1') return true;
  if (value === 'false' || value === 0 || value === '0') return false;
  return null;
};

const first = (metadata: Record<string, unknown>, ...keys: string[]): unknown => {
  for (const key of keys) {
    if (metadata[key] !== undefined && metadata[key] !== null) {
      return metadata[key];
    }
  }
  return undefined;
};

const shortId = (value: unknown): string => {
  const resolved = text(value);
  if (!resolved) return '';
  return resolved.length > 18 ? `${resolved.slice(0, 8)}…${resolved.slice(-6)}` : resolved;
};

const Row = ({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) => (
  <div className="flex items-start justify-between gap-3 border-b border-border/50 py-2 last:border-b-0">
    <span className="text-xs text-muted-foreground">{label}</span>
    <span
      className={cn(
        'max-w-[62%] text-right text-xs font-medium text-foreground',
        mono && 'font-mono text-[11px]',
      )}
    >
      {value}
    </span>
  </div>
);

const EmptyState = ({ children }: { children: React.ReactNode }) => (
  <p className="text-xs leading-relaxed text-muted-foreground">{children}</p>
);

export default function ChatIntelligenceSidecar({
  metadata,
  agentSteps,
  configuredProvider,
  configuredModel,
  streamingStatus,
  isLoading = false,
  isBackendOffline = false,
}: ChatIntelligenceSidecarProps) {
  const actualProvider = text(first(metadata, 'actual_provider', 'provider'));
  const actualModel = text(first(metadata, 'actual_model', 'model', 'model_name'));
  const runtimeEngine = text(first(metadata, 'runtime_engine'));
  const responseSource = text(first(metadata, 'response_source'));
  const latencyMs = numberValue(first(metadata, 'latency_ms', 'processing_time_ms'));
  const fallbackLevel = numberValue(first(metadata, 'fallback_level'));
  const degradedMode = booleanValue(first(metadata, 'degraded_mode')) === true;
  const degradationReason = text(
    first(metadata, 'degradation_reason', 'fallback_reason', 'failure_reason'),
  );

  const contextUsed = booleanValue(first(metadata, 'context_used'));
  const memoryRecallCount = numberValue(
    first(metadata, 'memory_recall_count', 'memory_context_count', 'recalled_memory_count'),
  );
  const memoryFormationCount = numberValue(
    first(metadata, 'memory_formation_count', 'memory_persisted_count', 'memory_write_count'),
  );

  const trajectoryId = text(first(metadata, 'trajectory_id'));
  const policyDecisionId = text(first(metadata, 'policy_decision_id'));
  const decisionObservationId = text(first(metadata, 'decision_observation_id'));
  const executionStatus = text(first(metadata, 'execution_status', 'status'));
  const persistenceSuccess = booleanValue(first(metadata, 'persistence_success'));
  const featureSnapshotRefs = first(metadata, 'feature_snapshot_refs');
  const featureSnapshotCount = Array.isArray(featureSnapshotRefs)
    ? featureSnapshotRefs.length
    : numberValue(first(metadata, 'feature_snapshot_count'));

  const toolSteps = agentSteps.filter((step) =>
    String(step.type).startsWith('tool_'),
  ).length;
  const agentExecutionSteps = agentSteps.filter((step) =>
    String(step.type).startsWith('agent_step_'),
  ).length;

  const runtimeAvailable = Boolean(
    actualProvider ||
      actualModel ||
      runtimeEngine ||
      responseSource ||
      latencyMs !== null ||
      configuredProvider ||
      configuredModel,
  );
  const memoryAvailable =
    contextUsed !== null ||
    memoryRecallCount !== null ||
    memoryFormationCount !== null;
  const learningAvailable = Boolean(
    trajectoryId ||
      policyDecisionId ||
      decisionObservationId ||
      executionStatus ||
      persistenceSuccess !== null ||
      featureSnapshotCount !== null,
  );

  const statusLabel = isBackendOffline
    ? 'Offline'
    : degradedMode
      ? 'Degraded'
      : isLoading
        ? 'Working'
        : 'Ready';

  return (
    <aside
      data-testid="chat-intelligence-sidecar"
      className="flex h-full min-h-0 w-full flex-col border-l border-border bg-card/35"
      aria-label="KAREN intelligence and runtime details"
    >
      <div className="border-b border-border bg-background/80 px-4 py-3 backdrop-blur">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <BrainCircuit className="h-4 w-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold">KAREN Intelligence</h2>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Runtime, memory, agents, and learning evidence
            </p>
          </div>
          <Badge
            variant={isBackendOffline || degradedMode ? 'destructive' : 'secondary'}
            className="text-[10px]"
          >
            {statusLabel}
          </Badge>
        </div>
        {streamingStatus ? (
          <p className="mt-2 text-[11px] text-muted-foreground">{streamingStatus}</p>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        <Card className="border-border/70 bg-background/70">
          <CardHeader className="px-3 py-2.5">
            <CardTitle className="flex items-center gap-2 text-xs font-semibold">
              <ServerCog className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              Runtime
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-0">
            {runtimeAvailable ? (
              <>
                <Row label="Configured" value={configuredProvider || 'not reported'} />
                <Row label="Configured model" value={configuredModel || 'not reported'} />
                <Row label="Actual provider" value={actualProvider || 'not reported'} />
                <Row label="Actual model" value={actualModel || 'not reported'} />
                <Row label="Engine" value={runtimeEngine || 'not reported'} />
                <Row label="Source" value={responseSource || 'not reported'} />
                <Row
                  label="Latency"
                  value={latencyMs !== null ? `${Math.round(latencyMs)} ms` : 'not reported'}
                />
                <Row
                  label="Fallback"
                  value={
                    fallbackLevel !== null && fallbackLevel > 0
                      ? `level ${fallbackLevel}`
                      : 'primary path'
                  }
                />
                {degradationReason ? (
                  <div className="mt-2 rounded-md border border-amber-500/20 bg-amber-500/5 p-2 text-[11px] text-amber-700 dark:text-amber-300">
                    {degradationReason}
                  </div>
                ) : null}
              </>
            ) : (
              <EmptyState>No runtime metadata has been reported for this conversation yet.</EmptyState>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-background/70">
          <CardHeader className="px-3 py-2.5">
            <CardTitle className="flex items-center gap-2 text-xs font-semibold">
              <Database className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              Memory & Continuity
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-0">
            {memoryAvailable ? (
              <>
                <Row
                  label="Context used"
                  value={
                    contextUsed === null
                      ? 'not reported'
                      : contextUsed
                        ? 'yes'
                        : 'no'
                  }
                />
                <Row
                  label="Memories recalled"
                  value={memoryRecallCount ?? 'not reported'}
                />
                <Row
                  label="Memories formed"
                  value={memoryFormationCount ?? 'not reported'}
                />
              </>
            ) : (
              <EmptyState>
                This turn has not reported memory recall or formation evidence.
              </EmptyState>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-background/70">
          <CardHeader className="px-3 py-2.5">
            <CardTitle className="flex items-center gap-2 text-xs font-semibold">
              <Activity className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              Agents & Tools
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-0">
            {agentSteps.length > 0 ? (
              <>
                <div className="mb-2 grid grid-cols-2 gap-2">
                  <div className="rounded-md bg-muted/50 p-2">
                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Agent events
                    </div>
                    <div className="mt-1 text-sm font-semibold">{agentExecutionSteps}</div>
                  </div>
                  <div className="rounded-md bg-muted/50 p-2">
                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Tool events
                    </div>
                    <div className="mt-1 text-sm font-semibold">{toolSteps}</div>
                  </div>
                </div>
                <AgentActivityPanel steps={agentSteps} />
              </>
            ) : (
              <EmptyState>No agent or tool activity has been reported for this turn.</EmptyState>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-background/70">
          <CardHeader className="px-3 py-2.5">
            <CardTitle className="flex items-center gap-2 text-xs font-semibold">
              <GitBranch className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
              Learning & Outcome
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-0">
            {learningAvailable ? (
              <>
                <Row label="Execution" value={executionStatus || 'not reported'} />
                <Row
                  label="Trajectory"
                  value={shortId(trajectoryId) || 'not reported'}
                  mono
                />
                <Row
                  label="Policy decision"
                  value={shortId(policyDecisionId) || 'not reported'}
                  mono
                />
                <Row
                  label="Decision observation"
                  value={shortId(decisionObservationId) || 'not reported'}
                  mono
                />
                <Row
                  label="Feature snapshots"
                  value={featureSnapshotCount ?? 'not reported'}
                />
                <Row
                  label="Persistence"
                  value={
                    persistenceSuccess === null
                      ? 'not reported'
                      : persistenceSuccess
                        ? 'stored'
                        : 'failed'
                  }
                />
              </>
            ) : (
              <EmptyState>
                Learning lineage or outcome evidence has not been reported on this turn.
              </EmptyState>
            )}
          </CardContent>
        </Card>
      </div>
    </aside>
  );
}
