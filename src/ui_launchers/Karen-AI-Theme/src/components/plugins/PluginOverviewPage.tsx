'use client';

/**
 * @file PluginOverviewPage.tsx
 * @description Displays Karen AI plugin health, backend lifecycle state,
 * frontend mount/registration state, and governed UI install controls.
 *
 * Architecture boundary:
 * - Backend plugin state comes from the extension/plugin runtime.
 * - Frontend registration state comes from the plugin host loader/registry.
 * - This page displays and invokes lifecycle actions only. It does not invent
 *   plugin capabilities, bypass RBAC, or execute plugin logic directly.
 *
 * Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4
 */

import React, { useCallback, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  EyeOff,
  Github,
  HelpCircle,
  Info,
  Loader2,
  MessageSquare,
  PlugZap,
  Puzzle,
  RotateCcw,
  Settings2,
  Trash2,
  XCircle,
  Zap,
  type LucideIcon,
} from 'lucide-react';

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

import { apiClient } from '@/lib/api';
import {
  usePluginHealth,
  usePluginRegistry,
  type FrontendMountState,
} from '@/plugin_host/registry';
import {
  getRegisteredPluginIds,
  normalizePluginId,
  refreshImportMap,
} from '@/plugin_host/loader';

type BackendState =
  | 'active'
  | 'error'
  | 'disabled'
  | 'broken'
  | 'uninstalled'
  | 'restorable'
  | 'validated'
  | 'discovered'
  | 'not_discovered'
  | string;

type BackendStatusDetail =
  | 'not_discovered'
  | 'discovered'
  | 'validated'
  | 'installed'
  | 'enabled'
  | 'disabled'
  | 'broken'
  | 'uninstalled'
  | 'restorable';

type UIInstallStatus =
  | 'not_installed'
  | 'installed'
  | 'removing'
  | 'restoring'
  | 'error'
  | 'installing';

type UIRegistrationStatus =
  | 'not_registered'
  | 'registered'
  | 'mountable'
  | 'mount_error';

type PluginOperation =
  | 'install-ui'
  | 'remove-ui'
  | 'restore-ui'
  | 'retry-registration'
  | 'enable-plugin'
  | 'disable-plugin';

type PluginOperationResult = {
  success: boolean;
  message?: string;
  [key: string]: unknown;
};

type BadgeConfig = {
  icon: LucideIcon;
  color: string;
  label: string;
};

type PluginHealthCardProps = {
  pluginId: string;
  displayName: string;
  description: string;
  version: string;
};

type OperationOverrideState = {
  uiInstallStatus?: UIInstallStatus;
  uiRegistrationStatus?: UIRegistrationStatus;
  backendStatusDetail?: BackendStatusDetail;
};

const EXTENSIONS_INSTALL_ENDPOINT = '/api/extensions/install';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const getErrorMessage = (
  error: unknown,
  fallback = 'Plugin operation failed.',
): string => {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }

  if (typeof error === 'string' && error.trim()) {
    return error.trim();
  }

  return fallback;
};

const getNormalizedRegisteredPluginIds = (): string[] => {
  return getRegisteredPluginIds().map((id) => normalizePluginId(id));
};

const isPluginUiRegistered = (pluginId: string): boolean => {
  const normalizedId = normalizePluginId(pluginId);
  return getNormalizedRegisteredPluginIds().includes(normalizedId);
};

const getBackendBadgeConfig = (state: BackendState): BadgeConfig => {
  switch (state) {
    case 'active':
      return {
        icon: CheckCircle2,
        color: 'text-green-600 dark:text-green-400',
        label: 'active',
      };

    case 'error':
      return {
        icon: XCircle,
        color: 'text-destructive',
        label: 'error',
      };

    case 'disabled':
      return {
        icon: XCircle,
        color: 'text-amber-600 dark:text-amber-400',
        label: 'disabled',
      };

    case 'broken':
      return {
        icon: Zap,
        color: 'text-orange-600 dark:text-orange-400',
        label: 'broken',
      };

    case 'uninstalled':
      return {
        icon: Trash2,
        color: 'text-muted-foreground',
        label: 'uninstalled',
      };

    case 'restorable':
      return {
        icon: RotateCcw,
        color: 'text-purple-600 dark:text-purple-400',
        label: 'restorable',
      };

    case 'validated':
      return {
        icon: CheckCircle2,
        color: 'text-blue-600 dark:text-blue-400',
        label: 'validated',
      };

    case 'discovered':
      return {
        icon: Github,
        color: 'text-gray-600 dark:text-gray-400',
        label: 'discovered',
      };

    case 'not_discovered':
      return {
        icon: HelpCircle,
        color: 'text-muted-foreground',
        label: 'not discovered',
      };

    default:
      return {
        icon: AlertTriangle,
        color: 'text-muted-foreground',
        label: cleanString(state) || 'unknown',
      };
  }
};

