"use client";

/**
 * Plugin Settings UI - Configuration interface for plugins.
 *
 * Provides:
 * - PluginSettingsProvider for managing plugin settings
 * - usePluginSettings hook for accessing plugin settings
 * - PluginSettingsForm component for rendering settings
 * - Settings persistence with backend integration
 * - Schema-based form generation
 * - Type-safe settings access
 *
 * Requirements: 4.3
 */

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Loader2, Save, RotateCcw, AlertCircle, CheckCircle2 } from 'lucide-react';
import apiClient from '@/lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

/** Supported setting types */
export type SettingType = 'string' | 'number' | 'boolean' | 'text' | 'select' | 'password' | 'json';

/** Setting schema definition */
export interface SettingSchema {
  /** Setting key */
  key: string;
  /** Display label */
  label: string;
  /** Description/tooltip */
  description?: string;
  /** Setting type */
  type: SettingType;
  /** Default value */
  defaultValue?: unknown;
  /** Validation options */
  validation?: {
    required?: boolean;
    min?: number;
    max?: number;
    pattern?: string;
    minLength?: number;
    maxLength?: number;
  };
  /** Options for select type */
  options?: Array<{
    value: string;
    label: string;
    description?: string;
  }>;
  /** Whether setting is read-only */
  readOnly?: boolean;
  /** Whether setting requires plugin restart */
  requiresRestart?: boolean;
  /** Category for grouping */
  category?: string;
  /** Order within category */
  order?: number;
}

/** Plugin settings configuration */
export interface PluginSettingsConfig {
  /** Plugin ID */
  pluginId: string;
  /** Settings schema */
  schema: SettingSchema[];
  /** Current settings values */
  values: Record<string, unknown>;
  /** Whether settings are loaded */
  loaded: boolean;
  /** Whether settings are modified */
  modified: boolean;
  /** Error state */
  error: string | null;
  /** Revision returned by the tenant-scoped database. */
  revision: number;
  stored: boolean;
}

/** Settings context value */
export interface PluginSettingsContextValue {
  /** Get settings for a plugin */
  getPluginSettings: (pluginId: string) => PluginSettingsConfig | undefined;
  /** Save settings for a plugin */
  savePluginSettings: (pluginId: string) => Promise<boolean>;
  /** Reset settings to defaults */
  resetPluginSettings: (pluginId: string) => Promise<boolean>;
  /** Update a setting value */
  updateSetting: (pluginId: string, key: string, value: unknown) => void;
  /** Refresh settings from backend */
  refreshSettings: (pluginId: string) => Promise<void>;
  /** Load all plugins' settings */
  loadAllSettings: () => Promise<void>;
}

// ─── Context ──────────────────────────────────────────────────────────────────

const PluginSettingsContext = createContext<PluginSettingsContextValue | null>(null);

// ─── Provider ──────────────────────────────────────────────────────────────────

type PluginSettingsApiResponse = {
  plugin_id: string;
  settings: Record<string, unknown>;
  schema: SettingSchema[];
  revision: number;
  stored: boolean;
  success?: boolean;
  saved?: boolean;
  reset?: boolean;
};

function checkedSettingsResponse(
  value: unknown,
  pluginId: string,
): PluginSettingsApiResponse {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Plugin settings API returned an invalid response.');
  }
  const response = value as Partial<PluginSettingsApiResponse>;
  if (
    response.plugin_id !== pluginId ||
    !response.settings ||
    typeof response.settings !== 'object' ||
    Array.isArray(response.settings) ||
    !Array.isArray(response.schema) ||
    !response.schema.every(
      (field) => field && typeof field.key === 'string' && typeof field.type === 'string',
    ) ||
    typeof response.revision !== 'number' ||
    !Number.isSafeInteger(response.revision) ||
    (response.revision ?? -1) < 0 ||
    typeof response.stored !== 'boolean'
  ) {
    throw new Error('Plugin settings API returned an invalid response.');
  }
  return response as PluginSettingsApiResponse;
}

