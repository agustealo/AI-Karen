'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ChartNoAxesColumnIncreasing,
  Bot,
  Brain,
  Cpu,
  Database,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Gauge,
  GitBranch,
  Network,
  MemoryStick,
  PlugZap,
  Route,
  Scale,
  ShieldAlert,
  Sparkles,
  TimerReset,
  UsersRound,
  Wrench,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AgentStepEvent } from '@/lib/types';
import { apiClient } from '@/lib/api';

type JsonRecord = Record<string, unknown>;

interface ApprovalAttentionItem {
  approval_id: string;
  intent: string;
  risk_level: string;
  status: string;
  expires_at: string;
}

interface ConversationContextRailProps {
  metadata?: JsonRecord;
  agentSteps: AgentStepEvent[];
  approvals?: ApprovalAttentionItem[];
  approvalsLoadState?: 'idle' | 'loading' | 'ready' | 'unavailable';
  systemResources?: PlatformResourceSnapshot | null;
  resourcesLoadState?: 'idle' | 'loading' | 'ready' | 'unavailable';
}

interface ContinuityCandidate {
  id: string;
  subject: string;
  sourceType?: string;
  urgency?: string;
  confidence?: number;
  utility?: number;
  primary: boolean;
}

interface CapabilityReceipt {
  executionTopology?: string;
  reasoningModes: string[];
  executionBudget?: {
    maxDurationMs?: number;
    maxModelCalls?: number;
    maxToolCalls?: number;
    maxReasoningSteps?: number;
    maxOutputTokens?: number;
  };
  allowedCapabilities: string[];
  forbiddenCapabilities: string[];
  allowedTools: string[];
  allowedPlugins: string[];
  allowedAgents: string[];
  requiresHumanGate: boolean;
  requiresResumability: boolean;
  workflowId?: string;
  workflowVersion?: string;
  policyDecisionId?: string;
  policyReasonCodes: string[];
}

interface ExecutionUsage {
  tools: string[];
  plugins: string[];
  providers: string[];
}

interface PlatformResourceMetric {
  available: boolean;
  usage_percent?: number | null;
  used_bytes?: number | null;
  available_bytes?: number | null;
  total_bytes?: number | null;
}

interface PlatformResourceSnapshot {
  timestamp: number;
  cpu: PlatformResourceMetric;
  memory: PlatformResourceMetric;
  gpu: PlatformResourceMetric;
  vram: PlatformResourceMetric;
  disk: PlatformResourceMetric;
}

interface ProviderAttemptInsight {
  provider?: string;
  model?: string;
  status?: string;
  latencyMs?: number;
  errorType?: string;
}

interface RuntimeInsight {
  requestedProvider?: string;
  requestedModel?: string;
  actualProvider?: string;
  actualModel?: string;
  runtimeEngine?: string;
  locality?: string;
  responseSource?: string;
  mode?: string;
  latencyMs?: number;
  fallbackLevel: number;
  usedFallback: boolean;
  degradedMode: boolean;
  degradationReason?: string;
  providerAttempts: ProviderAttemptInsight[];
  transcriptPersistenceStatus?: string;
  memoryPersistenceStatus?: string;
  correlationId?: string;
  requestId?: string;
  trajectoryId?: string;
}

interface RecallInsight {
  id: string;
  content: string;
  relevance?: number;
  confidence?: number;
}

interface TurnIntelligence {
  intent?: string;
  intentConfidence?: number;
  recallStatus?: string;
  recallCount: number;
  recalled: RecallInsight[];
  memoryFormationStatus?: string;
  memoryCandidateCount: number;
  memoryAdmittedCount: number;
  memoryPersistedCount: number;
}

const asRecord = (value: unknown): JsonRecord =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};

const asString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const asStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => asString(item))
    .filter(Boolean);
};

const asNumber = (value: unknown): number | undefined => {
  return typeof value === 'number' && Number.isFinite(value)
    ? value
    : undefined;
};

const unique = (values: string[]): string[] => {
  return Array.from(new Set(values.filter(Boolean)));
};

const normalizeCapabilityReceipt = (metadata: JsonRecord): CapabilityReceipt => {
  const receipt = asRecord(metadata.capability_receipt);

  const budget = asRecord(receipt.execution_budget);
  return {
    executionTopology: asString(receipt.execution_topology) || undefined,
    reasoningModes: asStringArray(receipt.reasoning_modes),
    executionBudget: Object.keys(budget).length
      ? {
          maxDurationMs: asNumber(budget.max_duration_ms),
          maxModelCalls: asNumber(budget.max_model_calls),
          maxToolCalls: asNumber(budget.max_tool_calls),
          maxReasoningSteps: asNumber(budget.max_reasoning_steps),
          maxOutputTokens: asNumber(budget.max_output_tokens),
        }
      : undefined,
    allowedCapabilities: asStringArray(receipt.allowed_capabilities),
    forbiddenCapabilities: asStringArray(receipt.forbidden_capabilities),
    allowedTools: asStringArray(receipt.allowed_tools),
    allowedPlugins: asStringArray(receipt.allowed_plugins),
    allowedAgents: asStringArray(receipt.allowed_agents),
    requiresHumanGate: receipt.requires_human_gate === true,
    requiresResumability: receipt.requires_resumability === true,
    workflowId: asString(receipt.workflow_id) || undefined,
    workflowVersion: asString(receipt.workflow_version) || undefined,
    policyDecisionId: asString(receipt.policy_decision_id) || undefined,
    policyReasonCodes: asStringArray(receipt.policy_reason_codes),
  };
};