const deriveBackendStatusDetail = (
  backendState: BackendState,
): BackendStatusDetail => {
  switch (backendState) {
    case 'active':
      return 'enabled';

    case 'error':
    case 'broken':
      return 'broken';

    case 'disabled':
      return 'disabled';

    case 'uninstalled':
      return 'uninstalled';

    case 'restorable':
      return 'restorable';

    case 'validated':
      return 'validated';

    case 'not_discovered':
      return 'not_discovered';

    case 'discovered':
    default:
      return 'discovered';
  }
};

const deriveUiInstallStatus = (backendState: BackendState): UIInstallStatus => {
  switch (backendState) {
    case 'active':
    case 'disabled':
    case 'validated':
      return 'installed';

    case 'error':
    case 'broken':
      return 'error';

    case 'uninstalled':
    case 'not_discovered':
    case 'discovered':
    case 'restorable':
    default:
      return 'not_installed';
  }
};

const deriveUiRegistrationStatus = ({
  hasUiCapabilities,
  isRegistered,
  frontendMountState,
}: {
  hasUiCapabilities: boolean;
  isRegistered: boolean;
  frontendMountState: FrontendMountState;
}): UIRegistrationStatus => {
  if (!hasUiCapabilities) {
    return 'not_registered';
  }

  if (frontendMountState === 'error') {
    return 'mount_error';
  }

  if (isRegistered) {
    return 'registered';
  }

  return 'not_registered';
};

const getFrontendDisplayState = ({
  frontendMountState,
  isRegistered,
}: {
  frontendMountState: FrontendMountState;
  isRegistered: boolean;
}): FrontendMountState | 'registered' => {
  return frontendMountState === 'idle' && isRegistered
    ? 'registered'
    : frontendMountState;
};

const parsePluginOperationResult = (
  value: unknown,
): PluginOperationResult => {
  if (value && typeof value === 'object') {
    const result = value as Record<string, unknown>;

    return {
      ...result,
      success: Boolean(result.success),
      message: cleanString(result.message),
    };
  }

  return {
    success: false,
    message: 'Plugin operation returned an invalid response.',
  };
};

const getOperationFailureMessage = (
  result: PluginOperationResult,
  fallback: string,
): string => {
  return cleanString(result.message) || fallback;
};

function BackendStateBadge({
  state,
  detail,
}: {
  state: BackendState;
  detail?: string;
}) {
  const config = getBackendBadgeConfig(state);
  const Icon = config.icon;
  const detailLabel = cleanString(detail);

  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <Icon className={`h-3 w-3 ${config.color}`} aria-hidden={true} />
      {detailLabel ? `${config.label} (${detailLabel})` : config.label}
    </span>
  );
}

function FrontendStateBadge({
  state,
}: {
  state: FrontendMountState | 'registered';
}) {
  switch (state) {
    case 'mounted':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
          <CheckCircle2 className="h-3 w-3" aria-hidden={true} /> mounted
        </span>
      );

    case 'registered':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
          <CheckCircle2 className="h-3 w-3" aria-hidden={true} /> registered
        </span>
      );

    case 'error':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-destructive">
          <XCircle className="h-3 w-3" aria-hidden={true} /> render error
        </span>
      );

    case 'idle':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <AlertTriangle className="h-3 w-3" aria-hidden={true} /> not registered
        </span>
      );

    default:
      return (
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" aria-hidden={true} /> loading
        </span>
      );
  }
}