function configFromBackend(response: PluginSettingsApiResponse): PluginSettingsConfig {
  return {
    pluginId: response.plugin_id,
    values: Object.fromEntries(
      Object.entries(response.settings).filter(([key]) =>
        response.schema.some((field) =>
          field.key === key && !field.readOnly && field.type !== 'password' && field.type !== 'json',
        ),
      ),
    ),
    schema: response.schema,
    revision: response.revision,
    stored: response.stored,
    loaded: true,
    modified: false,
    error: null,
  };
}

export function PluginSettingsProvider({ children }: { children: React.ReactNode }) {
  const [pluginSettings, setPluginSettings] = useState<Map<string, PluginSettingsConfig>>(new Map());
  const latestLoads = useRef(new Map<string, number>());

  const getPluginSettings = useCallback((pluginId: string): PluginSettingsConfig | undefined => {
    return pluginSettings.get(pluginId);
  }, [pluginSettings]);

  const updateSetting = useCallback((pluginId: string, key: string, value: unknown) => {
    setPluginSettings((prev) => {
      const config = prev.get(pluginId);
      if (!config || !config.loaded || config.schema.length === 0) return prev;
      const field = config.schema.find((item) => item.key === key);
      // The UI is never an authority for credential storage.
      if (!field || field.readOnly || field.type === 'password' || field.type === 'json') return prev;

      return new Map(prev).set(pluginId, {
        ...config,
        values: { ...config.values, [key]: value },
        modified: true,
        error: null,
      });
    });
  }, []);

  const refreshSettings = useCallback(async (pluginId: string) => {
    const sequence = (latestLoads.current.get(pluginId) ?? 0) + 1;
    latestLoads.current.set(pluginId, sequence);
    setPluginSettings((prev) => {
      const current = prev.get(pluginId);
      return new Map(prev).set(pluginId, {
        pluginId,
        schema: current?.schema ?? [],
        values: current?.values ?? {},
        revision: current?.revision ?? 0,
        stored: current?.stored ?? false,
        loaded: false,
        modified: current?.modified ?? false,
        error: null,
      });
    });
    try {
      const response: unknown = await apiClient.get(
        "/api/extensions/" + encodeURIComponent(pluginId) + "/settings",
      );
      const checked = checkedSettingsResponse(response, pluginId);
      if (latestLoads.current.get(pluginId) !== sequence) return;
      setPluginSettings((prev) => new Map(prev).set(pluginId, configFromBackend(checked)));
    } catch (err) {
      if (latestLoads.current.get(pluginId) !== sequence) return;
      const message = err instanceof Error ? err.message : 'Failed to load plugin settings';
      setPluginSettings((prev) => new Map(prev).set(pluginId, {
        pluginId,
        schema: [],
        values: {},
        revision: 0,
        stored: false,
        loaded: true,
        modified: false,
        error: message,
      }));
    }
  }, []);

  const savePluginSettings = useCallback(async (pluginId: string): Promise<boolean> => {
    const config = pluginSettings.get(pluginId);
    if (!config || !config.loaded || config.schema.length === 0) return false;
    if (!config.modified) return true;

    const values = { ...config.values };
    const revision = config.revision;
    try {
      const result: unknown = await apiClient.post(
        "/api/extensions/" + encodeURIComponent(pluginId) + "/settings",
        { settings: values, revision },
      );
      const checked = checkedSettingsResponse(result, pluginId);
      if (
        checked.success !== true ||
        checked.saved !== true ||
        checked.revision <= revision ||
        checked.stored !== true
      ) {
        throw new Error('The backend did not confirm durable settings persistence.');
      }
      setPluginSettings((prev) => {
        const current = prev.get(pluginId);
        if (!current || current.revision !== revision) return prev;
        // New keystrokes during the request remain unsaved, not silently lost.
        const sameValues = JSON.stringify(current.values) === JSON.stringify(values);
        return new Map(prev).set(pluginId, {
          ...current,
          ...(sameValues ? configFromBackend(checked) : {
            revision: checked.revision,
            stored: checked.stored,
            error: null,
          }),
        });
      });
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save settings';
      setPluginSettings((prev) => {
        const current = prev.get(pluginId);
        return current ? new Map(prev).set(pluginId, { ...current, error: message }) : prev;
      });
      return false;
    }
  }, [pluginSettings]);

  const resetPluginSettings = useCallback(async (pluginId: string): Promise<boolean> => {
    const config = pluginSettings.get(pluginId);
    if (!config || !config.loaded) return false;
    const revision = config.revision;
    try {
      const result: unknown = await apiClient.delete(
        "/api/extensions/" + encodeURIComponent(pluginId) + "/settings?revision=" + revision,
      );
      const checked = checkedSettingsResponse(result, pluginId);
      if (
        checked.success !== true ||
        checked.reset !== true ||
        checked.revision <= revision
      ) {
        throw new Error('The backend did not confirm a durable settings reset.');
      }
      setPluginSettings((prev) => {
        const current = prev.get(pluginId);
        return current && current.revision === revision
          ? new Map(prev).set(pluginId, configFromBackend(checked))
          : prev;
      });
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to reset settings';
      setPluginSettings((prev) => {
        const current = prev.get(pluginId);
        return current ? new Map(prev).set(pluginId, { ...current, error: message }) : prev;
      });
      return false;
    }
  }, [pluginSettings]);

  const loadAllSettings = useCallback(async () => {
    const response: unknown = await apiClient.get('/api/extensions/settings');
    if (!Array.isArray(response)) {
      throw new Error('Plugin settings list API returned an invalid response.');
    }
    const next = new Map<string, PluginSettingsConfig>();
    for (const record of response) {
      if (!record || typeof record !== 'object' || typeof record.plugin_id !== 'string') {
        throw new Error('Plugin settings list API returned an invalid response.');
      }
      const checked = checkedSettingsResponse(record, record.plugin_id);
      next.set(checked.plugin_id, configFromBackend(checked));
    }
    setPluginSettings(next);
  }, []);

  const value: PluginSettingsContextValue = {
    getPluginSettings,
    savePluginSettings,
    resetPluginSettings,
    updateSetting,
    refreshSettings,
    loadAllSettings,
  };

  return React.createElement(PluginSettingsContext.Provider, { value }, children);
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function usePluginSettings(pluginId: string): PluginSettingsConfig {
  const context = useContext(PluginSettingsContext);
  if (!context) {
    throw new Error('usePluginSettings must be used within a PluginSettingsProvider');
  }

  const config = context.getPluginSettings(pluginId);
  if (!config) {
    return {
      pluginId,
      schema: [],
      values: {},
      loaded: false,
      modified: false,
      error: 'Settings not loaded',
      revision: 0,
      stored: false,
    };
  }

  return config;
}

export function usePluginSettingsManager(): PluginSettingsContextValue {
  const context = useContext(PluginSettingsContext);
  if (!context) {
    throw new Error('usePluginSettingsManager must be used within a PluginSettingsProvider');
  }
  return context;
}

// ─── Components ───────────────────────────────────────────────────────────────

/** Form field for a single setting */
function SettingField({
  setting,
  value,
  onChange,
  readOnly,
}: {
  setting: SettingSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  readOnly?: boolean;
}) {
  const id = `setting-${setting.key}`;

  switch (setting.type) {
    case 'boolean':
      return (
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label htmlFor={id}>{setting.label}</Label>
            {setting.description && (
              <p className="text-xs text-muted-foreground">{setting.description}</p>
            )}
          </div>
          <Switch
            id={id}
            checked={Boolean(value)}
            onCheckedChange={onChange}
            disabled={readOnly}
          />
        </div>
      );

    case 'select':
      return (
        <div className="space-y-2">
          <Label htmlFor={id}>{setting.label}</Label>
          {setting.description && (
            <p className="text-xs text-muted-foreground">{setting.description}</p>
          )}
          <Select value={String(value)} onValueChange={onChange} disabled={readOnly}>
            <SelectTrigger id={id}>
              <SelectValue placeholder="Select an option" />
            </SelectTrigger>
            <SelectContent>
              {setting.options?.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );

    case 'number':
      return (
        <div className="space-y-2">
          <Label htmlFor={id}>{setting.label}</Label>
          {setting.description && (
            <p className="text-xs text-muted-foreground">{setting.description}</p>
          )}
          <Input
            id={id}
            type="number"
            value={value !== undefined ? String(value) : ''}
            onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}
            disabled={readOnly}
            min={setting.validation?.min}
            max={setting.validation?.max}
          />
        </div>
      );

    case 'text':
      return (
        <div className="space-y-2">
          <Label htmlFor={id}>{setting.label}</Label>
          {setting.description && (
            <p className="text-xs text-muted-foreground">{setting.description}</p>
          )}
          <Textarea
            id={id}
            value={String(value || '')}
            onChange={(e) => onChange(e.target.value)}
            disabled={readOnly}
            rows={3}
            maxLength={setting.validation?.maxLength}
          />
        </div>
      );

    case 'password':
      return (
        <div className="space-y-2">
          <Label htmlFor={id}>{setting.label}</Label>
          {setting.description && (
            <p className="text-xs text-muted-foreground">{setting.description}</p>
          )}
          <Input
            id={id}
            type="password"
            value={String(value || '')}
            onChange={(e) => onChange(e.target.value)}
            disabled={readOnly}
          />
        </div>
      );

    case 'json':
      return (
        <div className="space-y-2">
          <Label htmlFor={id}>{setting.label}</Label>
          {setting.description && (
            <p className="text-xs text-muted-foreground">{setting.description}</p>
          )}
          <Textarea
            id={id}
            value={value !== undefined ? JSON.stringify(value, null, 2) : ''}
            onChange={(e) => {
              try {
                onChange(JSON.parse(e.target.value));
              } catch {
                onChange(e.target.value);
              }
            }}
            disabled={readOnly}
            rows={5}
            className="font-mono text-xs"
          />
        </div>
      );

    case 'string':
    default:
      return (
        <div className="space-y-2">
          <Label htmlFor={id}>{setting.label}</Label>
          {setting.description && (
            <p className="text-xs text-muted-foreground">{setting.description}</p>
          )}
          <Input
            id={id}
            type="text"
            value={String(value || '')}
            onChange={(e) => onChange(e.target.value)}
            disabled={readOnly}
            maxLength={setting.validation?.maxLength}
          />
        </div>
      );
  }
}

type CredentialStatus = {
  configured: boolean;
  status: string;
  revision: number;
};

function checkedCredentialStatus(value: unknown, receipt = false): CredentialStatus {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Identity Vault returned an invalid credential receipt.');
  }
  const record = value as Partial<CredentialStatus>;
  if (
    typeof record.configured !== 'boolean' ||
    typeof record.status !== 'string' ||
    !['missing', 'active', 'revoked', 'unavailable'].includes(record.status) ||
    typeof record.revision !== 'number' ||
    !Number.isSafeInteger(record.revision) ||
    record.revision < 0 ||
    record.configured !== (record.status === 'active')
  ) {
    throw new Error('Identity Vault returned an invalid credential receipt.');
  }
  const allowed = receipt
    ? ['configured', 'status', 'revision', 'plugin_id', 'field_key']
    : ['configured', 'status', 'revision'];
  if (Object.keys(record).some((key) => !allowed.includes(key))) {
    throw new Error('Identity Vault returned an invalid credential receipt.');
  }
  return {
    configured: record.configured,
    status: record.status,
    revision: record.revision,
  } as CredentialStatus;
}

