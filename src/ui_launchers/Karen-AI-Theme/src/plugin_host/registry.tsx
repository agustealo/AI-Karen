"use client";

/**
 * Dynamic_Plugin_Registry — React context providing the authoritative frontend
 * view of the backend plugin catalog.
 *
 * Design principles:
 * - Single source of truth: the backend catalog at /api/extensions/list
 * - Safe normalization: maps diverse backend manifests into consistent TS interfaces
 * - Governance-first: respects RBAC and capability flags
 */
import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from 'react';
import { apiClient, ApiError } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';

// ─── Interfaces ──────────────────────────────────────────────────────────────

/** Internal frontend states for a plugin component */
export type FrontendMountState = 'idle' | 'loading' | 'mounted' | 'error' | 'uninstalled';

/**
 * Module-level map tracking frontend mount state per plugin ID.
 * Updated by PluginHost (loader resolution), PluginErrorBoundary (componentDidCatch),
 * and Suspense onLoad callbacks.
 *
 * Exported so PluginHost and PluginErrorBoundary can update it.
 * Requirements: 9.3, 9.4
 */
export const mountStateRegistry = new Map<string, { state: FrontendMountState; errorMessage?: string }>();

/**
 * Updates the frontend mount state for a plugin.
 * Call this from PluginHost and PluginErrorBoundary.
 *
 * Requirements: 9.3, 9.4
 */
export function setPluginMountState(
  pluginId: string,
  state: FrontendMountState,
  errorMessage?: string
): void {
  mountStateRegistry.set(pluginId, { state, errorMessage });
}

// ─── Backend catalog shape (raw API response) ─────────────────────────────────

/** Raw entry returned by /api/extensions/list */
interface BackendPluginEntry {
  name: string;
  display_name?: string;
  description?: string;
  version: string;
  status: string;
  loaded_at?: string | null;
  error_message?: string | null;
  /** Capability flags from the manifest */
  capabilities?: {
    provides_ui?: boolean;
    provides_api?: boolean;
    provides_background_tasks?: boolean;
    provides_webhooks?: boolean;
  };
  /** Whether the plugin has a UI component */
  has_component?: boolean;
  /** UI entry points */
  ui_entry_points?: Array<{
    entry_id: string;
    component: string;
    zone: string;
    label?: string;
    order?: number;
    subzone?: string;
    icon_path?: string;
  }>;
  /** UI section from plugin_manifest.json */
  ui?: {
    has_component?: boolean;
    component_id?: string;
    purpose?: string;
    menu?: Array<{
      placement?: string;
      label?: string;
      icon?: string;
      order?: number;
      subzone?: string;
    }>;
  };
  /** RBAC config */
  rbac?: {
    allowed_roles?: string[];
    default_enabled?: boolean;
  };
  tags?: string[];
  purpose?: string;
  actions?: unknown[];
  invocation_guidance?: unknown;
}

/** A single UI contribution slot declared by a plugin. */
export interface MenuContribution {
  pluginId: string;
  entryId: string;
  label: string;
  zone: string;
  order: number | null;
  iconPath?: string;
  subzone?: string;
}

/** Definition of a plugin's UI capabilities */
export interface PluginUIManifest {
  pluginId: string;
  componentId: string;
  purpose?: string;
  displayName?: string;
}

/** A single UI contribution slot declared by a plugin. */
export interface PluginUIContribution {
  pluginId: string;
  zone: string;
  manifest: PluginUIManifest;
}

/** Normalised frontend catalog entry. */
export interface PluginCatalogEntry {
  /** Canonical plugin ID */
  id: string;
  displayName: string;
  description: string;
  version: string;
  /** Whether the plugin is active/enabled on the backend */
  enabled: boolean;
  /** Whether the plugin declares a GUI component */
  has_gui: boolean;
  /** Whether the plugin passes prompt-first validation */
  promptFirstValid: boolean;
  /** Normalised UI manifest (present when has_gui is true) */
  uiManifest?: PluginUIManifest;
  /** Menu/hook-zone contributions */
  menuContributions: MenuContribution[];
  /** Raw backend status string */
  rawStatus: string;
  /** RBAC: roles allowed to see this plugin's UI. Empty = allow all. */
  allowedRoles: string[];
}

// ─── Registry state & context value ──────────────────────────────────────────

export interface PluginRegistryState {
  /** All normalised catalog entries */
  plugins: PluginCatalogEntry[];
  loading: boolean;
  error: string | null;
}

export interface PluginRegistryContextValue extends PluginRegistryState {
  /** Returns plugins that are enabled, GUI-capable, and prompt-first valid */
  getPluginsWithUI(): PluginCatalogEntry[];
  /** Looks up a single plugin by ID */
  getPlugin(pluginId: string): PluginCatalogEntry | undefined;
  /** Returns all menu contributions for a given hook zone */
  getContributionsByZone(zone: string): MenuContribution[];
  /** Re-fetches the catalog from the backend */
  refresh(): Promise<void>;
}