function UIInstallStatusBadge({ status }: { status: UIInstallStatus }) {
  switch (status) {
    case 'installed':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
          <CheckCircle2 className="h-3 w-3" aria-hidden={true} /> installed
        </span>
      );

    case 'not_installed':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <AlertTriangle className="h-3 w-3" aria-hidden={true} /> not installed
        </span>
      );

    case 'removing':
      return (
        <span className="inline-flex animate-pulse items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
          <Trash2 className="h-3 w-3" aria-hidden={true} /> removing
        </span>
      );

    case 'restoring':
      return (
        <span className="inline-flex animate-pulse items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
          <RotateCcw className="h-3 w-3" aria-hidden={true} /> restoring
        </span>
      );

    case 'installing':
      return (
        <span className="inline-flex animate-pulse items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden={true} /> installing
        </span>
      );

    case 'error':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-destructive">
          <XCircle className="h-3 w-3" aria-hidden={true} /> error
        </span>
      );

    default:
      return (
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <HelpCircle className="h-3 w-3" aria-hidden={true} /> unknown
        </span>
      );
  }
}

function UIRegistrationStatusBadge({
  status,
}: {
  status: UIRegistrationStatus;
}) {
  switch (status) {
    case 'registered':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
          <CheckCircle2 className="h-3 w-3" aria-hidden={true} /> registered
        </span>
      );

    case 'mountable':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-3 w-3" aria-hidden={true} /> mountable
        </span>
      );

    case 'mount_error':
      return (
        <span className="inline-flex items-center gap-1 text-xs text-destructive">
          <XCircle className="h-3 w-3" aria-hidden={true} /> mount error
        </span>
      );

    case 'not_registered':
    default:
      return (
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <AlertTriangle className="h-3 w-3" aria-hidden={true} /> not registered
        </span>
      );
  }
}

