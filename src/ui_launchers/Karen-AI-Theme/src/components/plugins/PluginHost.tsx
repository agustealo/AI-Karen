'use client';

/**
 * PluginHost — renders a plugin UI component by plugin ID.
 *
 * Frontend loading authority:
 * - Component resolution belongs to plugin_host/loader.
 * - Mount state belongs to plugin_host/registry.
 * - This component does not hardcode import maps or plugin component paths.
 *
 * Requirements: 3.1, 3.2, 3.3, 3.4, 7.1, 7.2, 7.3, 7.4, 7.5, 9.3, 9.4, 29, 30
 */

import React, {
  Suspense,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';

import {
  getRegisteredPluginIds,
  normalizePluginId,
  resolvePluginComponentAsync,
} from '../../plugin_host/loader';
import { PluginErrorBoundary } from '../../plugin_host/PluginErrorBoundary';
import { setPluginMountState } from '../../plugin_host/registry';

export interface PluginHostProps {
  pluginId: string;
  fallback?: React.ReactNode;
  /** Host-supplied data only; plugin components cannot use this as an ACL grant. */
  componentProps?: Record<string, unknown>;
}

type LoadedPluginComponent =
  React.LazyExoticComponent<React.ComponentType<Record<string, unknown>>>;

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const isPluginRegistered = (normalizedId: string): boolean => {
  return getRegisteredPluginIds()
    .map((id) => normalizePluginId(id))
    .includes(normalizedId);
};

function PluginLoadingFallback({
  pluginId,
  fallback,
}: {
  pluginId: string;
  fallback?: React.ReactNode;
}) {
  if (fallback) {
    return <>{fallback}</>;
  }

  return (
    <div
      className="flex flex-col items-center justify-center space-y-4 p-12"
      role="status"
      aria-live="polite"
    >
      <Loader2
        className="h-8 w-8 animate-spin text-primary opacity-50"
        aria-hidden="true"
      />
      <p className="animate-pulse text-xs text-muted-foreground">
        Loading {pluginId} UI module…
      </p>
    </div>
  );
}

function PluginUnavailableState({
  normalizedId,
  isRegistered,
}: {
  normalizedId: string;
  isRegistered: boolean;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 rounded-lg border bg-destructive/5 p-8 text-center text-sm text-destructive"
      role="alert"
      aria-live="polite"
    >
      <AlertCircle className="h-5 w-5" aria-hidden="true" />

      <p>
        No UI registered for plugin{' '}
        <span className="font-mono font-bold">{normalizedId}</span>.
      </p>

      <p className="text-xs italic opacity-70">
        {isRegistered
          ? 'Plugin is installed, but its UI component could not be resolved. Check the plugin manifest and generated import map.'
          : 'Install the plugin UI first from the plugin overview page.'}
      </p>
    </div>
  );
}

export function PluginHost({ pluginId, fallback, componentProps }: PluginHostProps) {
  const normalizedId = useMemo(
    () => normalizePluginId(cleanString(pluginId)),
    [pluginId],
  );

  const [pluginComponent, setPluginComponent] =
    useState<LoadedPluginComponent | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [resolutionFailed, setResolutionFailed] = useState(false);

  const isRegistered = useMemo(
    () => isPluginRegistered(normalizedId),
    [normalizedId],
  );

  useEffect(() => {
    let cancelled = false;

    const loadPlugin = async () => {
      setIsLoading(true);
      setResolutionFailed(false);
      setPluginComponent(null);

      if (!normalizedId) {
        setPluginMountState(pluginId, 'uninstalled');
        setIsLoading(false);
        setResolutionFailed(true);
        return;
      }

      /*
       * PluginHost delegates resolution to the loader. Do not add local dynamic
       * imports here, or the UI grows a second plugin registry by accident.
       */
      try {
        setPluginMountState(pluginId, 'loading');

        const component = await resolvePluginComponentAsync(normalizedId);

        if (cancelled) {
          return;
        }

        if (component) {
          setPluginComponent(component);
          setPluginMountState(pluginId, 'loading');
        } else {
          setPluginComponent(null);
          setResolutionFailed(true);
          setPluginMountState(pluginId, 'uninstalled');
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        setPluginComponent(null);
        setResolutionFailed(true);
        setPluginMountState(pluginId, 'error');

        if (process.env.NODE_ENV !== 'production') {
          console.warn(`Failed to resolve plugin ${normalizedId}:`, error);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void loadPlugin();

    return () => {
      cancelled = true;
    };
  }, [normalizedId, pluginId]);

  if (isLoading) {
    return (
      <PluginLoadingFallback
        pluginId={normalizedId || pluginId}
        fallback={fallback}
      />
    );
  }

  if (!pluginComponent || resolutionFailed) {
    return (
      <PluginUnavailableState
        normalizedId={normalizedId || pluginId}
        isRegistered={isRegistered}
      />
    );
  }

  return (
    <Suspense
      fallback={
        <PluginLoadingFallback
          pluginId={normalizedId || pluginId}
          fallback={fallback}
        />
      }
    >
      <PluginErrorBoundary pluginId={pluginId}>
        <PluginMountTracker pluginId={pluginId}>
          {React.createElement(pluginComponent, componentProps ?? {})}
        </PluginMountTracker>
      </PluginErrorBoundary>
    </Suspense>
  );
}

/**
 * Marks a plugin UI as mounted after React successfully renders its lazy
 * component. On unmount we return to idle, not not_registered: unmounting means
 * the UI left the page, not that the plugin disappeared from the import map.
 */
function PluginMountTracker({
  pluginId,
  children,
}: {
  pluginId: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    setPluginMountState(pluginId, 'mounted');

    return () => {
      setPluginMountState(pluginId, 'idle');
    };
  }, [pluginId]);

  return <>{children}</>;
}