const normalizeContinuity = (metadata: JsonRecord): {
  candidates: ContinuityCandidate[];
  ambiguous: boolean;
} => {
  const continuity = asRecord(metadata.proactive_continuity);
  const primaryId = asString(metadata.continuity_primary_candidate_id);
  const ambiguous = metadata.continuity_ambiguous === true;
  const rawCandidates = Array.isArray(continuity.candidates)
    ? continuity.candidates
    : [];

  const candidates = rawCandidates
    .map((raw): ContinuityCandidate | null => {
      const item = asRecord(raw);
      const id = asString(item.id);
      const subject = asString(item.subject);

      if (!id || !subject) {
        return null;
      }

      return {
        id,
        subject,
        sourceType: asString(item.source_type) || undefined,
        urgency: asString(item.urgency) || undefined,
        confidence: asNumber(item.confidence),
        utility: asNumber(item.utility),
        primary: Boolean(primaryId && id === primaryId && !ambiguous),
      };
    })
    .filter((item): item is ContinuityCandidate => item !== null);

  return { candidates, ambiguous };
};

const normalizeExecutionUsage = (
  steps: AgentStepEvent[],
  responseMetadata: JsonRecord,
): ExecutionUsage => {
  const tools: string[] = [];
  const plugins: string[] = [];
  const providers: string[] = [];

  for (const step of steps) {
    const metadata = asRecord(step.metadata);
    const tool = asString(metadata.tool);
    const extension = asString(metadata.extension_id);
    const plugin = asString(metadata.plugin_id);
    const provider =
      asString(metadata.actual_provider) ||
      asString(metadata.provider) ||
      asString(metadata.requested_provider);

    if (tool) tools.push(tool);
    if (extension) plugins.push(extension);
    if (plugin) plugins.push(plugin);
    if (provider) providers.push(provider);
  }

  const actualProvider = asString(responseMetadata.actual_provider);
  const actualModel = asString(responseMetadata.actual_model);
  if (actualProvider) {
    providers.push(actualModel ? `${actualProvider} · ${actualModel}` : actualProvider);
  }

  return {
    tools: unique(tools),
    plugins: unique(plugins),
    providers: unique(providers),
  };
};

const normalizeRuntimeInsight = (metadata: JsonRecord): RuntimeInsight => {
  const attempts = Array.isArray(metadata.provider_attempts)
    ? metadata.provider_attempts
        .map((raw): ProviderAttemptInsight | null => {
          const attempt = asRecord(raw);
          const provider = asString(attempt.provider) || undefined;
          const model = asString(attempt.model) || undefined;
          const status = asString(attempt.status) || undefined;
          const latencyMs = asNumber(attempt.latency_ms);
          const errorType = asString(attempt.error_type) || undefined;
          if (!provider && !model && !status && latencyMs === undefined && !errorType) {
            return null;
          }
          return { provider, model, status, latencyMs, errorType };
        })
        .filter((item): item is ProviderAttemptInsight => item !== null)
    : [];

  return {
    requestedProvider: asString(metadata.requested_provider) || undefined,
    requestedModel: asString(metadata.requested_model) || undefined,
    actualProvider: asString(metadata.actual_provider) || undefined,
    actualModel: asString(metadata.actual_model) || undefined,
    runtimeEngine: asString(metadata.runtime_engine) || undefined,
    locality: asString(metadata.locality) || undefined,
    responseSource: asString(metadata.response_source) || undefined,
    mode: asString(metadata.mode) || undefined,
    latencyMs: asNumber(metadata.latency_ms),
    fallbackLevel: asNumber(metadata.fallback_level) ?? 0,
    usedFallback:
      metadata.used_fallback === true || (asNumber(metadata.fallback_level) ?? 0) > 0,
    degradedMode: metadata.degraded_mode === true,
    degradationReason: asString(metadata.degradation_reason) || undefined,
    providerAttempts: attempts,
    transcriptPersistenceStatus:
      asString(metadata.transcript_persistence_status) || undefined,
    memoryPersistenceStatus:
      asString(metadata.memory_persistence_status) || undefined,
    correlationId: asString(metadata.correlation_id) || undefined,
    requestId: asString(metadata.request_id) || undefined,
    trajectoryId: asString(metadata.trajectory_id) || undefined,
  };
};

const normalizeTurnIntelligence = (metadata: JsonRecord): TurnIntelligence => {
  const memoryContext = asRecord(metadata.memory_context);
  const rawRecall = Array.isArray(memoryContext.recall) ? memoryContext.recall : [];
  const recalled = rawRecall
    .map((raw): RecallInsight | null => {
      const item = asRecord(raw);
      const id = asString(item.id);
      const content = asString(item.content);
      if (!content) return null;
      return {
        id: id || content.slice(0, 48),
        content,
        relevance: asNumber(item.relevance),
        confidence: asNumber(item.confidence),
      };
    })
    .filter((item): item is RecallInsight => item !== null);

  return {
    intent: asString(metadata.intent) || undefined,
    intentConfidence: asNumber(metadata.intent_confidence),
    recallStatus: asString(metadata.memory_recall_status) || undefined,
    recallCount: asNumber(metadata.memory_recall_count) ?? recalled.length,
    recalled,
    memoryFormationStatus: asString(metadata.memory_formation_status) || undefined,
    memoryCandidateCount: asNumber(metadata.memory_candidate_count) ?? 0,
    memoryAdmittedCount: asNumber(metadata.memory_admitted_count) ?? 0,
    memoryPersistedCount: asNumber(metadata.memory_persisted_count) ?? 0,
  };
};

