'use client';

import React, { useId, useMemo, useState } from 'react';
import type { Citation } from '@/lib/types';

interface SourceListProps {
  citations?: Citation[];
}

const DEFAULT_SOURCE_TITLE = 'Untitled source';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const stringifyValue = (value: unknown): string => {
  if (typeof value === 'string') {
    return value.trim();
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

const getSafeUrl = (value: unknown): string => {
  const rawUrl = cleanString(value);

  if (!rawUrl) {
    return '';
  }

  try {
    const parsed = new URL(rawUrl);

    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.toString();
    }
  } catch {
    return '';
  }

  return '';
};

const getCitationDomain = (citation: Citation): string => {
  const metadataDomain =
    citation.metadata && typeof citation.metadata.domain === 'string'
      ? citation.metadata.domain
      : '';

  if (metadataDomain.trim()) {
    return metadataDomain.trim();
  }

  const safeUrl = getSafeUrl(citation.url);

  if (!safeUrl) {
    return '';
  }

  try {
    return new URL(safeUrl).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
};

const getCitationKey = (citation: Citation, index: number): string => {
  const explicitId = cleanString(citation.id);
  const safeUrl = getSafeUrl(citation.url);
  const title = cleanString(citation.title);

  return explicitId || safeUrl || `${title || DEFAULT_SOURCE_TITLE}-${index}`;
};

const getSourceCountLabel = (count: number): string => {
  return `${count} source${count === 1 ? '' : 's'}`;
};

export default function SourceList({ citations }: SourceListProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const contentId = useId();

  const safeCitations = useMemo(() => {
    return Array.isArray(citations) ? citations.filter(Boolean) : [];
  }, [citations]);

  if (safeCitations.length === 0) {
    return null;
  }

  const sourceCountLabel = getSourceCountLabel(safeCitations.length);

  /*
   * SourceList renders citations that are already attached to the message.
   * It must not fetch, enrich, deduplicate, or invent sources in the UI layer.
   */
  return (
    <div data-testid="chat-source-list" className="mt-4 border-t border-gray-200 pt-3 dark:border-gray-700">
      <button
        type="button"
        onClick={() => setIsExpanded((current) => !current)}
        className="flex items-center gap-2 text-sm text-gray-600 transition-colors hover:text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 dark:text-gray-400 dark:hover:text-gray-200"
        aria-expanded={isExpanded}
        aria-controls={contentId}
        aria-label={isExpanded ? `Hide ${sourceCountLabel}` : `Show ${sourceCountLabel}`}
      >
        <svg
          className={`h-4 w-4 transform transition-transform ${
            isExpanded ? 'rotate-180' : ''
          }`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>

        <span>Sources ({safeCitations.length})</span>
      </button>

      {isExpanded && (
        <div id={contentId} className="mt-2 space-y-2">
          {safeCitations.map((citation, index) => {
            const sourceNumber = index + 1;
            const title = cleanString(citation.title) || DEFAULT_SOURCE_TITLE;
            const snippet = stringifyValue(citation.snippet);
            const safeUrl = getSafeUrl(citation.url);
            const domain = getCitationDomain(citation);

            return (
              <div
                key={getCitationKey(citation, index)}
                className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800"
              >
                <div className="flex items-start gap-2">
                  <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-300">
                    {sourceNumber}
                  </span>

                  <div className="min-w-0 flex-1">
                    {safeUrl ? (
                      <a
                        href={safeUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block truncate text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                        title={title}
                      >
                        {title}
                      </a>
                    ) : (
                      <span
                        className="block truncate text-sm font-medium text-gray-700 dark:text-gray-300"
                        title={title}
                      >
                        {title}
                      </span>
                    )}

                    {snippet && (
                      <p className="mt-1 line-clamp-2 text-xs text-gray-600 dark:text-gray-400">
                        {snippet}
                      </p>
                    )}

                    {domain && (
                      <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">
                        {domain}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}