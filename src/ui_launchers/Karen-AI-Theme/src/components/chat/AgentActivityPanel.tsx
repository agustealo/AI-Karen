'use client';

import React, { useId, useMemo, useState } from 'react';
import type { AgentStepEvent } from '@/lib/types';

interface AgentActivityPanelProps {
  steps: AgentStepEvent[];
}

type ActionIconMap = Record<string, React.ReactNode>;

type AgentStepMetadata = Record<string, unknown>;

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const stringifyMetadataValue = (value: unknown): string => {
  if (typeof value === 'string') {
    return value;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  if (value == null) {
    return '';
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const getSafeTimestamp = (timestamp: unknown): string => {
  if (!timestamp) {
    return '';
  }

  const date = new Date(
    typeof timestamp === 'string' || typeof timestamp === 'number'
      ? timestamp
      : String(timestamp),
  );

  if (Number.isNaN(date.getTime())) {
    return '';
  }

  return date.toLocaleTimeString();
};

const getActionLabel = (type: string): string => {
  switch (type) {
    case 'agent_step_started':
      return 'Processing';
    case 'agent_step_completed':
      return 'Completed';
    case 'agent_step_failed':
      return 'Failed';
    case 'agent_step_skipped':
      return 'Skipped';
    case 'tool_execution_started':
      return 'Executing tool';
    case 'tool_execution_completed':
      return 'Tool complete';
    case 'web_search_started':
      return 'Searching web';
    case 'web_search_sources_found':
      return 'Sources found';
    case 'extension_execution_started':
      return 'Running extension';
    case 'extension_execution_completed':
      return 'Extension complete';
    case 'citation_bundle_ready':
      return 'Citations ready';
    case 'degraded_mode_entered':
      return 'Degraded mode';
    case 'provider_selection_started':
      return 'Selecting provider';
    case 'provider_selected':
      return 'Provider selected';
    case 'provider_fallback_started':
      return 'Trying fallback';
    case 'provider_fallback_succeeded':
      return 'Fallback succeeded';
    case 'provider_invocation_failed':
      return 'Provider failed';
    case 'streaming_started':
      return 'Streaming started';
    case 'streaming_completed':
      return 'Streaming complete';
    default:
      return type.replace(/_/g, ' ');
  }
};

const actionIcons: ActionIconMap = {
  agent_step_started: (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
    </svg>
  ),
  agent_step_completed: (
    <svg className="h-4 w-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  ),
  agent_step_failed: (
    <svg className="h-4 w-4 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  ),
  agent_step_skipped: (
    <svg className="h-4 w-4 text-gray-500 dark:text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14" />
    </svg>
  ),
  tool_execution_started: (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  tool_execution_completed: (
    <svg className="h-4 w-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  ),
  web_search_started: (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.5 18a7.5 7.5 0 110-15 7.5 7.5 0 010 15z" />
    </svg>
  ),
  web_search_sources_found: (
    <svg className="h-4 w-4 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
    </svg>
  ),
  extension_execution_started: (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-5" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4.5 4.5 1.5-6L18.5 2.5z" />
    </svg>
  ),
  extension_execution_completed: (
    <svg className="h-4 w-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4" />
    </svg>
  ),
  citation_bundle_ready: (
    <svg className="h-4 w-4 text-purple-600 dark:text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
    </svg>
  ),
  degraded_mode_entered: (
    <svg className="h-4 w-4 text-yellow-600 dark:text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
    </svg>
  ),
  provider_invocation_failed: (
    <svg className="h-4 w-4 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12A9 9 0 113 12a9 9 0 0118 0z" />
    </svg>
  ),
  provider_fallback_succeeded: (
    <svg className="h-4 w-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v6h6M20 20v-6h-6" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 19A9 9 0 0119 5" />
    </svg>
  ),
  streaming_started: (
    <svg className="h-4 w-4 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7h16M4 12h10M4 17h16" />
    </svg>
  ),
  streaming_completed: (
    <svg className="h-4 w-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4" />
    </svg>
  ),
};

const renderMetadataLine = (
  label: string,
  value: unknown,
  className: string,
): React.ReactNode | null => {
  const text = stringifyMetadataValue(value);

  if (!text) {
    return null;
  }

  return (
    <p className={className}>
      {label}: {text}
    </p>
  );
};

const renderToolInfo = (
  metadata?: AgentStepMetadata,
): React.ReactNode | null => {
  return renderMetadataLine(
    'Tool',
    metadata?.tool,
    'text-xs text-blue-600 dark:text-blue-400',
  );
};

const renderExtensionInfo = (
  metadata?: AgentStepMetadata,
): React.ReactNode | null => {
  return renderMetadataLine(
    'Extension',
    metadata?.extension_id,
    'text-xs text-purple-600 dark:text-purple-400',
  );
};

const renderProviderInfo = (
  metadata?: AgentStepMetadata,
): React.ReactNode | null => {
  const provider =
    metadata?.actual_provider ??
    metadata?.provider ??
    metadata?.requested_provider;

  return renderMetadataLine(
    'Provider',
    provider,
    'text-xs text-emerald-700 dark:text-emerald-400',
  );
};

const renderFallbackInfo = (
  metadata?: AgentStepMetadata,
): React.ReactNode | null => {
  return renderMetadataLine(
    'Fallback',
    metadata?.fallback_reason ?? metadata?.degradation_reason,
    'text-xs text-yellow-700 dark:text-yellow-400',
  );
};

export default function AgentActivityPanel({ steps }: AgentActivityPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const panelContentId = useId();

  const normalizedSteps = useMemo(() => {
    return Array.isArray(steps) ? steps.filter(Boolean) : [];
  }, [steps]);

  if (normalizedSteps.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <button
        type="button"
        onClick={() => setIsExpanded((current) => !current)}
        className="flex w-full items-center justify-between border-b border-gray-200 p-3 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-750"
        aria-expanded={isExpanded}
        aria-controls={panelContentId}
      >
        <div className="flex items-center gap-2">
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2h2a2 2 0 002-2z" />
          </svg>

          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            Agent Activity ({normalizedSteps.length})
          </span>
        </div>

        <svg
          className={`h-4 w-4 transform transition-transform ${
            isExpanded ? 'rotate-180' : ''
          }`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isExpanded && (
        <div
          id={panelContentId}
          className="max-h-64 space-y-2 overflow-y-auto p-2"
          /*
           * This panel is observability UI only. It must display backend events,
           * not infer provider routing or invent fallback truth.
           */
          aria-live="polite"
        >
          {normalizedSteps.map((step, index) => {
            const metadata =
              step.metadata && typeof step.metadata === 'object'
                ? (step.metadata as AgentStepMetadata)
                : undefined;
            const timestamp = getSafeTimestamp(step.timestamp);
            const icon = actionIcons[step.type] || actionIcons.agent_step_started;

            return (
              <div
                key={`${step.step_id || step.type || 'step'}-${index}`}
                className="flex items-start gap-3 rounded-md bg-gray-50 p-2 transition-colors hover:bg-gray-100 dark:bg-gray-750 dark:hover:bg-gray-700"
              >
                <span className="mt-0.5 flex-shrink-0">{icon}</span>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      {getActionLabel(cleanString(step.type) || 'agent_step_started')}
                    </span>

                    {timestamp && (
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {timestamp}
                      </span>
                    )}
                  </div>

                  {typeof step.action_type === 'string' && step.action_type.trim() && (
                    <p className="text-xs text-gray-600 dark:text-gray-400">
                      {step.action_type}
                    </p>
                  )}

                  {renderToolInfo(metadata)}
                  {renderExtensionInfo(metadata)}
                  {renderProviderInfo(metadata)}
                  {renderFallbackInfo(metadata)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}