function CredentialField({
  pluginId,
  setting,
  status,
  onReceipt,
}: {
  pluginId: string;
  setting: SettingSchema;
  status: CredentialStatus;
  onReceipt: (status: CredentialStatus) => void;
}) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState<string | null>(null);
  const path = '/api/extensions/' + encodeURIComponent(pluginId) +
    '/credentials/' + encodeURIComponent(setting.key);

  const write = async () => {
    if (!value || busy) return;
    const submitted = value;
    setValue(''); // Never preserve entered credential after an API request.
    setBusy(true);
    setCompleted(null);
    setError(null);
    try {
      const response: unknown = await apiClient.post(path, {
        value: submitted,
        revision: status.revision,
      });
      if (
        !response || typeof response !== 'object' ||
        (response as { plugin_id?: unknown }).plugin_id !== pluginId ||
        (response as { field_key?: unknown }).field_key !== setting.key
      ) {
        throw new Error('Identity Vault did not confirm credential persistence.');
      }
      const checked = checkedCredentialStatus(response, true);
      if (!checked.configured || checked.revision <= status.revision) {
        throw new Error('Identity Vault did not confirm credential persistence.');
      }
      onReceipt(checked);
      setCompleted('Credential saved in Identity Vault.');
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : 'Credential write failed.');
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    if (!confirmRevoke || busy) return;
    setValue('');
    setBusy(true);
    setError(null);
    setCompleted(null);
    setConfirmRevoke(false);
    try {
      const response: unknown = await apiClient.delete(
        path + '?revision=' + status.revision,
      );
      if (
        !response || typeof response !== 'object' ||
        (response as { plugin_id?: unknown }).plugin_id !== pluginId ||
        (response as { field_key?: unknown }).field_key !== setting.key
      ) {
        throw new Error('Identity Vault did not confirm credential revocation.');
      }
      const checked = checkedCredentialStatus(response, true);
      if (checked.configured || checked.status !== 'revoked' || checked.revision <= status.revision) {
        throw new Error('Identity Vault did not confirm credential revocation.');
      }
      onReceipt(checked);
      setCompleted('Credential revoked and encrypted value erased.');
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : 'Credential revocation failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={'credential-' + setting.key}>{setting.label}</Label>
        <span role="status" className="text-xs text-muted-foreground">
          {status.configured ? 'Configured in Identity Vault' :
            status.status === 'revoked' ? 'Revoked' :
            status.status === 'unavailable' ? 'Unavailable' : 'Not configured'}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        The stored value is never displayed. Re-enter a complete replacement to rotate.
      </p>
      <Input
        id={'credential-' + setting.key}
        type="password"
        autoComplete="new-password"
        value={value}
        disabled={busy}
        maxLength={4096}
        onChange={(event) => {
          setValue(event.target.value);
          setCompleted(null);
          setError(null);
        }}
      />
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" disabled={busy || !value} onClick={() => { void write(); }}>
          {busy ? 'Working...' : status.configured ? 'Rotate credential' : 'Save credential'}
        </Button>
        {status.configured && (
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={busy}
            onClick={() => {
              if (!confirmRevoke) {
                setConfirmRevoke(true);
              } else {
                void revoke();
              }
            }}
          >
            {confirmRevoke ? 'Confirm revoke' : 'Revoke credential'}
          </Button>
        )}
        {confirmRevoke && (
          <Button type="button" size="sm" variant="outline" onClick={() => setConfirmRevoke(false)}>
            Cancel
          </Button>
        )}
      </div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {completed && <p role="status" className="text-sm">{completed}</p>}
    </div>
  );
}

