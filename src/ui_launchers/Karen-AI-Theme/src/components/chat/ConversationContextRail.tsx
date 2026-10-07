'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  Cpu,
  Database,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Gauge,
  GitBranch,
  MemoryStick,
  PlugZap,
  Route,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
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
  allowedCapabilities: string[];
  forbiddenCapabilities: string[];
  allowedTools: string[];
  allowedPlugins: string[];
  allowedAgents: string[];
  requiresHumanGate: boolean;
  requiresResumability: boolean;
  workflowId?: string;
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
  providerAttempts: number;
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

  return {
    allowedCapabilities: asStringArray(receipt.allowed_capabilities),
    forbiddenCapabilities: asStringArray(receipt.forbidden_capabilities),
    allowedTools: asStringArray(receipt.allowed_tools),
    allowedPlugins: asStringArray(receipt.allowed_plugins),
    allowedAgents: asStringArray(receipt.allowed_agents),
    requiresHumanGate: receipt.requires_human_gate === true,
    requiresResumability: receipt.requires_resumability === true,
    workflowId: asString(receipt.workflow_id) || undefined,
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
    ? metadata.provider_attempts.length
    : 0;

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

  const hasCapabilityTruth =
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
            Now
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

      <Card className="karen-surface border-border/70 bg-card/70">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            Can use
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
            Used
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

      {needsAttention && (
        <Card className="border-amber-500/20 bg-amber-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              Needs you
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
  return (
    <aside
      className="hidden w-[19rem] shrink-0 overflow-y-auto border-l border-border/70 bg-background/40 p-3 xl:block 2xl:w-[20rem]"
      aria-label="Conversation context and capabilities"
      data-testid="conversation-context-rail"
    >
      <div className="sticky top-0">
        <div className="mb-3 px-1">
          <p className="karen-panel-label text-foreground/90">
            Conversation intelligence
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            What Karen understood, remembered, learned, and actually used for this turn.
          </p>
        </div>
        <RailContent {...props} />
      </div>
    </aside>
  );
}