// ─── Context ──────────────────────────────────────────────────────────────────

const PluginRegistryContext = createContext<PluginRegistryContextValue | null>(null);

// ─── Normalisation helpers ────────────────────────────────────────────────────

const PLACEMENT_TO_ZONE: Record<string, string> = {
  sidebar: 'sidebar.plugins',
  'sidebar.plugins': 'sidebar.plugins',
  'sidebar-plugins': 'sidebar.plugins',
  'sidebar-settings': 'sidebar.settings',
  'sidebar-admin': 'sidebar.admin',
  'sidebar-communications': 'sidebar.communications',
  'communications-center': 'page.communications.tabs',
  'application-settings': 'page.settings.sections',
  'admin-settings': 'page.admin.sections',
  'plugin-overview': 'page.plugins.overview',
  dashboard: 'page.dashboard.sections',
};

/**
 * Determines whether a backend entry passes prompt-first validation.
 */
function isPromptFirstValid(entry: BackendPluginEntry): boolean {
  if (Array.isArray(entry.tags) && entry.tags.includes('prompt-first')) return true;
  if (typeof entry.purpose === 'string' && entry.purpose.trim().length > 0) return true;
  if (Array.isArray(entry.actions) && entry.actions.length > 0) return true;
  if (entry.invocation_guidance && typeof entry.invocation_guidance === 'object') return true;
  if (entry.capabilities?.provides_ui === true || entry.has_component === true) return true;
  if (Array.isArray(entry.ui_entry_points) && entry.ui_entry_points.length > 0) return true;
  return false;
}

/** Normalises a raw backend entry into a PluginCatalogEntry. */
function normaliseEntry(raw: BackendPluginEntry): PluginCatalogEntry {
  const id = raw.name;
  // The canonical runtime projects enabled plugins using the "enabled"
  // lifecycle state; "active" and "registered" are compatible states.
  const enabled = ['active', 'registered', 'enabled', 'loaded'].includes(raw.status);
  const has_gui =
    raw.capabilities?.provides_ui === true ||
    raw.ui?.has_component === true ||
    raw.has_component === true ||
    (Array.isArray(raw.ui_entry_points) && raw.ui_entry_points.length > 0);

  const menuContributions: MenuContribution[] = [];

  // Map backend menu items
  if (raw.ui?.menu) {
    raw.ui.menu.forEach((m, idx) => {
      menuContributions.push({
        pluginId: id,
        entryId: `${id}-menu-${idx}`,
        label: m.label || raw.display_name || id,
        zone: PLACEMENT_TO_ZONE[m.placement || 'sidebar'] || 'sidebar.plugins',
        order: m.order ?? null,
        iconPath: m.icon,
        subzone: m.subzone,
      });
    });
  }

  // Handle entry points from modern extensions API
  if (Array.isArray(raw.ui_entry_points)) {
    raw.ui_entry_points.forEach((ep) => {
        menuContributions.push({
            pluginId: id,
            entryId: ep.entry_id,
            label: ep.label || raw.display_name || id,
            zone: ep.zone || 'sidebar.plugins',
            order: ep.order ?? null,
            subzone: ep.subzone,
            iconPath: ep.icon_path
        });
    });
  }

  return {
    id,
    displayName: raw.display_name || id.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    description: raw.description || 'No description provided.',
    version: raw.version,
    enabled,
    has_gui,
    promptFirstValid: isPromptFirstValid(raw),
    rawStatus: raw.status,
    allowedRoles: raw.rbac?.allowed_roles || [],
    menuContributions,
    uiManifest: has_gui
      ? {
          pluginId: id,
          componentId: raw.ui?.component_id || id,
          purpose: raw.ui?.purpose || raw.description,
          displayName: raw.display_name || id,
        }
      : undefined,
  };
}

// ─── Provider Component ───────────────────────────────────────────────────────