function PluginCredentialsManager({
  pluginId,
  fields,
}: {
  pluginId: string;
  fields: SettingSchema[];
}) {
  const [statuses, setStatuses] = useState<Record<string, CredentialStatus> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setStatuses(null);
    setError(null);
    void (async () => {
      try {
        const response: unknown = await apiClient.get(
          '/api/extensions/' + encodeURIComponent(pluginId) + '/credentials',
        );
        if (
          !response || typeof response !== 'object' ||
          (response as { plugin_id?: unknown }).plugin_id !== pluginId
        ) {
          throw new Error('Identity Vault credential inventory is unavailable.');
        }
        const records = (response as { fields?: unknown }).fields;
        if (!records || typeof records !== 'object' || Array.isArray(records)) {
          throw new Error('Identity Vault credential inventory is unavailable.');
        }
        const result: Record<string, CredentialStatus> = {};
        for (const field of fields) {
          result[field.key] = checkedCredentialStatus(
            (records as Record<string, unknown>)[field.key],
          );
        }
        if (active) setStatuses(result);
      } catch (exception) {
        if (active) {
          setError(exception instanceof Error
            ? exception.message : 'Identity Vault credential inventory is unavailable.');
        }
      }
    })();
    return () => { active = false; };
  }, [pluginId, fields]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Credentials</CardTitle>
        <CardDescription>Managed by Identity Vault. Ordinary plugin settings never contain secrets.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {!statuses && !error && <p role="status">Checking credential status...</p>}
        {statuses && fields.map((field) => (
          <CredentialField
            key={field.key}
            pluginId={pluginId}
            setting={field}
            status={statuses[field.key]}
            onReceipt={(next) => setStatuses((previous) =>
              previous ? { ...previous, [field.key]: next } : previous
            )}
          />
        ))}
      </CardContent>
    </Card>
  );
}

