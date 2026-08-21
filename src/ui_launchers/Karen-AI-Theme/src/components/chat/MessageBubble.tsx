'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import type { ChatMessage } from '@/lib/types';
import type { SuggestedAction } from '@/lib/agent-ui/service';
import Image from 'next/image';
import { format } from 'date-fns';
import {
  AlertTriangle,
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Copy,
  Info,
  PlusCircle,
  Speaker,
  ThumbsDown,
  ThumbsUp,
  User,
  Zap,
} from 'lucide-react';

import { Avatar } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import {
  deriveCompactBadgePresentation,
  deriveDegradedPresentation,
  deriveResponseDetailsPresentation,
  sanitizeChatContent,
} from '@/lib/chat-response';
import { ChatRenderedContent } from '@/lib/chat-renderer';

import CitationBadge from './CitationBadge';
import SourceList from './SourceList';

interface MessageBubbleProps {
  message: ChatMessage;
  onActionClick?: (action: SuggestedAction) => void;
}

type FeedbackValue = 'up' | 'down' | null;

const COPY_RESET_DELAY_MS = 2000;
const FEEDBACK_RESET_DELAY_MS = 3000;

const isAssistantMessage = (message: ChatMessage): boolean => {
  return message.role === 'assistant';
};

const isUserMessage = (message: ChatMessage): boolean => {
  return message.role === 'user';
};

const getSafeTimestampLabel = (timestamp: unknown): string => {
  const date =
    timestamp instanceof Date
      ? timestamp
      : new Date(
          typeof timestamp === 'string' || typeof timestamp === 'number'
            ? timestamp
            : Date.now(),
        );

  if (Number.isNaN(date.getTime())) {
    return format(new Date(), 'h:mm a');
  }

  return format(date, 'h:mm a');
};

const copyTextFallback = (text: string): boolean => {
  if (typeof document === 'undefined') {
    return false;
  }

  const textArea = document.createElement('textarea');
  textArea.value = text;

  /*
   * Keep the fallback node invisible but focusable. execCommand is deprecated,
   * yet still the safest fallback for older/non-secure browser contexts.
   */
  textArea.style.position = 'fixed';
  textArea.style.left = '-999999px';
  textArea.style.top = '-999999px';
  textArea.style.opacity = '0';

  document.body.appendChild(textArea);

  try {
    textArea.focus();
    textArea.select();

    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    document.body.removeChild(textArea);
  }
};

const getActionLabel = (action: SuggestedAction): string => {
  if (action.type === 'routing.profile.list') {
    return 'Show Available Profiles';
  }

  return action.description || action.type || 'Perform Action';
};

const renderMetadataPair = ({
  label,
  value,
  title,
  valueClassName = 'font-semibold',
  testId,
}: {
  label: string;
  value: string;
  title?: string;
  valueClassName?: string;
  testId?: string;
}) => {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted-foreground">{label}:</span>
      <span 
        className={valueClassName} 
        title={title || value}
        data-testid={testId}
      >
        {value}
      </span>
    </div>
  );
};

