'use client';

/**
 * @file NotificationSettings.tsx
 * @description Live-backed notification preferences for Karen.
 *
 * Backend ownership:
 * - Notification preferences must persist through backend settings/profile APIs.
 * - UI may keep a temporary draft cache, but localStorage is not runtime truth.
 * - Success toast only fires after backend save succeeds.
 */

import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Bell, Loader2, RotateCcw, Save } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '../ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';

import { useToast } from '@/hooks/use-toast';
import { ApiError, apiClient } from '@/lib/api';
import { DEFAULT_KAREN_SETTINGS } from '@/lib/constants';
import type { NotificationPreferences } from '@/lib/types';

type NotificationSettingsResponse = Partial<NotificationPreferences> & {
  notifications?: Partial<NotificationPreferences>;
  settings?: Partial<NotificationPreferences>;
};

type BackendStatus = 'checking' | 'available' | 'unavailable';

const NOTIFICATION_SETTINGS_ENDPOINT = '/api/settings/notifications';
const NOTIFICATION_DRAFT_CACHE_KEY = 'karen_notification_settings_draft_v1';

const DEFAULT_NOTIFICATION_SETTINGS: NotificationPreferences = {
  ...DEFAULT_KAREN_SETTINGS.notifications,
};

const getErrorMessage = (
  error: unknown,
  fallback = 'Notification settings request failed.',
): string => {
  if (error instanceof ApiError && error.message.trim()) {
    return error.message.trim();
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }

  if (typeof error === 'string' && error.trim()) {
    return error.trim();
  }

  return fallback;
};

const isUnavailableError = (error: unknown): boolean => {
  return (
    error instanceof ApiError &&
    (error.status === 404 || error.status === 405 || error.status === 501)
  );
};

const coerceBoolean = (value: unknown, fallback: boolean): boolean => {
  return typeof value === 'boolean' ? value : fallback;
};

const normalizeNotificationSettings = (
  value: unknown,
): NotificationPreferences => {
  const raw =
    value && typeof value === 'object'
      ? (value as NotificationSettingsResponse)
      : {};

  const source =
    raw.notifications && typeof raw.notifications === 'object'
      ? raw.notifications
      : raw.settings && typeof raw.settings === 'object'
        ? raw.settings
        : raw;

  return {
    enabled: coerceBoolean(
      source.enabled,
      DEFAULT_NOTIFICATION_SETTINGS.enabled,
    ),
    alertOnNewInsights: coerceBoolean(
      source.alertOnNewInsights,
      DEFAULT_NOTIFICATION_SETTINGS.alertOnNewInsights,
    ),
    alertOnSummaryReady: coerceBoolean(
      source.alertOnSummaryReady,
      DEFAULT_NOTIFICATION_SETTINGS.alertOnSummaryReady,
    ),
  };
};

const readDraftSettings = (): NotificationPreferences | null => {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(NOTIFICATION_DRAFT_CACHE_KEY);

    if (!raw) {
      return null;
    }

    return normalizeNotificationSettings(JSON.parse(raw));
  } catch {
    return null;
  }
};

const writeDraftSettings = (settings: NotificationPreferences): void => {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    window.localStorage.setItem(
      NOTIFICATION_DRAFT_CACHE_KEY,
      JSON.stringify(settings),
    );
  } catch {
    /*
     * Draft cache failure must not masquerade as backend persistence.
     * Notification settings are only active after backend save succeeds.
     */
  }
};

const clearDraftSettings = (): void => {
  if (typeof window === 'undefined') {
    return;
  }

  try {
    window.localStorage.removeItem(NOTIFICATION_DRAFT_CACHE_KEY);
  } catch {
    // Non-critical cleanup.
  }
};

