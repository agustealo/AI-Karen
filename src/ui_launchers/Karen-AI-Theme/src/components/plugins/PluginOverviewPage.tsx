'use client';

/**
 * @file PluginOverviewPage.tsx
 * @description Displays KAREN plugin health, backend lifecycle state,
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
import Link from 'next/link';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  EyeOff,
  Github,
  HelpCircle,
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
import { PluginRecommendedModels } from './PluginRecommendedModels';
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
  declaresUi: boolean;
  isCommunicationChannel: boolean;
  supportsVoiceOutput: boolean;
  rawStatus?: string;
  onOpenVoiceStudio?: () => void;
  onOpenPocketTts?: () => void;
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

const isBackendActive = (state: string): boolean => {
  const normalized = cleanString(state).toLowerCase();
  return ['active', 'enabled', 'loaded', 'registered'].includes(normalized);
};

const getBackendBadgeConfig = (state: BackendState): BadgeConfig => {
  const normalized = cleanString(state).toLowerCase();
  if (['active', 'enabled', 'loaded', 'registered'].includes(normalized)) {
    return {
      icon: CheckCircle2,
      color: 'text-green-600 dark:text-green-400',
      label: normalized === 'active' ? 'active' : 'enabled',
    };
  }

  switch (normalized) {
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
        color: 'text-muted-foreground',
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
  const normalized = cleanString(backendState).toLowerCase();
  if (['active', 'enabled', 'loaded', 'registered'].includes(normalized)) {
    return 'enabled';
  }

  switch (normalized) {
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
  const normalized = cleanString(backendState).toLowerCase();
  if (
    ['active', 'enabled', 'loaded', 'registered', 'disabled', 'validated'].includes(
      normalized,
    )
  ) {
    return 'installed';
  }

  switch (normalized) {
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
      {detailLabel && detailLabel.toLowerCase() !== config.label.toLowerCase()
        ? `${config.label} (${detailLabel})`
        : config.label}
    </span>
  );
}

function FrontendStateBadge({
  state,
  hasGui,
}: {
  state: FrontendMountState | 'registered';
  hasGui?: boolean;
}) {
  if (hasGui === false) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <CheckCircle2 className="h-3 w-3 text-muted-foreground/60" aria-hidden={true} /> not registered (headless)
      </span>
    );
  }

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
  declaresUi,
  isCommunicationChannel,
  supportsVoiceOutput,
  rawStatus,
  onOpenVoiceStudio,
  onOpenPocketTts,
}: PluginHealthCardProps) {
  const { refresh } = usePluginRegistry();
  const health = usePluginHealth(pluginId);

  const [operationInProgress, setOperationInProgress] =
    useState<PluginOperation | null>(null);
  const [operationError, setOperationError] = useState('');
  const [showModelSetup, setShowModelSetup] = useState(false);
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

  const baseBackendState = health.backendState || rawStatus || 'uninstalled';
  const effectiveBackendState =
    operationOverride.backendStatusDetail || baseBackendState;

  const derivedBackendStatusDetail = useMemo(
    () => deriveBackendStatusDetail(effectiveBackendState),
    [effectiveBackendState],
  );

  const derivedUiInstallStatus = useMemo(
    () => deriveUiInstallStatus(effectiveBackendState),
    [effectiveBackendState],
  );

  const isBackendActiveState = useMemo(
    () => isBackendActive(effectiveBackendState),
    [effectiveBackendState],
  );

  // Only the backend manifest can declare a UI contribution. An installed
  // backend transport (including intentionally disabled channels) never
  // implies that a frontend package is missing or requires registration.
  const hasUiCapabilities = declaresUi;

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
    <article className="kari-card flex h-full min-w-0 flex-col gap-4 p-4 sm:p-5" data-testid="plugin-integration-card">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="kari-card-title min-w-0 break-words text-base font-semibold text-foreground">
            {displayName}
            <span className="ml-2 text-xs font-normal opacity-50">v{version}</span>
          </h3>

          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            {description || 'No description provided.'}
          </p>
        </div>

        {!health.permissionVisible && (
          <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
            <EyeOff className="h-3 w-3" aria-hidden={true} /> hidden
          </span>
        )}
      </div>

      <div className="grid min-w-0 gap-3 rounded-xl border border-border/60 bg-muted/20 p-3 text-xs sm:grid-cols-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-muted-foreground">Backend</span>
          <BackendStateBadge
            state={effectiveBackendState}
            detail={backendStatusDetail}
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="font-medium text-muted-foreground">Frontend</span>
          {hasUiCapabilities ? (
            <FrontendStateBadge state={frontendDisplayState} />
          ) : (
            <span className="text-muted-foreground">
              {pluginId === "pocket-tts"
                ? "Host-owned user workspace (no separate plugin bundle)"
                : "not required (backend-only)"}
            </span>
          )}
        </div>

        {hasUiCapabilities && (
          <>
            <div className="flex items-center gap-2">
              <span className="font-medium text-muted-foreground">UI installation</span>
              <UIInstallStatusBadge status={uiInstallStatus} />
            </div>

            <div className="flex items-center gap-2">
              <span className="font-medium text-muted-foreground">UI registration</span>
              <UIRegistrationStatusBadge status={uiRegistrationStatus} />
            </div>
          </>
        )}
      </div>

      {hasUiCapabilities && uiInstallStatus === 'not_installed' && isUiRegistered && (
        <p className="text-xs text-muted-foreground" role="note">
          Frontend registration only confirms that the plugin has a UI entry.
          Its installable UI package is not confirmed as installed. To upload or
          uninstall a complete plugin package, use the Plugin Store.
        </p>
      )}

      {supportsVoiceOutput && !hasUiCapabilities && (
        <p className="text-xs text-muted-foreground" role="note">
          {pluginId === "pocket-tts"
            ? "Pocket TTS has its own user workspace in the Plugins menu. Karen’s VoiceRuntime still owns audio execution, and live voices are shown only after licensed model installation and readiness checks."
            : "Speech controls belong to Karen’s Voice Studio. Backend-only means this extension does not ship a separate frontend; it does not establish model installation, voice availability or playback readiness."}
        </p>
      )}

      {isCommunicationChannel && (
        <p className="text-xs text-muted-foreground" role="note">
          This is a communication transport governed by ChannelHost, not a
          generic plugin executable. Backend disabled does not mean its UI
          failed to register. Connection readiness requires a configured
          host, Vault credentials, authorized activation and provider evidence.
        </p>
      )}

      {operationError && (
        <Alert variant="destructive" className="px-3 py-2">
          <XCircle className="h-3 w-3" aria-hidden={true} />
          <AlertDescription className="text-xs">{operationError}</AlertDescription>
        </Alert>
      )}

      {isBackendActiveState && health.frontendMountState === 'error' && (
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

      <div className="mt-auto flex flex-wrap gap-2 border-t border-border/60 pt-4">
        {supportsVoiceOutput && (
          <Button type="button" size="sm" variant="outline"
            aria-expanded={showModelSetup}
            aria-label={`Download recommended model for ${displayName}`}
            onClick={() => setShowModelSetup((visible) => !visible)}>
            <Settings2 className="mr-1.5 h-4 w-4" aria-hidden="true" />
            {showModelSetup ? 'Hide model setup' : 'Download recommended model'}
          </Button>
        )}
        {pluginId === "pocket-tts" && onOpenPocketTts && (
          <Button type="button" size="sm" variant="default"
            onClick={onOpenPocketTts} aria-label="Open Pocket TTS workspace">
            <Settings2 className="mr-1.5 h-4 w-4" aria-hidden="true" />
            Open Pocket TTS
          </Button>
        )}
        {supportsVoiceOutput && onOpenVoiceStudio && (
          <Button type="button" size="sm" variant="outline"
            onClick={onOpenVoiceStudio} aria-label={`Open Voice Studio for ${displayName}`}>
            <Settings2 className="mr-1.5 h-4 w-4" aria-hidden={true} />
            Open Voice Studio
          </Button>
        )}
        {supportsVoiceOutput && showModelSetup && (
          <div className="w-full">
            <PluginRecommendedModels key={pluginId} pluginId={pluginId} />
          </div>
        )}
        {hasUiCapabilities && uiInstallStatus === 'installed' && isBackendActiveState && (
          <div className="flex items-center gap-2 text-xs text-green-600">
            <CheckCircle2 className="h-3 w-3" aria-hidden={true} />
            UI Mounted
          </div>
        )}

        {hasUiCapabilities && uiInstallStatus === 'installed' && !isBackendActiveState && (
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

        {!isCommunicationChannel && health.backendState !== 'error' && (
          <>
            {isBackendActiveState && (
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

            {!isBackendActiveState && health.backendState !== 'error' && (
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

        {hasUiCapabilities && health.backendState !== 'uninstalled' && uiInstallStatus === 'installed' && (
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={() => void handleRemoveUI()}
            disabled={isOperationInProgress}
          >
            {isRemoving ? 'Removing UI...' : 'Remove UI only'}
          </Button>
        )}

        {hasUiCapabilities && health.backendState === 'uninstalled' && (
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
    </article>
  );
}

export default function PluginOverviewPage({
  onOpenVoiceStudio,
  onOpenPocketTts,
}: { onOpenVoiceStudio?: () => void; onOpenPocketTts?: () => void } = {}) {
  const { plugins, loading, error } = usePluginRegistry();

  // Catalog totals are derived strictly from the same registry snapshot as
  // the cards. They are intentionally not claims of runtime readiness.
  const declaredUiCount = plugins.filter((plugin) => plugin.has_gui).length;
  const communicationCount = plugins.filter(
    (plugin) => plugin.isCommunicationChannel === true,
  ).length;

  return (
    <main
      data-kari-root
      data-testid="plugins-overview"
      className="min-w-0 space-y-6 pb-8"
      aria-labelledby="plugins-overview-title"
    >
      <header className="karen-surface relative isolate overflow-hidden rounded-2xl border border-border/70 bg-gradient-to-br from-card via-card to-primary/10 p-5 shadow-lg md:p-8">
        <div aria-hidden="true" className="karen-workspace-grid pointer-events-none absolute inset-0 opacity-30" />
        <div className="relative flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
          <div className="min-w-0 max-w-2xl">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 text-xs font-semibold tracking-wide text-primary">
              <PlugZap aria-hidden="true" className="h-4 w-4" />
              Extension workspace
            </div>
            <h1 id="plugins-overview-title" className="kari-display karen-page-title text-balance md:text-[2.25rem]">
              Plugins &amp; Tools
            </h1>
            <p className="karen-page-description mt-3 max-w-xl">
              Inspect governed capabilities, backend lifecycle state and frontend registration.
              Plugin execution and permissions remain with KAREN&apos;s runtime.
            </p>
          </div>
          <Button asChild className="min-h-11 shrink-0 gap-2 self-start lg:self-end">
            <Link href="/plugins">
              <Puzzle aria-hidden="true" className="h-4 w-4" />
              Upload and install a plugin
            </Link>
          </Button>
        </div>
      </header>

      <section aria-label="Plugin registry snapshot" className="grid gap-3 sm:grid-cols-3">
        <div className="kari-card p-4 sm:p-5">
          <p className="karen-panel-label">Discovered plugins</p>
          <p className="kari-display mt-2 text-3xl font-semibold tabular-nums" data-testid="plugin-count">
            {loading || error ? '—' : plugins.length}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">Registry entries, not verified active executions</p>
        </div>
        <div className="kari-card p-4 sm:p-5">
          <p className="karen-panel-label">UI-declaring plugins</p>
          <p className="kari-display mt-2 text-3xl font-semibold tabular-nums" data-testid="plugin-ui-count">
            {loading || error ? '—' : declaredUiCount}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">Manifest-declared frontend capability</p>
        </div>
        <div className="kari-card p-4 sm:p-5">
          <p className="karen-panel-label">Communication channels</p>
          <p className="kari-display mt-2 text-3xl font-semibold tabular-nums" data-testid="plugin-channel-count">
            {loading || error ? '—' : communicationCount}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">Transport integrations, not connection readiness</p>
        </div>
      </section>

      <section aria-labelledby="plugin-catalog-heading" className="kari-card overflow-hidden">
        <div className="flex flex-col gap-2 border-b border-border/70 bg-muted/20 p-5 sm:flex-row sm:items-end sm:justify-between md:px-6">
          <div className="min-w-0">
            <h2 id="plugin-catalog-heading" className="kari-card-title text-lg font-semibold">
              Registered plugin components
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Backend status and UI registration are separate signals. Actions are governed by the existing plugin APIs.
            </p>
          </div>
          {!loading && !error && (
            <span className="kari-metric shrink-0 text-muted-foreground" aria-label={plugins.length + ' registry entries'}>
              {plugins.length} ENTRIES
            </span>
          )}
        </div>
        <div className="p-4 md:p-6">
          {loading ? (
            <div className="flex items-center justify-center gap-3 rounded-xl border border-border/60 bg-muted/20 p-10" role="status" aria-live="polite">
              <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden="true" />
              <span className="text-sm text-muted-foreground">Loading the live plugin registry…</span>
            </div>
          ) : error ? (
            <Alert variant="destructive">
              <XCircle aria-hidden="true" className="h-4 w-4" />
              <AlertTitle>Plugin catalog unavailable</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : plugins.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border/70 bg-muted/20 px-5 py-10 text-center">
              <Puzzle aria-hidden="true" className="mx-auto mb-3 h-6 w-6 text-muted-foreground" />
              <h3 className="kari-card-title text-base font-semibold">No plugins discovered</h3>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                The backend registry has not returned any extensions for this session.
                Discovery and installation are managed by the plugin runtime.
              </p>
            </div>
          ) : (
            <div className="grid min-w-0 gap-4 lg:grid-cols-2" data-testid="plugin-registry-grid">
              {plugins.map((plugin) => (
                <PluginHealthCard
                  key={plugin.id}
                  pluginId={plugin.id}
                  displayName={plugin.displayName}
                  description={plugin.description}
                  version={plugin.version}
                  declaresUi={plugin.has_gui}
                  isCommunicationChannel={plugin.isCommunicationChannel === true}
                  supportsVoiceOutput={plugin.supportsVoiceOutput === true}
                  rawStatus={plugin.rawStatus}
                  onOpenVoiceStudio={onOpenVoiceStudio}
                  onOpenPocketTts={onOpenPocketTts}
                />
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section aria-labelledby="plugin-invocation-heading" className="kari-card p-5 md:p-6">
          <div className="flex items-center gap-2">
            <MessageSquare aria-hidden="true" className="h-5 w-5 text-primary" />
            <h2 id="plugin-invocation-heading" className="kari-card-title text-base font-semibold">
              Prompt-first interaction
            </h2>
          </div>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            Ask KAREN for a task in chat. The runtime determines eligible tools from
            registered capabilities, prompt contracts and permissions. The UI does not
            select executors or imply that a plugin ran.
          </p>
        </section>
        <section aria-labelledby="plugin-governance-heading" className="kari-card p-5 md:p-6">
          <div className="flex items-center gap-2">
            <Settings2 aria-hidden="true" className="h-5 w-5 text-primary" />
            <h2 id="plugin-governance-heading" className="kari-card-title text-base font-semibold">
              Governed extensions
            </h2>
          </div>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            Manifests, input/output schemas, RBAC, audit evidence and lifecycle controls
            remain backend-owned. Plugin capabilities may support authorized agents and workflows.
          </p>
        </section>
      </div>
    </main>
  );
}