/** Form for editing a plugin's settings */
export function PluginSettingsForm({
  pluginId,
  onClose,
}: {
  pluginId: string;
  onClose?: () => void;
}) {
  const { values: settings, schema, loaded, modified, error, stored } = usePluginSettings(pluginId);
  const { updateSetting, savePluginSettings, resetPluginSettings, refreshSettings } = usePluginSettingsManager();

  useEffect(() => {
    void refreshSettings(pluginId);
  }, [pluginId, refreshSettings]);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    setSaveSuccess(false);
    const success = await savePluginSettings(pluginId);
    setSaving(false);
    if (success) {
      // Never auto-close: an edit entered while the save was in flight
      // must remain visible and unsaved rather than being discarded.
      setSaveSuccess(true);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    await resetPluginSettings(pluginId);
    setResetting(false);
  };

  // Group settings by category
  const groupedSettings = React.useMemo(() => {
    const groups: Record<string, SettingSchema[]> = {};
    for (const s of schema) {
      if (s.type === 'password') continue;
      const category = s.category || 'General';
      if (!groups[category]) groups[category] = [];
      groups[category].push(s);
    }
    // Sort within each group
    for (const category of Object.keys(groups)) {
      groups[category].sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
    }
    return groups;
  }, [schema]);
  const credentialFields = React.useMemo(
    () => schema.filter((field) => field.type === 'password'),
    [schema],
  );

  if (!loaded) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center p-8">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <span className="ml-2 text-sm text-muted-foreground">Loading settings...</span>
        </CardContent>
      </Card>
    );
  }

  if (error && schema.length === 0) {
    return (
      <Card>
        <CardContent className="p-8">
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {saveSuccess && !modified && (
        <Alert>
          <CheckCircle2 className="h-4 w-4" />
          <AlertDescription>Settings saved successfully!</AlertDescription>
        </Alert>
      )}

      {Object.entries(groupedSettings).map(([category, categoryFields]) => (
        <Card key={category}>
          <CardHeader>
            <CardTitle className="text-lg">{category}</CardTitle>
            <CardDescription>
              Configure {category.toLowerCase()} settings for this plugin
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {categoryFields.map((setting) => (
              <SettingField
                key={setting.key}
                setting={setting}
                value={settings[setting.key]}
                onChange={(value) => updateSetting(pluginId, setting.key, value)}
                readOnly={setting.readOnly}
              />
            ))}
          </CardContent>
        </Card>
      ))}

      {credentialFields.length > 0 && (
        <PluginCredentialsManager pluginId={pluginId} fields={credentialFields} />
      )}

      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          onClick={handleReset}
          disabled={resetting || (!stored && !modified)}
        >
          <RotateCcw className="mr-2 h-4 w-4" />
          {resetting ? 'Resetting...' : 'Reset to Defaults'}
        </Button>
        {onClose && (
          <Button variant="outline" onClick={onClose} disabled={saving || resetting || modified}>
            Done
          </Button>
        )}
        <Button onClick={handleSave} disabled={saving || !modified}>
          <Save className="mr-2 h-4 w-4" />
          {saving ? 'Saving...' : 'Save Settings'}
        </Button>
      </div>

      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
    </div>
  );
}

/** Badge showing restart requirement */
export function RestartRequiredBadge() {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 px-2 py-0.5 rounded-full">
      <AlertCircle className="h-3 w-3" />
      restart required
    </span>
  );
}