export default function NotificationSettings() {
  const [notifications, setNotifications] =
    useState<NotificationPreferences>(DEFAULT_NOTIFICATION_SETTINGS);
  const [backendStatus, setBackendStatus] =
    useState<BackendStatus>('checking');
  const [loadError, setLoadError] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const { toast } = useToast();

  const [hasDraft, setHasDraft] = useState(false);

  const loadSettings = useCallback(async () => {
    setIsLoading(true);
    setLoadError('');

    const draft = readDraftSettings();
    setHasDraft(Boolean(draft));

    if (draft) {
      setNotifications(draft);
    }

    try {
      const response = await apiClient.get<NotificationSettingsResponse>(
        NOTIFICATION_SETTINGS_ENDPOINT,
      );
      const liveSettings = normalizeNotificationSettings(response);

      setNotifications(liveSettings);
      setBackendStatus('available');
      clearDraftSettings();
      setHasDraft(false);
    } catch (error) {
      setBackendStatus('unavailable');

      if (!draft) {
        setNotifications(DEFAULT_NOTIFICATION_SETTINGS);
      }

      setLoadError(
        isUnavailableError(error)
          ? 'Notification settings endpoint is not available yet.'
          : getErrorMessage(
              error,
              'Karen could not load notification settings.',
            ),
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const updateNotifications = useCallback(
    (patch: Partial<NotificationPreferences>) => {
      setNotifications((current) => {
        const next = {
          ...current,
          ...patch,
        };

        writeDraftSettings(next);
        setHasDraft(true);
        return next;
      });
    },
    [],
  );

  const handleEnabledChange = useCallback(
    (enabled: boolean) => {
      updateNotifications({ enabled });
    },
    [updateNotifications],
  );

  const handleAlertTypeChange = useCallback(
    (
      alertType: keyof Omit<NotificationPreferences, 'enabled'>,
      checked: boolean,
    ) => {
      updateNotifications({ [alertType]: checked });
    },
    [updateNotifications],
  );

  const saveSettings = useCallback(
    async (nextSettings: NotificationPreferences) => {
      if (isSaving) {
        return;
      }

      setIsSaving(true);
      writeDraftSettings(nextSettings);
      setHasDraft(true);

      try {
        const response = await apiClient.put<NotificationSettingsResponse>(
          NOTIFICATION_SETTINGS_ENDPOINT,
          nextSettings,
        );
        const liveSettings = normalizeNotificationSettings(response);

        setNotifications(liveSettings);
        setBackendStatus('available');
        setLoadError('');
        clearDraftSettings();
        setHasDraft(false);

        toast({
          title: 'Notification Settings Saved',
          description: 'Karen synced your notification preferences to backend.',
        });
      } catch (error) {
        setBackendStatus('unavailable');
        setLoadError(
          isUnavailableError(error)
            ? 'Notification settings endpoint is unavailable. Your changes remain a local draft only.'
            : getErrorMessage(
                error,
                'Karen could not save notification settings.',
              ),
        );

        toast({
          title: 'Notification Save Failed',
          description: isUnavailableError(error)
            ? 'Backend notification settings are unavailable. Draft was kept locally but is not active runtime truth.'
            : getErrorMessage(
                error,
                'Could not save notification settings to backend.',
              ),
          variant: 'destructive',
        });
      } finally {
        setIsSaving(false);
      }
    },
    [isSaving, toast],
  );

  const handleSave = useCallback(async () => {
    await saveSettings(notifications);
  }, [notifications, saveSettings]);

  const resetToDefaults = useCallback(async () => {
    setNotifications(DEFAULT_NOTIFICATION_SETTINGS);
    writeDraftSettings(DEFAULT_NOTIFICATION_SETTINGS);
    await saveSettings(DEFAULT_NOTIFICATION_SETTINGS);
  }, [saveSettings]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Bell className="h-5 w-5 text-primary" aria-hidden="true" />
          Notification Preferences
        </CardTitle>
        <CardDescription>
          Manage how and when Karen AI notifies you. Changes apply after they
          sync to Karen&apos;s backend settings.
        </CardDescription>
      </CardHeader>

      <CardContent className="p-0">
        {backendStatus === 'unavailable' && (
          <div className="px-6 pb-4">
            <Alert className="border-amber-500/30 bg-amber-500/10">
              <AlertCircle
                className="h-4 w-4 !text-amber-600"
                aria-hidden="true"
              />
              <AlertTitle>Notification Backend Unavailable</AlertTitle>
              <AlertDescription>
                {loadError ||
                  'Karen could not reach the live notification settings endpoint.'}
                {hasDraft && (
                  <span className="mt-1 block">
                    A local draft may exist, but it is not active backend
                    runtime configuration until save succeeds.
                  </span>
                )}
              </AlertDescription>
            </Alert>
          </div>
        )}

        {isLoading ? (
          <div
            className="flex items-center gap-2 px-6 py-6 text-sm text-muted-foreground"
            role="status"
            aria-live="polite"
          >
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading notification settings.
          </div>
        ) : (
          <div className="divide-y divide-border">
            <div className="px-6 py-4">
              <div className="flex items-center space-x-2">
                <Switch
                  id="enable-notifications"
                  checked={notifications.enabled}
                  onCheckedChange={handleEnabledChange}
                />
                <Label
                  htmlFor="enable-notifications"
                  className="cursor-pointer"
                >
                  Enable All Notifications
                </Label>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Toggle all app notifications on or off. Specific alert types
                below require this to be enabled.
              </p>
            </div>

            <div className="space-y-4 px-6 py-4">
              <Label className="mb-2 block text-base font-medium">
                Alert Types
              </Label>

              <div className="space-y-1">
                <div className="flex items-center space-x-3">
                  <Checkbox
                    id="alert-insights"
                    checked={notifications.alertOnNewInsights}
                    onCheckedChange={(checked) =>
                      handleAlertTypeChange(
                        'alertOnNewInsights',
                        Boolean(checked),
                      )
                    }
                    disabled={!notifications.enabled}
                  />
                  <Label
                    htmlFor="alert-insights"
                    className={`cursor-pointer ${
                      !notifications.enabled ? 'text-muted-foreground' : ''
                    }`}
                  >
                    New Insights Available
                  </Label>
                </div>
                <p className="pl-7 text-xs text-muted-foreground">
                  Get a notification when Karen provides new insight metadata in
                  a message.
                </p>
              </div>

              <div className="space-y-1">
                <div className="flex items-center space-x-3">
                  <Checkbox
                    id="alert-summary"
                    checked={notifications.alertOnSummaryReady}
                    onCheckedChange={(checked) =>
                      handleAlertTypeChange(
                        'alertOnSummaryReady',
                        Boolean(checked),
                      )
                    }
                    disabled={!notifications.enabled}
                  />
                  <Label
                    htmlFor="alert-summary"
                    className={`cursor-pointer ${
                      !notifications.enabled ? 'text-muted-foreground' : ''
                    }`}
                  >
                    Conversation Summary Ready
                  </Label>
                </div>
                <p className="pl-7 text-xs text-muted-foreground">
                  Notify when the backend marks a conversation summary as ready.
                </p>
              </div>
            </div>
          </div>
        )}
      </CardContent>

      <CardFooter className="flex justify-end space-x-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => void resetToDefaults()}
          disabled={isLoading || isSaving}
        >
          {isSaving ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" />
          )}
          Reset to Defaults
        </Button>

        <Button
          type="button"
          onClick={() => void handleSave()}
          disabled={isLoading || isSaving}
        >
          {isSaving ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Save className="mr-2 h-4 w-4" aria-hidden="true" />
          )}
          Save Settings
        </Button>
      </CardFooter>
    </Card>
  );
}
