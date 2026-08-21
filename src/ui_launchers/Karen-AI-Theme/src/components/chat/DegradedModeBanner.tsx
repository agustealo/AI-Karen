'use client';

import React from 'react';

interface DegradedModeBannerProps {
  reason: string;
  fallbackPath?: string;
  onDismiss?: () => void;
}

const DEFAULT_DEGRADED_REASON =
  'No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

export default function DegradedModeBanner({
  reason,
  fallbackPath,
  onDismiss,
}: DegradedModeBannerProps) {
  const safeReason = cleanString(reason) || DEFAULT_DEGRADED_REASON;
  const safeFallbackPath = cleanString(fallbackPath);

  /*
   * This banner is runtime-status display only.
   * Provider routing, fallback order, and degraded/live/static truth must come
   * from backend metadata, not from UI inference.
   */
  return (
    <div
      role="status"
      aria-live="polite"
      className="mb-4 w-full rounded-r-lg border-l-4 border-amber-500 bg-amber-50 p-4 dark:bg-amber-900/20"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-1 items-start gap-3">
          <svg
            className="h-5 w-5 flex-shrink-0 text-amber-600 dark:text-amber-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
            />
          </svg>

          <div className="flex flex-col">
            <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
              System operating in degraded mode
            </p>

            <p className="mt-0.5 text-xs text-amber-700 dark:text-amber-300">
              {safeReason}
            </p>

            {safeFallbackPath && (
              <p className="mt-0.5 text-xs text-amber-600 dark:text-amber-400">
                Fallback path: {safeFallbackPath}
              </p>
            )}
          </div>
        </div>

        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="flex-shrink-0 rounded p-1 transition-colors hover:bg-amber-100 dark:hover:bg-amber-800/30"
            aria-label="Dismiss degraded mode notification"
          >
            <svg
              className="h-4 w-4 text-amber-600 dark:text-amber-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18 18 6M6 6l12 12"
              />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