function PluginHealthCard({
  pluginId,
  displayName,
  description,
  version,
}: PluginHealthCardProps) {
  const { refresh } = usePluginRegistry();
  const health = usePluginHealth(pluginId);

  const [operationInProgress, setOperationInProgress] =
    useState<PluginOperation | null>(null);
  const [operationError, setOperationError] = useState('');
  const [operationOverride, setOperationOverride] =
    useState<OperationOverrideState>({});

  const normalizedPluginId = useMemo(
    () => normalizePluginId(pluginId),
    [pluginId],
  );

  const isUiRegistered = useMemo(() => {
    /*
     * Registration comes from loader/import-map state. It is a read-only UI
     * signal here, not a substitute for backend lifecycle state.
     */
    return isPluginUiRegistered(normalizedPluginId);
  }, [normalizedPluginId]);

  const derivedBackendStatusDetail = useMemo(
    () => deriveBackendStatusDetail(health.backendState),
    [health.backendState],
  );

  const derivedUiInstallStatus = useMemo(
    () => deriveUiInstallStatus(health.backendState),
    [health.backendState],
  );

  const hasUiCapabilities = useMemo(() => {
    /*
     * UI capability should eventually come from plugin manifest/health metadata.
     * Until that contract exists, use only observable frontend/import-map state.
     */
    return (
      health.frontendMountState !== 'idle' ||
      isUiRegistered ||
      derivedUiInstallStatus === 'installed' ||
      operationOverride.uiInstallStatus === 'installed'
    );
  }, [
    derivedUiInstallStatus,
    health.frontendMountState,
    isUiRegistered,
    operationOverride.uiInstallStatus,
  ]);

  const derivedUiRegistrationStatus = useMemo(
    () =>
      deriveUiRegistrationStatus({
        hasUiCapabilities,
        isRegistered: isUiRegistered,
        frontendMountState: health.frontendMountState,
      }),
    [hasUiCapabilities, health.frontendMountState, isUiRegistered],
  );

  const backendStatusDetail =
    operationOverride.backendStatusDetail || derivedBackendStatusDetail;
  const uiInstallStatus =
    operationOverride.uiInstallStatus || derivedUiInstallStatus;
  const uiRegistrationStatus =
    operationOverride.uiRegistrationStatus || derivedUiRegistrationStatus;

  const frontendDisplayState = useMemo(
    () =>
      getFrontendDisplayState({
        frontendMountState: health.frontendMountState,
        isRegistered: isUiRegistered,
      }),
    [health.frontendMountState, isUiRegistered],
  );

  const isOperationInProgress = operationInProgress !== null;
  const isInstalling = operationInProgress === 'install-ui';
  const isRemoving = operationInProgress === 'remove-ui';
  const isRestoring = operationInProgress === 'restore-ui';
  const isRegistering = operationInProgress === 'retry-registration';
  const isEnabling = operationInProgress === 'enable-plugin';
  const isDisabling = operationInProgress === 'disable-plugin';

  const refreshPluginSurfaces = useCallback(async () => {
    await refreshImportMap();
    await refresh();

    return isPluginUiRegistered(normalizedPluginId);
  }, [normalizedPluginId, refresh]);

  const runOperation = useCallback(
    async (
      operation: PluginOperation,
      action: () => Promise<OperationOverrideState | void>,
    ): Promise<void> => {
      if (operationInProgress) {
        return;
      }

      setOperationInProgress(operation);
      setOperationError('');

      try {
        const nextOverride = await action();

        if (nextOverride) {
          setOperationOverride(nextOverride);
        }
      } catch (error) {
        setOperationError(getErrorMessage(error));
        setOperationOverride({
          uiInstallStatus: 'error',
          backendStatusDetail: 'broken',
        });
      } finally {
        setOperationInProgress(null);
      }
    },
    [operationInProgress],
  );

  const postPluginOperation = useCallback(
    async (
      endpoint: string,
      body?: Record<string, unknown>,
      failureMessage = `Plugin operation failed for ${pluginId}.`,
    ): Promise<PluginOperationResult> => {
      const rawResult = body
        ? await apiClient.post(endpoint, body)
        : await apiClient.post(endpoint);

      const result = parsePluginOperationResult(rawResult);

      if (!result.success) {
        throw new Error(getOperationFailureMessage(result, failureMessage));
      }

      return result;
    },
    [pluginId],
  );

  const handleInstallUI = useCallback(async () => {
    await runOperation('install-ui', async () => {
      setOperationOverride({
        uiInstallStatus: 'installing',
      });

      await postPluginOperation(
        EXTENSIONS_INSTALL_ENDPOINT,
        { plugin_id: pluginId },
        `Failed to install plugin UI for ${pluginId}.`,
      );

      const registeredAfterRefresh = await refreshPluginSurfaces();

      return {
        uiInstallStatus: 'installed',
        uiRegistrationStatus: registeredAfterRefresh ? 'registered' : 'mountable',
        backendStatusDetail: 'installed',
      };
    });
  }, [pluginId, postPluginOperation, refreshPluginSurfaces, runOperation]);

  const handleRemoveUI = useCallback(async () => {
    await runOperation('remove-ui', async () => {
      setOperationOverride({
        uiInstallStatus: 'removing',
      });

      await postPluginOperation(
        `/api/extensions/${pluginId}/remove-ui`,
        undefined,
        `Failed to remove plugin UI for ${pluginId}.`,
      );

      await refreshPluginSurfaces();

      return {
        uiInstallStatus: 'not_installed',
        uiRegistrationStatus: 'not_registered',
        backendStatusDetail: 'uninstalled',
      };
    });
  }, [pluginId, postPluginOperation, refreshPluginSurfaces, runOperation]);

  const handleRestoreUI = useCallback(async () => {
    await runOperation('restore-ui', async () => {
      setOperationOverride({
        uiInstallStatus: 'restoring',
      });

      /*
       * Current backend restore behavior is install-compatible.
       * Keep this explicit instead of inventing a separate UI restore route.
       */
      await postPluginOperation(
        EXTENSIONS_INSTALL_ENDPOINT,
        { plugin_id: pluginId },
        `Failed to restore plugin UI for ${pluginId}.`,
      );

      const registeredAfterRefresh = await refreshPluginSurfaces();

      return {
        uiInstallStatus: 'installed',
        uiRegistrationStatus: registeredAfterRefresh ? 'registered' : 'mountable',
        backendStatusDetail: 'installed',
      };
    });
  }, [pluginId, postPluginOperation, refreshPluginSurfaces, runOperation]);

  const handleRetryRegistration = useCallback(async () => {
    await runOperation('retry-registration', async () => {
      const registeredAfterRefresh = await refreshPluginSurfaces();

      return {
        uiRegistrationStatus: registeredAfterRefresh ? 'registered' : 'not_registered',
      };
    });
  }, [refreshPluginSurfaces, runOperation]);

  const handleEnablePlugin = useCallback(async () => {
    await runOperation('enable-plugin', async () => {
      await postPluginOperation(
        `/api/extensions/${pluginId}/load`,
        undefined,
        `Failed to enable plugin ${pluginId}.`,
      );

      const registeredAfterRefresh = await refreshPluginSurfaces();

      return {
        backendStatusDetail: 'enabled',
        uiInstallStatus: 'installed',
        uiRegistrationStatus: registeredAfterRefresh ? 'registered' : 'not_registered',
      };
    });
  }, [pluginId, postPluginOperation, refreshPluginSurfaces, runOperation]);

  const handleDisablePlugin = useCallback(async () => {
    await runOperation('disable-plugin', async () => {
      await postPluginOperation(
        `/api/extensions/${pluginId}/unload`,
        undefined,
        `Failed to disable plugin ${pluginId}.`,
      );

      const registeredAfterRefresh = await refreshPluginSurfaces();

      return {
        backendStatusDetail: 'disabled',
        uiInstallStatus: 'installed',
        uiRegistrationStatus: registeredAfterRefresh ? 'registered' : 'not_registered',
      };
    });
  }, [pluginId, postPluginOperation, refreshPluginSurfaces, runOperation]);

  return (
    <div className="space-y-3 rounded-lg border bg-muted/30 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold">
            {displayName}
            <span className="ml-2 text-xs font-normal opacity-50">v{version}</span>
          </h4>

          <p className="text-xs text-muted-foreground">
            {description || 'No description provided.'}
          </p>
        </div>

        {!health.permissionVisible && (
          <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
            <EyeOff className="h-3 w-3" aria-hidden={true} /> hidden
          </span>
        )}
      </div>

      <div className="grid gap-3 text-xs">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Backend:</span>
          <BackendStateBadge
            state={health.backendState}
            detail={backendStatusDetail}
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Frontend:</span>
          <FrontendStateBadge state={frontendDisplayState} />
        </div>

        {hasUiCapabilities && (
          <>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">UI Install:</span>
              <UIInstallStatusBadge status={uiInstallStatus} />
            </div>

            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">UI Reg:</span>
              <UIRegistrationStatusBadge status={uiRegistrationStatus} />
            </div>
          </>
        )}
      </div>

      {operationError && (
        <Alert variant="destructive" className="px-3 py-2">
          <XCircle className="h-3 w-3" aria-hidden={true} />
          <AlertDescription className="text-xs">{operationError}</AlertDescription>
        </Alert>
      )}

      {health.backendState === 'active' && health.frontendMountState === 'error' && (
        <Alert variant="destructive" className="px-3 py-2">
          <AlertTriangle className="h-3 w-3" aria-hidden={true} />
          <AlertDescription className="text-xs">
            Backend reports active but the UI component failed to render.
            {health.errorMessage && <> Error: {health.errorMessage}</>}
          </AlertDescription>
        </Alert>
      )}

      {hasUiCapabilities && uiInstallStatus === 'installed' && !isUiRegistered && (
        <Alert className="border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-700 dark:text-amber-300">
          <AlertTriangle className="h-3 w-3" aria-hidden={true} />
          <AlertDescription className="text-xs">
            UI installed but not registered. Retry registration to fix.
          </AlertDescription>
        </Alert>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {hasUiCapabilities && uiInstallStatus === 'installed' && health.backendState === 'active' && (
          <div className="flex items-center gap-2 text-xs text-green-600">
            <CheckCircle2 className="h-3 w-3" aria-hidden={true} />
            UI Mounted
          </div>
        )}

        {hasUiCapabilities && uiInstallStatus === 'installed' && health.backendState !== 'active' && (
          <div className="flex items-center gap-2 text-xs text-amber-600">
            <AlertTriangle className="h-3 w-3" aria-hidden={true} />
            UI Unmounted
          </div>
        )}

        {hasUiCapabilities && uiInstallStatus === 'installed' && !isUiRegistered && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleRetryRegistration()}
            disabled={isOperationInProgress}
          >
            {isRegistering ? 'Registering...' : 'Retry Registration'}
          </Button>
        )}

        {hasUiCapabilities && uiInstallStatus === 'not_installed' && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleInstallUI()}
            disabled={isOperationInProgress}
          >
            {isInstalling ? 'Installing...' : 'Install UI'}
          </Button>
        )}

        {health.backendState !== 'error' && (
          <>
            {health.backendState === 'active' && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void handleDisablePlugin()}
                disabled={isOperationInProgress}
              >
                {isDisabling ? 'Disabling...' : 'Disable'}
              </Button>
            )}

            {health.backendState !== 'active' && health.backendState !== 'error' && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void handleEnablePlugin()}
                disabled={isOperationInProgress}
              >
                {isEnabling ? 'Enabling...' : 'Enable'}
              </Button>
            )}
          </>
        )}

        {health.backendState !== 'uninstalled' && uiInstallStatus === 'installed' && (
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => void handleRemoveUI()}
            disabled={isOperationInProgress}
          >
            {isRemoving ? 'Uninstalling...' : 'Uninstall'}
          </Button>
        )}

        {health.backendState === 'uninstalled' && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleRestoreUI()}
            disabled={isOperationInProgress}
          >
            {isRestoring ? 'Restoring...' : 'Restore'}
          </Button>
        )}
      </div>
    </div>
  );
}