export function MessageBubble({ message, onActionClick }: MessageBubbleProps) {
  const isUser = isUserMessage(message);
  const isAssistant = isAssistantMessage(message);
  const isSystemMessage = message.role === 'system';

  const [copied, setCopied] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackValue>(null);
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);

  const responseDetailsId = `response-details-${message.id}`;
  const normalizedContent = useMemo(
    () => sanitizeChatContent(message.content),
    [message.content],
  );

  const {
    visibleDegradedNotice,
    shouldRenderDegradedState,
  } = deriveDegradedPresentation(message.metadata);

  const {
    shouldRenderBadge,
    providerLabel: badgeProviderLabel,
    modelLabel: badgeModelLabel,
    durationLabel: badgeDurationLabel,
    speedLabel: badgeSpeedLabel,
    statusLabel: badgeStatusLabel,
    isDegraded: badgeIsDegraded,
  } = deriveCompactBadgePresentation(message.metadata);

  const {
    hasMetadataDetails,
    requestedProviderLabel,
    requestedModelLabel,
    providerLabel,
    modelLabel,
    modelTitle,
    sourceLabel,
    runtimeEngineLabel,
    fallbackLevelLabel,
    speedLabel,
    latencyLabel,
    engineHeaderLabel,
    showStatusRow,
    statusLabel,
    showFallbackRow,
    fallbackLabel,
    showReasonRow,
    reasonLabel,
    showTokensRow,
    tokensLabel,
    memoryUsedLabel,
    memoryClassesLabel,
    recallModeLabel,
    memorySourcesLabel,
    memoryLatencyLabel,
    memoryDegradedLabel,
    writebackStatusLabel,
  } = deriveResponseDetailsPresentation(message.metadata);

  const normalizedDegradedNotice = useMemo(
    () => sanitizeChatContent(visibleDegradedNotice),
    [visibleDegradedNotice],
  );

  const shouldShowDegradedNotice =
    Boolean(normalizedDegradedNotice) &&
    normalizedDegradedNotice.toLowerCase() !== normalizedContent.toLowerCase();

  const hasCitations =
    !isUser && Array.isArray(message.citations) && message.citations.length > 0;

  const hasStructuredContent =
    Boolean(message.structuredContent) &&
    Object.keys(message.structuredContent || {}).length > 0;

  const timestampLabel = useMemo(
    () => getSafeTimestampLabel(message.timestamp),
    [message.timestamp],
  );

  useEffect(() => {
    if (!copied) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setCopied(false);
    }, COPY_RESET_DELAY_MS);

    return () => window.clearTimeout(timer);
  }, [copied]);

  useEffect(() => {
    if (!feedbackSubmitted) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setFeedbackSubmitted(false);
    }, FEEDBACK_RESET_DELAY_MS);

    return () => window.clearTimeout(timer);
  }, [feedbackSubmitted]);

  const handleCopy = useCallback(async () => {
    if (!message.content) {
      return;
    }

    try {
      if (
        typeof navigator !== 'undefined' &&
        navigator.clipboard &&
        typeof window !== 'undefined' &&
        window.isSecureContext
      ) {
        await navigator.clipboard.writeText(message.content);
        setCopied(true);
        return;
      }

      if (copyTextFallback(message.content)) {
        setCopied(true);
      }
    } catch {
      if (copyTextFallback(message.content)) {
        setCopied(true);
      }
    }
  }, [message.content]);

  const handleFeedback = useCallback(
    async (type: Exclude<FeedbackValue, null>) => {
      const nextFeedback = feedback === type ? null : type;
      setFeedback(nextFeedback);

      if (!nextFeedback || feedbackSubmitted) {
        return;
      }

      /*
       * Feedback remains UI-local until the backend feedback endpoint is wired.
       * Do not fake provider/runtime metadata from this control.
       */
      setFeedbackSubmitted(true);
    },
    [feedback, feedbackSubmitted],
  );

  return (
    <div
      className={`user-bubble my-3 flex animate-in items-start gap-2 px-2 duration-300 fade-in slide-in-from-bottom-2 sm:my-4 sm:gap-3 sm:px-0 ${
        isUser ? 'justify-end' : 'justify-start'
      }`}
    >
      {!isUser && (
        <Avatar
          className={`flex h-8 w-8 shrink-0 items-center justify-center self-start rounded-full shadow-sm sm:h-10 sm:w-10 ${
            shouldRenderDegradedState ? 'bg-amber-500/20' : 'bg-muted'
          }`}
        >
          <Bot
            className={`h-4 w-4 sm:h-5 sm:w-5 ${
              shouldRenderDegradedState ? 'text-amber-600' : 'text-primary'
            }`}
            aria-hidden="true"
          />
        </Avatar>
      )}

      <Card
        className={`max-w-[90vw] rounded-2xl border-none shadow-md transition-all duration-300 sm:max-w-xl ${
          isUser
            ? 'rounded-tr-none bg-primary text-primary-foreground'
            : 'w-full flex-1 rounded-tl-none bg-card ring-1 ring-border/5'
        }`}
        data-testid={isUser ? 'chat-message-user' : 'chat-message-assistant'}
      >
        <CardContent className="p-2 sm:p-3 md:p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 space-y-2 overflow-hidden">
              {isAssistant && shouldShowDegradedNotice && (
                <div className="flex items-center justify-between rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200/90">
                  <span>{normalizedDegradedNotice}</span>
                  <span className="animate-pulse text-[10px] font-medium tracking-tight text-amber-500/70">
                    degraded mode
                  </span>
                </div>
              )}

              {message.content && (
                <ChatRenderedContent
                  content={normalizedContent}
                  emphasize={isSystemMessage}
                />
              )}

              {/*
               * Compact badge and expanded details display backend metadata.
               * They must not infer the actual provider from the selected provider.
               */}
              {isAssistant && shouldRenderBadge && !badgeIsDegraded && (
                <div className="mt-2 flex flex-wrap items-center gap-2 overflow-hidden">
                  <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/10 bg-primary/5 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-primary/80 shadow-sm shadow-primary/5 transition-all duration-300">
                    <Zap className="h-3 w-3" aria-hidden="true" />

                    <span>{badgeProviderLabel}</span>
                    <span className="text-muted-foreground/50">·</span>
                    <span className="font-medium normal-case">
                      {badgeModelLabel}
                    </span>

                    {badgeDurationLabel && (
                      <>
                        <span className="text-muted-foreground/50">·</span>
                        <Clock className="h-2.5 w-2.5" aria-hidden="true" />
                        <span className="font-medium normal-case">
                          {badgeDurationLabel}
                        </span>
                      </>
                    )}

                    {badgeSpeedLabel && (
                      <>
                        <span className="text-muted-foreground/50">·</span>
                        <span className="font-medium normal-case text-emerald-500">
                          {badgeSpeedLabel}
                        </span>
                      </>
                    )}
                  </div>

                  {badgeStatusLabel && (
                    <span className="animate-pulse text-[10px] font-medium tracking-tight text-amber-500/70">
                      {badgeStatusLabel}
                    </span>
                  )}
                </div>
              )}

              {isAssistant && hasMetadataDetails && (
                <div className="mt-1 overflow-hidden transition-all duration-300">
                  <button
                    type="button"
                    onClick={() => setShowDetails((current) => !current)}
                    className="group flex items-center gap-1 text-[10px] text-muted-foreground transition-all hover:text-primary"
                    aria-label={
                      showDetails ? 'Hide response details' : 'Show response details'
                    }
                    data-testid="chat-response-details-toggle"
                    aria-expanded={showDetails}
                    aria-controls={responseDetailsId}
                  >
                    <Info
                      className="h-3 w-3 transition-transform group-hover:scale-110"
                      aria-hidden="true"
                    />
                    <span>
                      {showDetails ? 'Hide response details' : 'Show response details'}
                    </span>
                    {showDetails ? (
                      <ChevronUp className="h-3 w-3" aria-hidden="true" />
                    ) : (
                      <ChevronDown className="h-3 w-3" aria-hidden="true" />
                    )}
                  </button>

                  {showDetails && (
                    <div
                      id={responseDetailsId}
                      className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-xl border border-border/30 bg-muted/40 p-2.5 font-mono text-[10px] shadow-inner animate-in fade-in zoom-in-95 duration-200"
                      data-testid="chat-response-details-panel"
                      role="region"
                      aria-label="Response details"
                    >
                      <div className="col-span-2 mb-1 flex justify-between border-b border-border/20 pb-1">
                        <span className="text-[8px] font-bold uppercase tracking-wider text-muted-foreground">
                          Engine Metadata
                        </span>
                        <span className="text-[8px] font-bold uppercase text-blue-500">
                          {engineHeaderLabel}
                        </span>
                      </div>

                      {renderMetadataPair({
                        label: 'Requested Provider',
                        value: requestedProviderLabel,
                        testId: 'chat-requested-provider',
                      })}
                      {renderMetadataPair({
                        label: 'Actual Provider',
                        value: providerLabel,
                        testId: 'chat-actual-provider',
                      })}
                      {renderMetadataPair({
                        label: 'Requested Model',
                        value: requestedModelLabel,
                        valueClassName: 'max-w-[120px] truncate font-semibold',
                        testId: 'chat-requested-model',
                      })}
                      {renderMetadataPair({
                        label: 'Actual Model',
                        value: modelLabel,
                        title: modelTitle,
                        valueClassName: 'max-w-[120px] truncate font-semibold',
                        testId: 'chat-actual-model',
                      })}
                      {renderMetadataPair({
                        label: 'Response Source',
                        value: sourceLabel,
                        testId: 'chat-response-source',
                      })}
                      {renderMetadataPair({
                        label: 'Fallback Level',
                        value: fallbackLevelLabel,
                        testId: 'chat-fallback-level',
                      })}
                      {renderMetadataPair({
                        label: 'Runtime Engine',
                        value: runtimeEngineLabel,
                        testId: 'chat-runtime-engine',
                      })}
                      {renderMetadataPair({
                        label: 'Speed',
                        value: speedLabel,
                        valueClassName: 'font-semibold text-emerald-500',
                      })}
                      {renderMetadataPair({
                        label: 'Latency',
                        value: latencyLabel,
                        valueClassName: 'font-semibold text-blue-500',
                      })}

                      {showStatusRow && (
                        <div className="col-span-2 mt-1 flex justify-between border-t border-border/20 pt-1">
                          <span className="text-muted-foreground">Status:</span>
                          <span className="flex items-center gap-1 font-semibold text-amber-500" data-testid="chat-degraded-status">
                            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                            {statusLabel}
                          </span>
                        </div>
                      )}

                      {showFallbackRow && (
                        <div className="col-span-2 mt-1 border-t border-border/20 pt-1">
                          <span className="text-muted-foreground">Fallback:</span>
                          <span className="ml-2 break-all font-semibold text-amber-300">
                            {fallbackLabel}
                          </span>
                        </div>
                      )}

                      {renderMetadataPair({
                        label: 'Correlation ID',
                        value: message.metadata?.correlation_id || message.metadata?.llm?.correlation_id || 'N/A',
                        testId: 'chat-correlation-id',
                      })}

                      {showTokensRow && (
                        <div className="col-span-2 mt-1 flex justify-between border-t border-border/20 pt-1">
                          <span className="text-muted-foreground">Tokens:</span>
                          <span className="font-semibold text-amber-500">
                            {tokensLabel}
                          </span>
                        </div>
                      )}

                      <div className="col-span-2 mt-1 mb-1 flex justify-between border-t border-border/20 pt-1">
                        <span className="text-[8px] font-bold uppercase tracking-wider text-muted-foreground">Memory Metadata</span>
                      </div>
                      {renderMetadataPair({ label: 'Memory Used', value: memoryUsedLabel })}
                      {renderMetadataPair({ label: 'Memory Classes', value: memoryClassesLabel })}
                      {renderMetadataPair({ label: 'Recall Mode', value: recallModeLabel })}
                      {renderMetadataPair({ label: 'Memory Sources', value: memorySourcesLabel })}
                      {renderMetadataPair({ label: 'Memory Latency', value: memoryLatencyLabel })}
                      {renderMetadataPair({ label: 'Memory Degraded', value: memoryDegradedLabel })}
                      {renderMetadataPair({ label: 'Writeback Status', value: writebackStatusLabel })}

                      {providerAttempts && providerAttempts.length > 0 && (
                        <div className="col-span-2 mt-2 border-t border-border/20 pt-2">
                          <div className="mb-1 text-[8px] font-bold uppercase tracking-wider text-muted-foreground">Provider Attempts</div>
                          <div className="space-y-1" data-testid="chat-provider-attempts">
                            {providerAttempts.map((attempt, idx) => (
                              <div key={`${attempt.provider}-${attempt.model}-${idx}`} className="flex justify-between text-[9px]">
                                <span className="truncate text-muted-foreground">{attempt.provider} / {attempt.model || 'auto'}</span>
                                <span className={attempt.status === 'success' ? 'text-emerald-500' : 'text-rose-400'}>{attempt.status}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {hasStructuredContent && (
                <div className="mt-3 flex flex-col gap-2">
                  {Object.entries(message.structuredContent || {}).map(
                    ([key, value]) => (
                      <div
                        key={key}
                        className="group rounded-xl border border-border/50 bg-muted/30 p-3 text-sm shadow-inner transition-all hover:bg-muted/40"
                      >
                        <span className="mb-1 block text-xs font-semibold capitalize tracking-tight text-primary transition-colors group-hover:text-blue-500">
                          {key.replace(/_/g, ' ')}
                        </span>

                        {typeof value === 'string' ? (
                          <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">
                            {value}
                          </p>
                        ) : (
                          <pre className="overflow-x-auto rounded-lg border border-border/20 bg-background/50 p-2 text-[10px] text-foreground/80">
                            {JSON.stringify(value, null, 2)}
                          </pre>
                        )}
                      </div>
                    ),
                  )}
                </div>
              )}

              {hasCitations && (
                <CitationBadge
                  citations={message.citations}
                  onClick={() => setShowDetails((current) => !current)}
                />
              )}

              {showDetails && hasCitations && (
                <SourceList citations={message.citations || []} />
              )}

              {message.actions && message.actions.length > 0 && (
                <div className="mt-3 animate-in duration-500 fade-in slide-in-from-left-2 sm:mt-4">
                  <div className="mb-2 flex items-center gap-2">
                    <Badge variant="secondary" className="px-2 py-0.5 text-[10px]">
                      Suggested Actions
                    </Badge>
                  </div>

                  <div className="flex flex-wrap gap-1.5 sm:gap-2">
                    <TooltipProvider>
                      {message.actions.map((action, index) => {
                        const actionLabel = getActionLabel(action);

                        return (
                          <Tooltip key={`${action.type || 'action'}-${index}`}>
                            <TooltipTrigger asChild>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => onActionClick?.(action)}
                                className="group h-7 rounded-full bg-background/50 px-2 text-[10px] shadow-sm transition-all duration-300 hover:border-primary/30 hover:bg-primary/10 hover:text-primary sm:h-8 sm:px-3 sm:text-[11px]"
                                aria-label={`Perform action: ${actionLabel}`}
                              >
                                <PlusCircle
                                  className="mr-1 h-2.5 w-2.5 text-primary/60 transition-colors group-hover:text-primary sm:mr-1.5 sm:h-3 sm:w-3"
                                  aria-hidden="true"
                                />
                                <span className="max-w-[120px] truncate sm:max-w-none">
                                  {actionLabel}
                                </span>
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="max-w-xs">
                              <p className="text-sm">
                                {action.description || `Execute ${action.type} action`}
                              </p>
                            </TooltipContent>
                          </Tooltip>
                        );
                      })}
                    </TooltipProvider>
                  </div>
                </div>
              )}

              {message.imageDataUri && (
                <div className="mt-2 overflow-hidden rounded-xl border border-border/50 shadow-sm transition-transform duration-300 hover:scale-[1.01]">
                  <Image
                    src={message.imageDataUri}
                    alt="Generated by Karen"
                    width={400}
                    height={400}
                    className="h-auto w-full object-cover"
                  />
                </div>
              )}
            </div>

            {isAssistant && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="ml-2 h-7 w-7 shrink-0 text-muted-foreground opacity-40 transition-opacity hover:text-primary hover:opacity-100"
                      aria-label="Play message audio"
                      disabled
                    >
                      <Speaker className="h-4 w-4" aria-hidden="true" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>TTS disabled: Backend removed.</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>

          <div
            className={`mt-2 flex flex-wrap items-center gap-2 border-t border-border/10 pt-2 sm:mt-3 sm:gap-3 ${
              isUser ? 'justify-end' : 'justify-between'
            }`}
          >
            {isAssistant && (
              <div className="flex origin-left scale-90 items-center gap-0.5 sm:scale-100 sm:gap-1">
                <button
                  type="button"
                  onClick={() => void handleFeedback('up')}
                  className={`rounded-md p-1 transition-all hover:bg-muted ${
                    feedback === 'up'
                      ? 'bg-emerald-500/10 text-emerald-500'
                      : 'text-muted-foreground'
                  } ${
                    feedbackSubmitted && feedback === 'up' ? 'animate-pulse' : ''
                  }`}
                  aria-label={
                    feedbackSubmitted && feedback === 'up'
                      ? 'Feedback submitted'
                      : 'Rate response positively'
                  }
                  aria-pressed={feedback === 'up'}
                  title="Thumbs Up"
                  disabled={feedbackSubmitted}
                >
                  <ThumbsUp
                    className={`h-3.5 w-3.5 ${
                      feedback === 'up' ? 'fill-current' : ''
                    }`}
                    aria-hidden="true"
                  />
                </button>

                <button
                  type="button"
                  onClick={() => void handleFeedback('down')}
                  className={`rounded-md p-1 transition-all hover:bg-muted ${
                    feedback === 'down'
                      ? 'bg-rose-500/10 text-rose-500'
                      : 'text-muted-foreground'
                  } ${
                    feedbackSubmitted && feedback === 'down' ? 'animate-pulse' : ''
                  }`}
                  aria-label={
                    feedbackSubmitted && feedback === 'down'
                      ? 'Feedback submitted'
                      : 'Rate response negatively'
                  }
                  aria-pressed={feedback === 'down'}
                  title="Thumbs Down"
                  disabled={feedbackSubmitted}
                >
                  <ThumbsDown
                    className={`h-3.5 w-3.5 ${
                      feedback === 'down' ? 'fill-current' : ''
                    }`}
                    aria-hidden="true"
                  />
                </button>

                <button
                  type="button"
                  onClick={() => void handleCopy()}
                  className={`ml-1 flex items-center gap-1 rounded-md p-1 transition-all hover:bg-muted ${
                    copied
                      ? 'bg-emerald-500/10 text-emerald-500'
                      : 'text-muted-foreground'
                  }`}
                  aria-label={
                    copied
                      ? 'Response copied to clipboard'
                      : 'Copy response to clipboard'
                  }
                  title="Copy to clipboard"
                >
                  {copied ? (
                    <Check className="h-3.5 w-3.5" aria-hidden="true" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {copied && <span className="text-[10px] font-bold">Copied!</span>}
                </button>
              </div>
            )}

            {isUser && (
              <button
                type="button"
                onClick={() => void handleCopy()}
                className={`mr-1 flex origin-right scale-90 items-center gap-1 rounded-md p-1 transition-all hover:bg-primary-foreground/10 ${
                  copied
                    ? 'bg-white/10 text-white'
                    : 'text-primary-foreground/60'
                }`}
                aria-label={
                  copied
                    ? 'Message copied to clipboard'
                    : 'Copy your message to clipboard'
                }
                title="Copy your message"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                )}
              </button>
            )}

            <p
              className={`text-[10px] font-medium tracking-tight ${
                isUser
                  ? 'text-primary-foreground/60'
                  : 'text-muted-foreground/70'
              }`}
            >
              {timestampLabel}
            </p>
          </div>
        </CardContent>
      </Card>

      {isUser && (
        <Avatar className="flex h-10 w-10 shrink-0 items-center justify-center self-start rounded-full bg-muted shadow-sm ring-2 ring-primary/20">
          <User className="h-5 w-5 text-secondary" aria-hidden="true" />
        </Avatar>
      )}
    </div>
  );
}
