'use client';

import { useMemo } from 'react';
import {
  AlertTriangle,
  Bot,
  Brain,
  CheckCircle2,
  ChevronRight,
  Clock3,
  PlugZap,
  ShieldAlert,
  Sparkles,
  Wrench,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AgentStepEvent } from '@/lib/types';

type JsonRecord = Record<string, unknown>;

interface ConversationContextRailProps {
  metadata?: JsonRecord;
  agentSteps: AgentStepEvent[];
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

const normalizeExecutionUsage = (steps: AgentStepEvent[]): ExecutionUsage => {
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

  return {
    tools: unique(tools),
    plugins: unique(plugins),
    providers: unique(providers),
  };
};

const confidenceLabel = (value?: number): string | null => {
  if (value === undefined) return null;
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
};

const EmptyTruth = ({ children }: { children: React.ReactNode }) => (
  <p className="text-xs leading-relaxed text-muted-foreground">{children}</p>
);

function RailContent({
  metadata,
  agentSteps,
}: ConversationContextRailProps) {
  const continuity = useMemo(
    () => normalizeContinuity(metadata || {}),
    [metadata],
  );
  const capabilities = useMemo(
    () => normalizeCapabilityReceipt(metadata || {}),
    [metadata],
  );
  const usage = useMemo(
    () => normalizeExecutionUsage(agentSteps),
    [agentSteps],
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
    continuity.ambiguous || capabilities.requiresHumanGate;

  return (
    <div className="space-y-3">
      <Card className="karen-surface border-border/70 bg-card/70">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
            <Brain className="h-3.5 w-3.5 text-primary" />
            Now
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {continuity.candidates.length === 0 ? (
            <EmptyTruth>
              No continuity candidates were reported for this turn.
            </EmptyTruth>
          ) : (
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
                          primary
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
            {capabilities.requiresHumanGate && (
              <p>
                The authorized plan requires a human approval before execution
                can continue.
              </p>
            )}
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
            Canonical continuity, permissions, and execution activity for this turn.
          </p>
        </div>
        <RailContent {...props} />
      </div>
    </aside>
  );
}