export default function PluginOverviewPage() {
  const { plugins, loading, error } = usePluginRegistry();

  return (
    <div className="space-y-8">
      <div className="flex items-center space-x-3">
        <PlugZap className="h-8 w-8 text-primary" aria-hidden={true} />

        <div>
          <h2 className="text-2xl font-semibold tracking-tight">
            Karen AI - Plugins & Tools Overview
          </h2>

          <p className="text-sm text-muted-foreground">
            Understanding Karen AI&apos;s capabilities and how she integrates new features.
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Current Plugin & Tool Integration</CardTitle>
          <CardDescription>
            Karen AI uses a &quot;prompt-first&quot; framework. Her core AI is
            instructed on how to use available tools and capabilities based on
            your conversational requests.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          <p className="text-sm">
            When you interact with Karen, her central AI decision-making flow
            determines whether a specialized tool is needed. If so, the governed
            runtime invokes the tool and crafts a response from the tool output.
          </p>

          <Alert>
            <MessageSquare className="h-4 w-4" aria-hidden={true} />
            <AlertTitle>Interaction Method</AlertTitle>
            <AlertDescription>
              Most tools are used by Karen when you ask relevant questions or
              make requests directly in the chat interface.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Registered Plugin Components</CardTitle>
          <CardDescription>
            Each card shows combined backend runtime state and frontend mount
            registration health for the plugin.
          </CardDescription>
        </CardHeader>

        <CardContent>
          {loading ? (
            <div className="flex justify-center p-8" role="status" aria-live="polite">
              <Loader2
                className="h-6 w-6 animate-spin text-primary"
                aria-hidden={true}
              />
            </div>
          ) : error ? (
            <Alert variant="destructive">
              <XCircle className="h-4 w-4" aria-hidden={true} />
              <AlertTitle>Failed to load plugin catalog</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : plugins.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              No dynamic extensions registered yet. Ensure the Python manager
              discovered them.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {plugins.map((plugin) => (
                <PluginHealthCard
                  key={plugin.id}
                  pluginId={plugin.id}
                  displayName={plugin.displayName}
                  description={plugin.description}
                  version={plugin.version}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center text-lg">
            <Settings2 className="mr-2 h-5 w-5 text-primary/80" aria-hidden={true} />
            Vision for Advanced Plugin Architecture
          </CardTitle>
          <CardDescription>
            The long-term goal for Karen AI is to support a more dynamic plugin
            system.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Karen&apos;s plugin layer should remain prompt-first, schema-driven,
            permission-aware, observable, and governed by the backend runtime.
            New capabilities should register their contracts without requiring
            frontend routing hacks.
          </p>

          <ul className="list-inside list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            <li>Standardized plugin schemas describing inputs, outputs, and purpose.</li>
            <li>Manifest-declared frontend surfaces with scoped permissions.</li>
            <li>Backend-owned lifecycle state, RBAC checks, and audit logging.</li>
            <li>Prompt contracts that let Karen understand when and how a plugin applies.</li>
          </ul>

          <Alert variant="default" className="bg-background">
            <Info className="h-4 w-4" aria-hidden={true} />
            <AlertTitle className="text-sm font-semibold">Developer Note</AlertTitle>
            <AlertDescription className="text-xs">
              True drag-and-drop plugin integration requires governed manifests,
              prompt contracts, schemas, permissions, sandboxing, telemetry, and
              lifecycle controls. The UI should display this state, not become
              the plugin authority.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      <Alert className="mt-6">
        <Puzzle className="h-4 w-4" aria-hidden={true} />
        <AlertTitle>Connecting to the Agents & Workflows</AlertTitle>
        <AlertDescription>
          The tools provided by these plugins are building blocks for agent
          skills in the Agents & Workflows section. Assign them to agents to support complex,
          governed automated tasks.
        </AlertDescription>
      </Alert>
    </div>
  );
}
