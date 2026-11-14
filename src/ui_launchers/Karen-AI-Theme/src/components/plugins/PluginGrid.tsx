import React, { useMemo } from 'react';
import { ChevronLeft, ChevronRight, Loader2, Package } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { Plugin } from '@/types/plugin';

import { PluginCard } from './PluginCard';

interface PluginGridProps {
  plugins: Plugin[];
  loading: boolean;
  total?: number;
  page?: number;
  perPage?: number;
  totalPages?: number;
  hasNext?: boolean;
  hasPrev?: boolean;
  onPageChange?: (page: number) => void;
  onInstall?: (pluginId: string, version?: string) => void;
  onDisable?: (pluginId: string) => void;
  onDetails?: (pluginId: string) => void;
  onDiscover?: (pluginId: string) => void;
  installingPlugins?: Set<string>;
  emptyMessage?: string;
  className?: string;
}

const MAX_VISIBLE_PAGE_BUTTONS = 5;

const clampNumber = (value: unknown, fallback: number): number => {
  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.max(0, Math.floor(parsed));
};

const clampPage = (page: number, totalPages: number): number => {
  if (totalPages <= 0) {
    return 1;
  }

  return Math.min(Math.max(1, page), totalPages);
};

const getVisiblePages = (currentPage: number, totalPages: number): number[] => {
  if (totalPages <= 0) {
    return [];
  }

  const visibleCount = Math.min(MAX_VISIBLE_PAGE_BUTTONS, totalPages);

  if (totalPages <= MAX_VISIBLE_PAGE_BUTTONS) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  let startPage = currentPage - Math.floor(visibleCount / 2);
  let endPage = startPage + visibleCount - 1;

  if (startPage < 1) {
    startPage = 1;
    endPage = visibleCount;
  }

  if (endPage > totalPages) {
    endPage = totalPages;
    startPage = totalPages - visibleCount + 1;
  }

  return Array.from(
    { length: endPage - startPage + 1 },
    (_, index) => startPage + index,
  );
};

export function PluginGrid({
  plugins,
  loading,
  total = 0,
  page = 1,
  perPage = 20,
  totalPages = 0,
  hasNext = false,
  hasPrev = false,
  onPageChange,
  onInstall,
  onDisable,
  onDetails,
  onDiscover,
  installingPlugins = new Set(),
  emptyMessage = 'No plugins found',
  className = '',
}: PluginGridProps) {
  const safePlugins = Array.isArray(plugins) ? plugins : [];
  const safeTotal = clampNumber(total, safePlugins.length);
  const safePerPage = Math.max(1, clampNumber(perPage, 20));
  const safeTotalPages =
    totalPages > 0
      ? clampNumber(totalPages, 0)
      : safeTotal > 0
        ? Math.ceil(safeTotal / safePerPage)
        : 0;
  const safePage = clampPage(clampNumber(page, 1), safeTotalPages);

  const visiblePages = useMemo(
    () => getVisiblePages(safePage, safeTotalPages),
    [safePage, safeTotalPages],
  );

  const startItem = safeTotal === 0 ? 0 : (safePage - 1) * safePerPage + 1;
  const endItem = Math.min(safePage * safePerPage, safeTotal);

  const canPagePrev = Boolean(onPageChange) && hasPrev && safePage > 1;
  const canPageNext =
    Boolean(onPageChange) && hasNext && safeTotalPages > 0 && safePage < safeTotalPages;

  /*
   * PluginGrid displays a paged plugin result set owned by the backend or
   * marketplace query layer. It should not infer installability or lifecycle
   * state beyond passing registry data down to PluginCard.
   */
  return (
    <div className={`flex flex-col gap-6 ${className}`.trim()}>
      {loading && safePlugins.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center py-12"
          role="status"
          aria-live="polite"
        >
          <Loader2
            className="mb-4 h-8 w-8 animate-spin text-primary"
            aria-hidden="true"
          />
          <p className="text-sm text-muted-foreground">Loading plugins...</p>
        </div>
      ) : safePlugins.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-12">
          <Package
            className="mb-4 h-12 w-12 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="text-sm text-muted-foreground">{emptyMessage}</p>
        </div>
      ) : (
        <>
          <div
            className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3"
            aria-label="Plugin results"
          >
            {safePlugins.map((plugin) => (
              <PluginCard
                key={plugin.id}
                plugin={plugin}
                onInstall={onInstall}
                onDisable={onDisable}
                onDetails={onDetails}
                onDiscover={onDiscover}
                loading={installingPlugins.has(plugin.id)}
              />
            ))}
          </div>

          {safeTotalPages > 1 && (
            <div className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm text-muted-foreground">
                Showing {startItem} to {endItem} of {safeTotal} plugins
              </div>

              <nav
                className="flex flex-wrap items-center gap-2"
                aria-label="Plugin pagination"
              >
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onPageChange?.(safePage - 1)}
                  disabled={!canPagePrev}
                  aria-label="Go to previous plugin page"
                >
                  <ChevronLeft className="mr-1 h-4 w-4" aria-hidden="true" />
                  Previous
                </Button>

                <div className="flex items-center gap-1">
                  {visiblePages.map((pageNumber) => (
                    <Button
                      key={pageNumber}
                      type="button"
                      variant={safePage === pageNumber ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => onPageChange?.(pageNumber)}
                      className="h-8 w-8 p-0"
                      aria-label={`Go to plugin page ${pageNumber}`}
                      aria-current={safePage === pageNumber ? 'page' : undefined}
                      disabled={!onPageChange}
                    >
                      {pageNumber}
                    </Button>
                  ))}
                </div>

                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onPageChange?.(safePage + 1)}
                  disabled={!canPageNext}
                  aria-label="Go to next plugin page"
                >
                  Next
                  <ChevronRight className="ml-1 h-4 w-4" aria-hidden="true" />
                </Button>
              </nav>
            </div>
          )}
        </>
      )}
    </div>
  );
}