export function PluginRegistryProvider({ children }: { children: ReactNode }) {
  const { user, isLoading: authLoading } = useAuth();
  const generation = useRef(0);
  const identity = user ? `${user.tenant_id}:${user.user_id}:${[...(user.roles || []), ...(user.permissions || [])].sort().join(',')}` : null;
  const [state, setState] = useState<PluginRegistryState>({
    plugins: [],
    loading: true,
    error: null,
  });

  const fetchCatalog = useCallback(async () => {
    const requestGeneration = ++generation.current;
    if (!identity || authLoading) {
      setState({ plugins: [], loading: false, error: null });
      return;
    }
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      // The plugin catalog is tenant- and RBAC-scoped. Send the same
      // authenticated context as the other governed runtime endpoints.
      const response = await apiClient.get<unknown>('/api/extensions/list');
      const raw =
        Array.isArray(response)
          ? response
          : response && typeof response === 'object'
            ? (response as Record<string, unknown>).plugins ??
              (response as Record<string, unknown>).extensions
            : undefined;

      // Missing content is not an empty catalog. Preserve the last known
      // catalog while reporting a real backend contract failure.
      if (
        !Array.isArray(raw) ||
        !raw.every(
          (entry): entry is BackendPluginEntry =>
            entry !== null &&
            typeof entry === 'object' &&
            typeof entry.name === 'string' &&
            entry.name.length > 0 &&
            typeof entry.status === 'string' &&
            typeof entry.version === 'string',
        )
      ) {
        throw new Error('Plugin catalog unavailable: backend returned an invalid response.');
      }

      if (requestGeneration !== generation.current) return;
      const normalised = raw.map(normaliseEntry);
      setState({ plugins: normalised, loading: false, error: null });
      console.log(`[PluginRegistry] Loaded ${normalised.length} plugins from backend.`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load plugin catalog';
      if (requestGeneration !== generation.current) return;
      const authorizationFailed = err instanceof ApiError && (err.status === 401 || err.status === 403);
      setState((prev) => ({ ...prev, plugins: authorizationFailed ? [] : prev.plugins, loading: false, error: message }));
    }
  }, [identity, authLoading]);

  useEffect(() => {
    fetchCatalog();
  }, [fetchCatalog]);

  const getPluginsWithUI = useCallback(() => {
    const userRoles = user?.permissions || [];
    return state.plugins.filter((p) => {
      // Must be enabled, have UI, and pass prompt-first validation
      if (!p.enabled || !p.has_gui || !p.promptFirstValid) return false;

      // Must pass RBAC check
      if (p.allowedRoles.length === 0) return true;
      return p.allowedRoles.some((role) => userRoles.includes(role));
    });
  }, [state.plugins, user?.permissions]);

  const getPlugin = useCallback(
    (pluginId: string) => state.plugins.find((p) => p.id === pluginId),
    [state.plugins]
  );

  const getContributionsByZone = useCallback(
    (zone: string) => {
      const userRoles = user?.permissions || [];
      const contributions: MenuContribution[] = [];

      state.plugins.forEach((p) => {
        // RBAC check
        const hasAccess =
          p.allowedRoles.length === 0 || p.allowedRoles.some((role) => userRoles.includes(role));

        if (hasAccess && p.enabled) {
          p.menuContributions.forEach((c) => {
            if (c.zone === zone) contributions.push(c);
          });
        }
      });

      return contributions.sort((a, b) => {
        const aHasOrder = a.order !== null;
        const bHasOrder = b.order !== null;
        if (aHasOrder && bHasOrder) return (a.order as number) - (b.order as number);
        if (aHasOrder) return -1;
        if (bHasOrder) return 1;
        return a.label.localeCompare(b.label);
      });
    },
    [state.plugins, user?.permissions]
  );

  const contextValue = useMemo(
    () => ({
      ...state,
      getPluginsWithUI,
      getPlugin,
      getContributionsByZone,
      refresh: fetchCatalog,
    }),
    [state, getPluginsWithUI, getPlugin, getContributionsByZone, fetchCatalog]
  );

  return (
    <PluginRegistryContext.Provider value={contextValue}>
      {children}
    </PluginRegistryContext.Provider>
  );
}

// ─── Hook ────────────────────────────────────────────────────────────────────

/**
 * authoritative hook for accessing the Karen AI plugin catalog.
 * must be used within a <PluginRegistryProvider>.
 */
export function usePluginRegistry(): PluginRegistryContextValue {
  const ctx = useContext(PluginRegistryContext);
  if (!ctx) {
    throw new Error('usePluginRegistry must be used within a PluginRegistryProvider');
  }
  return ctx;
}

/**
 * Returns health and availability status for a single plugin.
 */
export function usePluginHealth(pluginId: string) {
  const { getPlugin } = usePluginRegistry();
  const { user } = useAuth();
  
  const entry = getPlugin(pluginId);
  const mount = mountStateRegistry.get(pluginId);
  
  const backendState = entry?.rawStatus || 'uninstalled';
  const frontendMountState = mount?.state || 'idle';
  const errorMessage = mount?.errorMessage;
  
  const userRoles = user?.permissions || [];
  const allowedRoles = entry?.allowedRoles || [];
  const permissionVisible = allowedRoles.length === 0 || userRoles.some((r) => allowedRoles.includes(r));

  return {
    pluginId,
    backendState,
    frontendMountState,
    permissionVisible,
    ...(errorMessage !== undefined ? { errorMessage } : {}),
  };
}