const confidenceLabel = (value?: number): string | null => {
  if (value === undefined) return null;
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
};

const formatBytes = (value?: number | null): string => {
  if (!value || value <= 0) return 'Unavailable';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
};

const percentLabel = (value?: number | null): string =>
  value == null ? 'Unavailable' : `${Math.round(value)}%`;

const EmptyTruth = ({ children }: { children: React.ReactNode }) => (
  <p className="text-xs leading-relaxed text-muted-foreground">{children}</p>
);

function RailContent({
  metadata,
  agentSteps,
  approvals = [],
  approvalsLoadState = 'idle',
  systemResources = null,
  resourcesLoadState = 'idle',
}: ConversationContextRailProps) {
  const continuity = useMemo(
    () => normalizeContinuity(metadata || {}),
    [metadata],
  );
  const capabilities = useMemo(
    () => normalizeCapabilityReceipt(metadata || {}),
    [metadata],
  );
  const turnIntelligence = useMemo(
    () => normalizeTurnIntelligence(metadata || {}),
    [metadata],
  );
  const usage = useMemo(
    () => normalizeExecutionUsage(agentSteps, metadata || {}),
    [agentSteps, metadata],
  );
  const runtime = useMemo(
    () => normalizeRuntimeInsight(metadata || {}),
    [metadata],
  );
  const consumerInsights = useMemo(
    () => asRecord((metadata || {}).consumer_insights),
    [metadata],
  );
  const tokenWindow = asRecord(consumerInsights.token_window);
  const promptDecomposition = asRecord(consumerInsights.prompt_decomposition);
  const vectorHealth = asRecord(consumerInsights.vector_health);
  const counterfactuals = asRecord(consumerInsights.counterfactuals);
  const agentConsensus = asRecord(consumerInsights.agent_consensus);
  const executionWaterfall = asRecord(consumerInsights.execution_waterfall);

  const hasCapabilityTruth =
    Boolean(capabilities.executionTopology) ||
    capabilities.reasoningModes.length > 0 ||
    Boolean(capabilities.executionBudget) ||
    capabilities.allowedCapabilities.length > 0 ||
    capabilities.forbiddenCapabilities.length > 0 ||
    capabilities.allowedTools.length > 0 ||
    capabilities.allowedPlugins.length > 0 ||
    capabilities.allowedAgents.length > 0 ||
    capabilities.requiresHumanGate ||
    capabilities.requiresResumability ||
    Boolean(capabilities.workflowId);

  const hasUsage =
    usage.tools.length > 0 ||
    usage.plugins.length > 0 ||
    usage.providers.length > 0;

  const needsAttention =
    continuity.ambiguous ||
    capabilities.requiresHumanGate ||
    approvals.length > 0 ||
    approvalsLoadState === 'loading' ||
    approvalsLoadState === 'unavailable';

  return (
    <div className="space-y-3">
      <Card className="karen-surface border-border/70 bg-card/70">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
            <Brain className="h-3.5 w-3.5 text-primary" />
            Turn intelligence
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {(turnIntelligence.intent || turnIntelligence.recallStatus) && (
            <div className="rounded-lg border border-border/70 bg-muted/20 p-2.5">
              <p className="karen-panel-label text-[9px]">Turn understanding</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {turnIntelligence.intent && (
                  <Badge variant="secondary" className="text-[9px]">
                    {turnIntelligence.intent.replace(/_/g, ' ')}
                  </Badge>
                )}
                {confidenceLabel(turnIntelligence.intentConfidence) && (
                  <Badge variant="outline" className="text-[9px]">
                    {confidenceLabel(turnIntelligence.intentConfidence)} intent confidence
                  </Badge>
                )}
                {turnIntelligence.recallStatus && (
                  <Badge variant="outline" className="text-[9px]">
                    memory {turnIntelligence.recallStatus.replace(/_/g, ' ')}
                  </Badge>
                )}
              </div>
            </div>
          )}

          {turnIntelligence.recalled.length > 0 && (
            <div className="space-y-2">
              <p className="karen-panel-label text-[9px]">
                Context recalled ({turnIntelligence.recallCount})
              </p>
              {turnIntelligence.recalled.slice(0, 4).map((item) => (
                <div
                  key={item.id}
                  className="rounded-lg border border-border/70 bg-background/40 p-2.5"
                >
                  <p className="text-xs leading-relaxed">{item.content}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {confidenceLabel(item.relevance) && (
                      <Badge variant="outline" className="text-[9px]">
                        {confidenceLabel(item.relevance)} relevance
                      </Badge>
                    )}
                    {confidenceLabel(item.confidence) && (
                      <Badge variant="outline" className="text-[9px]">
                        {confidenceLabel(item.confidence)} confidence
                      </Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {(turnIntelligence.memoryFormationStatus ||
            turnIntelligence.memoryCandidateCount > 0 ||
            turnIntelligence.memoryPersistedCount > 0) && (
            <div className="rounded-lg border border-border/70 bg-background/40 p-2.5">
              <p className="karen-panel-label text-[9px]">Learning this turn</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {turnIntelligence.memoryFormationStatus && (
                  <Badge variant="outline" className="text-[9px]">
                    {turnIntelligence.memoryFormationStatus.replace(/_/g, ' ')}
                  </Badge>
                )}
                <Badge variant="outline" className="text-[9px]">
                  {turnIntelligence.memoryCandidateCount} candidates
                </Badge>
                <Badge variant="outline" className="text-[9px]">
                  {turnIntelligence.memoryAdmittedCount} admitted
                </Badge>
                <Badge variant="outline" className="text-[9px]">
                  {turnIntelligence.memoryPersistedCount} persisted
                </Badge>
              </div>
            </div>
          )}

          {continuity.candidates.length > 0 ? (
            continuity.candidates.map((candidate) => (
              <div
                key={candidate.id}
                className="rounded-lg border border-border/70 bg-muted/20 p-2.5"
                data-continuity-primary={candidate.primary || undefined}
              >
                <div className="flex items-start gap-2">
                  <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium leading-relaxed">
                      {candidate.subject}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {candidate.primary && (
                        <Badge variant="secondary" className="text-[9px]">
                          primary continuity
                        </Badge>
                      )}
                      {candidate.sourceType && (
                        <Badge variant="outline" className="text-[9px]">
                          {candidate.sourceType.replace(/_/g, ' ')}
                        </Badge>
                      )}
                      {candidate.urgency && (
                        <Badge variant="outline" className="text-[9px]">
                          {candidate.urgency}
                        </Badge>
                      )}
                      {confidenceLabel(candidate.confidence) && (
                        <Badge variant="outline" className="text-[9px]">
                          {confidenceLabel(candidate.confidence)} confidence
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))
          ) : (
            turnIntelligence.recalled.length === 0 &&
            !turnIntelligence.intent && (
              <EmptyTruth>
                No memory, intent, or continuity insight was reported for this turn.
              </EmptyTruth>
            )
          )}
        </CardContent>
      </Card>

      {(runtime.actualProvider ||
        runtime.runtimeEngine ||
        runtime.latencyMs !== undefined ||
        runtime.degradedMode) && (
        <Card className="karen-surface overflow-hidden border-border/70 bg-card/70">
          <CardHeader className="border-b border-border/50 bg-muted/10 pb-2">
            <CardTitle className="flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wider">
              <span className="flex items-center gap-2">
                <Route className="h-3.5 w-3.5 text-primary" />
                Runtime dispatch
              </span>
              <Badge
                variant={runtime.degradedMode ? 'outline' : 'secondary'}
                className="text-[9px]"
              >
                {runtime.degradedMode ? 'degraded' : 'healthy'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 pt-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                <p className="karen-panel-label text-[8px]">Provider</p>
                <p className="mt-1 truncate text-xs font-semibold">
                  {runtime.actualProvider || 'Unavailable'}
                </p>
                <p className="truncate text-[9px] text-muted-foreground">
                  {runtime.actualModel || runtime.runtimeEngine || 'No model reported'}
                </p>
              </div>
              <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                <p className="karen-panel-label text-[8px]">Turn latency</p>
                <p className="mt-1 text-xs font-semibold">
                  {runtime.latencyMs !== undefined
                    ? `${Math.round(runtime.latencyMs)} ms`
                    : 'Unavailable'}
                </p>
                <p className="text-[9px] text-muted-foreground">
                  {runtime.mode || runtime.responseSource || 'runtime'}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {runtime.locality && (
                <Badge variant="outline" className="text-[9px]">
                  {runtime.locality}
                </Badge>
              )}
              {runtime.runtimeEngine && (
                <Badge variant="outline" className="text-[9px]">
                  {runtime.runtimeEngine}
                </Badge>
              )}
              {runtime.providerAttempts.length > 0 && (
                <Badge variant="outline" className="text-[9px]">
                  {runtime.providerAttempts.length} provider attempt{runtime.providerAttempts.length === 1 ? '' : 's'}
                </Badge>
              )}
              {runtime.usedFallback && (
                <Badge variant="outline" className="text-[9px]">
                  fallback L{runtime.fallbackLevel}
                </Badge>
              )}
            </div>

            {runtime.providerAttempts.length > 0 && (
              <div className="rounded-lg border border-border/60 bg-background/30 p-2.5">
                <div className="mb-2 flex items-center justify-between">
                  <p className="karen-panel-label text-[8px]">Provider route</p>
                  <span className="text-[8px] text-muted-foreground">
                    {runtime.providerAttempts.length} hop{runtime.providerAttempts.length === 1 ? '' : 's'}
                  </span>
                </div>
                <div className="space-y-1.5">
                  {runtime.providerAttempts.slice(0, 4).map((attempt, index) => (
                    <div
                      key={`${attempt.provider || 'provider'}:${attempt.model || 'model'}:${index}`}
                      className="flex items-center gap-2 text-[9px]"
                    >
                      <span
                        className={[
                          'h-1.5 w-1.5 shrink-0 rounded-full',
                          attempt.status === 'success'
                            ? 'bg-emerald-500'
                            : attempt.status === 'failed' || attempt.errorType
                              ? 'bg-amber-500'
                              : 'bg-muted-foreground/50',
                        ].join(' ')}
                      />
                      <span className="min-w-0 flex-1 truncate">
                        {attempt.provider || 'unknown provider'}
                        {attempt.model ? ` · ${attempt.model}` : ''}
                      </span>
                      {attempt.status && (
                        <span className="shrink-0 text-muted-foreground">
                          {attempt.status}
                        </span>
                      )}
                      {attempt.latencyMs !== undefined && (
                        <span className="w-12 shrink-0 text-right font-mono text-muted-foreground">
                          {Math.round(attempt.latencyMs)} ms
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {runtime.degradationReason && (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2 text-[10px] leading-relaxed text-amber-700 dark:text-amber-300">
                {runtime.degradationReason.replace(/_/g, ' ')}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {Object.keys(consumerInsights).length > 0 && (
        <>
          <Card className="karen-surface overflow-hidden border-border/70 bg-card/70">
            <CardHeader className="border-b border-border/50 bg-muted/10 pb-2">
              <CardTitle className="flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wider">
                <span className="flex items-center gap-2">
                  <ChartNoAxesColumnIncreasing className="h-3.5 w-3.5 text-primary" />
                  Token window
                </span>
                <Badge variant="outline" className="text-[9px]">
                  {asString(tokenWindow.source) || 'unavailable'}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5 pt-3">
              {tokenWindow.available === true ? (
                <>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                      <p className="text-[8px] uppercase text-muted-foreground">Input</p>
                      <p className="mt-1 text-xs font-semibold">{asNumber(tokenWindow.input_tokens) ?? 0}</p>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                      <p className="text-[8px] uppercase text-muted-foreground">Headroom</p>
                      <p className="mt-1 text-xs font-semibold">{asNumber(tokenWindow.context_headroom_tokens) ?? 0}</p>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                      <p className="text-[8px] uppercase text-muted-foreground">Used</p>
                      <p className="mt-1 text-xs font-semibold">{asNumber(tokenWindow.context_used_percent) ?? 0}%</p>
                    </div>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{
                        width: `${Math.max(0, Math.min(100, asNumber(tokenWindow.context_used_percent) ?? 0))}%`,
                      }}
                    />
                  </div>
                  {(asNumber(tokenWindow.truncation_count) ?? 0) > 0 && (
                    <p className="text-[9px] text-amber-600 dark:text-amber-400">
                      {asNumber(tokenWindow.truncation_count)} prompt truncation event(s)
                    </p>
                  )}
                </>
              ) : (
                <EmptyTruth>Token-window telemetry was not available for this turn.</EmptyTruth>
              )}
            </CardContent>
          </Card>

          <Card className="karen-surface border-border/70 bg-card/70">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
                <Brain className="h-3.5 w-3.5 text-primary" />
                Prompt decomposition
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {promptDecomposition.available === true ? (
                Object.entries(asRecord(promptDecomposition.sections)).map(([name, raw]) => {
                  const section = asRecord(raw);
                  const percent = asNumber(section.percent) ?? 0;
                  return (
                    <div key={name} className="space-y-1">
                      <div className="flex items-center justify-between text-[9px]">
                        <span className="capitalize text-muted-foreground">{name}</span>
                        <span>{asNumber(section.tokens) ?? 0} · {percent}%</span>
                      </div>
                      <div className="h-1 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
                      </div>
                    </div>
                  );
                })
              ) : (
                <EmptyTruth>Prompt section accounting was not reported for this turn.</EmptyTruth>
              )}
            </CardContent>
          </Card>

          <Card className="karen-surface border-border/70 bg-card/70">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wider">
                <span className="flex items-center gap-2">
                  <Network className="h-3.5 w-3.5 text-primary" />
                  Retrieval / vector health
                </span>
                <Badge variant="outline" className="text-[9px]">
                  {vectorHealth.available === true ? 'reported' : 'not reported'}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {vectorHealth.available === true ? (
                <div className="grid grid-cols-2 gap-2 text-[10px]">
                  {Object.entries(vectorHealth)
                    .filter(([key]) => key !== 'available')
                    .slice(0, 6)
                    .map(([key, value]) => (
                      <div key={key} className="rounded-lg border border-border/60 bg-background/40 p-2">
                        <p className="text-[8px] uppercase text-muted-foreground">{key.replace(/_/g, ' ')}</p>
                        <p className="mt-1 truncate font-semibold">{String(value)}</p>
                      </div>
                    ))}
                </div>
              ) : (
                <EmptyTruth>
                  {asString(vectorHealth.unavailable_reason).replace(/_/g, ' ') || 'Vector health is unavailable.'}
                </EmptyTruth>
              )}
            </CardContent>
          </Card>

          <Card className="karen-surface border-border/70 bg-card/70">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
                <Scale className="h-3.5 w-3.5 text-primary" />
                Counterfactual scenarios
              </CardTitle>
            </CardHeader>
            <CardContent>
              {counterfactuals.available === true ? (
                <pre className="whitespace-pre-wrap text-[9px] text-muted-foreground">
                  {JSON.stringify(counterfactuals, null, 2)}
                </pre>
              ) : (
                <EmptyTruth>
                  {asString(counterfactuals.unavailable_reason).replace(/_/g, ' ') || 'No counterfactual scenario was evaluated.'}
                </EmptyTruth>
              )}
            </CardContent>
          </Card>

          <Card className="karen-surface border-border/70 bg-card/70">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
                <UsersRound className="h-3.5 w-3.5 text-primary" />
                Agent consensus
              </CardTitle>
            </CardHeader>
            <CardContent>
              {agentConsensus.available === true ? (
                <pre className="whitespace-pre-wrap text-[9px] text-muted-foreground">
                  {JSON.stringify(agentConsensus, null, 2)}
                </pre>
              ) : (
                <EmptyTruth>
                  {asString(agentConsensus.unavailable_reason).replace(/_/g, ' ') || 'No multi-agent consensus was reported.'}
                </EmptyTruth>
              )}
            </CardContent>
          </Card>

          <Card className="karen-surface border-border/70 bg-card/70">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wider">
                <span className="flex items-center gap-2">
                  <TimerReset className="h-3.5 w-3.5 text-primary" />
                  Execution waterfall
                </span>
                {asNumber(executionWaterfall.total_latency_ms) !== undefined && (
                  <span className="font-mono text-[9px] text-muted-foreground">
                    {Math.round(asNumber(executionWaterfall.total_latency_ms) || 0)} ms
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {executionWaterfall.available === true && Array.isArray(executionWaterfall.spans) ? (
                executionWaterfall.spans.slice(0, 8).map((raw, index) => {
                  const span = asRecord(raw);
                  const duration = asNumber(span.duration_ms) ?? 0;
                  const total = asNumber(executionWaterfall.total_latency_ms) || duration || 1;
                  return (
                    <div key={`${asString(span.name) || 'span'}:${index}`} className="space-y-1">
                      <div className="flex items-center justify-between gap-2 text-[9px]">
                        <span className="truncate text-muted-foreground">{asString(span.name) || 'runtime span'}</span>
                        <span className="shrink-0 font-mono">{Math.round(duration)} ms</span>
                      </div>
                      <div className="h-1 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(2, Math.min(100, (duration / total) * 100))}%` }} />
                      </div>
                    </div>
                  );
                })
              ) : (
                <EmptyTruth>
                  {asString(executionWaterfall.unavailable_reason).replace(/_/g, ' ') || 'No execution spans were reported.'}
                </EmptyTruth>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {(resourcesLoadState !== 'idle' || systemResources) && (
        <Card className="karen-surface overflow-hidden border-border/70 bg-card/70">
          <CardHeader className="border-b border-border/50 bg-muted/10 pb-2">
            <CardTitle className="flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wider">
              <span className="flex items-center gap-2">
                <Gauge className="h-3.5 w-3.5 text-primary" />
                System resources
              </span>
              <Badge variant="outline" className="text-[9px]">
                {resourcesLoadState === 'ready' ? 'live' : resourcesLoadState}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 pt-3">
            {!systemResources ? (
              <EmptyTruth>
                {resourcesLoadState === 'loading'
                  ? 'Reading local system resources…'
                  : 'System resource telemetry is unavailable.'}
              </EmptyTruth>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2 text-[10px]">
                  <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <Cpu className="h-3 w-3" />
                      CPU
                    </div>
                    <p className="mt-1 text-xs font-semibold">
                      {percentLabel(systemResources.cpu.usage_percent)}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <MemoryStick className="h-3 w-3" />
                      RAM
                    </div>
                    <p className="mt-1 text-xs font-semibold">
                      {percentLabel(systemResources.memory.usage_percent)}
                    </p>
                    <p className="text-[9px] text-muted-foreground">
                      {formatBytes(systemResources.memory.available_bytes)} free
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <Activity className="h-3 w-3" />
                      GPU / VRAM
                    </div>
                    <p className="mt-1 text-xs font-semibold">
                      {systemResources.gpu.available
                        ? `${percentLabel(systemResources.gpu.usage_percent)} / ${percentLabel(systemResources.vram.usage_percent)}`
                        : 'Unavailable'}
                    </p>
                    {systemResources.vram.available && (
                      <p className="text-[9px] text-muted-foreground">
                        {formatBytes(systemResources.vram.available_bytes)} VRAM free
                      </p>
                    )}
                  </div>
                  <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                    <div className="flex items-center gap-1.5 text-muted-foreground">
                      <Database className="h-3 w-3" />
                      Disk
                    </div>
                    <p className="mt-1 text-xs font-semibold">
                      {percentLabel(systemResources.disk.usage_percent)}
                    </p>
                    <p className="text-[9px] text-muted-foreground">
                      {formatBytes(systemResources.disk.available_bytes)} free
                    </p>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {(capabilities.executionTopology ||
        capabilities.executionBudget ||
        capabilities.reasoningModes.length > 0 ||
        capabilities.requiresResumability ||
        capabilities.workflowId) && (
        <Card className="karen-surface overflow-hidden border-border/70 bg-card/70">
          <CardHeader className="border-b border-border/50 bg-muted/10 pb-2">
            <CardTitle className="flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wider">
              <span className="flex items-center gap-2">
                <Gauge className="h-3.5 w-3.5 text-primary" />
                Execution envelope
              </span>
              {capabilities.executionTopology && (
                <Badge variant="outline" className="text-[9px]">
                  {capabilities.executionTopology}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5 pt-3">
            {capabilities.executionBudget && (
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                  <p className="text-[8px] uppercase tracking-wide text-muted-foreground">Model calls</p>
                  <p className="mt-1 text-xs font-semibold">
                    {capabilities.executionBudget.maxModelCalls ?? 'n/a'}
                  </p>
                </div>
                <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                  <p className="text-[8px] uppercase tracking-wide text-muted-foreground">Tool calls</p>
                  <p className="mt-1 text-xs font-semibold">
                    {capabilities.executionBudget.maxToolCalls ?? 'n/a'}
                  </p>
                </div>
                <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                  <p className="text-[8px] uppercase tracking-wide text-muted-foreground">Reasoning steps</p>
                  <p className="mt-1 text-xs font-semibold">
                    {capabilities.executionBudget.maxReasoningSteps ?? 'n/a'}
                  </p>
                </div>
                <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                  <p className="text-[8px] uppercase tracking-wide text-muted-foreground">Output budget</p>
                  <p className="mt-1 text-xs font-semibold">
                    {capabilities.executionBudget.maxOutputTokens
                      ? `${capabilities.executionBudget.maxOutputTokens.toLocaleString()} tokens`
                      : 'n/a'}
                  </p>
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-1.5">
              {capabilities.reasoningModes.map((mode) => (
                <Badge key={mode} variant="secondary" className="text-[9px]">
                  {mode.replace(/_/g, ' ')}
                </Badge>
              ))}
              {capabilities.requiresResumability && (
                <Badge variant="outline" className="text-[9px]">
                  resumable
                </Badge>
              )}
              {capabilities.workflowId && (
                <Badge variant="outline" className="max-w-full truncate text-[9px]">
                  workflow {capabilities.workflowId}
                  {capabilities.workflowVersion ? ` · ${capabilities.workflowVersion}` : ''}
                </Badge>
              )}
            </div>

            {(capabilities.policyDecisionId || capabilities.policyReasonCodes.length > 0) && (
              <div className="rounded-lg border border-border/60 bg-background/30 p-2.5">
                <p className="karen-panel-label text-[8px]">Policy lineage</p>
                {capabilities.policyDecisionId && (
                  <p className="mt-1 truncate font-mono text-[8px] text-muted-foreground">
                    {capabilities.policyDecisionId}
                  </p>
                )}
                {capabilities.policyReasonCodes.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {capabilities.policyReasonCodes.slice(0, 5).map((reason) => (
                      <Badge key={reason} variant="outline" className="text-[8px]">
                        {reason.replace(/_/g, ' ')}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card className="karen-surface border-border/70 bg-card/70">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            Guardrails & capabilities
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!hasCapabilityTruth ? (
            <EmptyTruth>
              No request-scoped capability receipt was reported yet.
            </EmptyTruth>
          ) : (
            <>
              {capabilities.allowedTools.length > 0 && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase text-muted-foreground">
                    <Wrench className="h-3 w-3" />
                    Tools
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {capabilities.allowedTools.map((tool) => (
                      <Badge key={tool} variant="secondary" className="text-[9px]">
                        {tool}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {capabilities.allowedPlugins.length > 0 && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase text-muted-foreground">
                    <PlugZap className="h-3 w-3" />
                    Plugins
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {capabilities.allowedPlugins.map((plugin) => (
                      <Badge key={plugin} variant="secondary" className="text-[9px]">
                        {plugin}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {capabilities.allowedAgents.length > 0 && (
                <div>
                  <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase text-muted-foreground">
                    <Bot className="h-3 w-3" />
                    Agents
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {capabilities.allowedAgents.map((agent) => (
                      <Badge key={agent} variant="secondary" className="text-[9px]">
                        {agent}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {capabilities.allowedCapabilities.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[10px] font-semibold uppercase text-muted-foreground">
                    Runtime permissions
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {capabilities.allowedCapabilities.map((capability) => (
                      <Badge key={capability} variant="outline" className="text-[9px]">
                        {capability}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {capabilities.forbiddenCapabilities.length > 0 && (
                <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5">
                  <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase text-amber-600 dark:text-amber-400">
                    <ShieldAlert className="h-3 w-3" />
                    Blocked by policy
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {capabilities.forbiddenCapabilities.map((capability) => (
                      <Badge key={capability} variant="outline" className="text-[9px]">
                        {capability}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card className="karen-surface border-border/70 bg-card/70">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
            <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
            Execution trace
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {!hasUsage ? (
            <EmptyTruth>
              No tool, plugin, or provider activity has been reported for this turn.
            </EmptyTruth>
          ) : (
            <>
              {usage.tools.map((tool) => (
                <div key={`tool:${tool}`} className="flex items-center gap-2 text-xs">
                  <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="truncate">{tool}</span>
                </div>
              ))}
              {usage.plugins.map((plugin) => (
                <div key={`plugin:${plugin}`} className="flex items-center gap-2 text-xs">
                  <PlugZap className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="truncate">{plugin}</span>
                </div>
              ))}
              {usage.providers.map((provider) => (
                <div key={`provider:${provider}`} className="flex items-center gap-2 text-xs">
                  <Clock3 className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="truncate">{provider}</span>
                </div>
              ))}
            </>
          )}
        </CardContent>
      </Card>

      {(runtime.trajectoryId ||
        runtime.correlationId ||
        runtime.transcriptPersistenceStatus ||
        runtime.memoryPersistenceStatus) && (
        <Card className="karen-surface border-border/70 bg-card/70">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
              <GitBranch className="h-3.5 w-3.5 text-primary" />
              Provenance & persistence
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-[10px]">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                <p className="text-muted-foreground">Transcript</p>
                <p className="mt-0.5 font-semibold">
                  {(runtime.transcriptPersistenceStatus || 'unknown').replace(/_/g, ' ')}
                </p>
              </div>
              <div className="rounded-lg border border-border/60 bg-background/40 p-2">
                <p className="text-muted-foreground">Memory write</p>
                <p className="mt-0.5 font-semibold">
                  {(runtime.memoryPersistenceStatus || 'unknown').replace(/_/g, ' ')}
                </p>
              </div>
            </div>
            {runtime.trajectoryId && (
              <div className="flex items-center gap-2 truncate text-muted-foreground">
                <GitBranch className="h-3 w-3 shrink-0" />
                <span className="truncate">trajectory {runtime.trajectoryId}</span>
              </div>
            )}
            {runtime.correlationId && (
              <div className="truncate font-mono text-[9px] text-muted-foreground">
                correlation {runtime.correlationId}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {needsAttention && (
        <Card className="border-amber-500/20 bg-amber-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              Human attention
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            {continuity.ambiguous && (
              <p>
                More than one unfinished thread is plausible. KAREN should ask
                which one you want instead of guessing.
              </p>
            )}
            {capabilities.requiresHumanGate && approvals.length === 0 && (
              <p>
                The authorized plan requires a human approval before execution
                can continue.
              </p>
            )}

            {approvalsLoadState === 'loading' && (
              <p className="text-muted-foreground">
                Checking durable approval state for this conversation…
              </p>
            )}

            {approvalsLoadState === 'unavailable' && (
              <p className="text-muted-foreground">
                Approval state is unavailable, so KAREN cannot confirm whether
                an action is waiting for your decision.
              </p>
            )}

            {approvals.map((approval) => (
              <div
                key={approval.approval_id}
                className="rounded-lg border border-border/70 bg-background/50 p-2.5"
              >
                <p className="font-medium leading-relaxed">
                  {approval.status === 'approved'
                    ? `${approval.intent.replace(/_/g, ' ')} is approved and ready to resume.`
                    : `${approval.intent.replace(/_/g, ' ')} is waiting for your decision.`}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Badge variant="secondary" className="text-[9px]">
                    {approval.status === 'approved' ? 'ready to resume' : 'approval required'}
                  </Badge>
                  <Badge variant="outline" className="text-[9px]">
                    {approval.risk_level} risk
                  </Badge>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function ConversationContextRail(
  props: ConversationContextRailProps,
) {
  const [systemResources, setSystemResources] =
    useState<PlatformResourceSnapshot | null>(null);
  const [resourcesLoadState, setResourcesLoadState] = useState<
    'idle' | 'loading' | 'ready' | 'unavailable'
  >('idle');

  useEffect(() => {
    let cancelled = false;
    if (!window.matchMedia('(min-width: 1280px)').matches) {
      return () => {
        cancelled = true;
      };
    }

    setResourcesLoadState('loading');

    const refreshResources = async () => {
      try {
        const snapshot = await apiClient.get<PlatformResourceSnapshot>(
          '/api/system/resources',
        );
        if (!cancelled) {
          setSystemResources(snapshot);
          setResourcesLoadState('ready');
        }
      } catch {
        if (!cancelled) {
          setSystemResources(null);
          setResourcesLoadState('unavailable');
        }
      }
    };

    void refreshResources();
    const timer = window.setInterval(() => {
      void refreshResources();
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const metadata = props.metadata || {};
  const runtime = normalizeRuntimeInsight(metadata);
  const hasTurnTruth =
    Boolean(runtime.actualProvider) ||
    Boolean(asString(metadata.intent)) ||
    Boolean(asNumber(metadata.memory_recall_count)) ||
    Boolean(runtime.trajectoryId);

  return (
    <aside
      className="hidden w-[21rem] shrink-0 overflow-y-auto border-l border-border/70 bg-background/45 p-3 xl:block 2xl:w-[22rem]"
      aria-label="Conversation intelligence deck"
      data-testid="conversation-context-rail"
    >
      <div className="sticky top-0 space-y-3">
        <div className="sticky top-0 z-10 rounded-2xl border border-border/70 bg-card/90 p-3 shadow-sm backdrop-blur-xl">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-start gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <Brain className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-foreground">
                  Conversation Intelligence
                </p>
                <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                  Turn context, runtime dispatch, memory, policy, resources, and execution truth.
                </p>
              </div>
            </div>
            <span
              className={[
                'mt-1 h-2 w-2 shrink-0 rounded-full',
                hasTurnTruth ? 'bg-emerald-500' : 'bg-muted-foreground/40',
              ].join(' ')}
              aria-label={hasTurnTruth ? 'Turn intelligence available' : 'Awaiting turn intelligence'}
            />
          </div>

          <div className="mt-3 flex flex-wrap gap-1.5 border-t border-border/50 pt-2.5">
            {runtime.actualProvider && (
              <Badge variant="secondary" className="text-[8px]">
                {runtime.actualProvider}
              </Badge>
            )}
            {runtime.latencyMs !== undefined && (
              <Badge variant="outline" className="text-[8px]">
                {Math.round(runtime.latencyMs)} ms
              </Badge>
            )}
            <Badge variant="outline" className="text-[8px]">
              resources {resourcesLoadState === 'ready' ? 'live' : resourcesLoadState}
            </Badge>
            {runtime.degradedMode && (
              <Badge variant="outline" className="text-[8px]">
                degraded
              </Badge>
            )}
          </div>
        </div>

        <RailContent
          {...props}
          systemResources={systemResources}
          resourcesLoadState={resourcesLoadState}
        />
      </div>
    </aside>
  );
}
