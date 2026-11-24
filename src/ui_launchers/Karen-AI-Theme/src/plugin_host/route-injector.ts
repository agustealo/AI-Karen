/**
 * Route_Injector — derives typed route/menu/widget entries from the plugin
 * catalog and exposes them via the `usePluginRoutes()` React hook.
 *
 * Design principles:
 * - `derivePluginRoutes` is a pure function: given a catalog snapshot it
 *   returns a fully-typed `PluginRoutes` object with no side-effects.
 * - Explicit manifest contributions always take precedence over
 *   convention-discovered defaults.
 * - When a GUI-capable plugin has no explicit sidebar contribution the
 *   injector synthesises a default `PluginMenuEntry` so the plugin still
 *   appears in the sidebar.
 * - `viewKey` values are derived deterministically from `pluginId + entryId`
 *   so they are stable across re-renders and catalog refreshes.
 * - Entries with an explicit `order` value are sorted ascending; entries
 *   without an explicit order are appended last, sorted alphabetically by
 *   label for determinism.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
 */

"use client";

import { useMemo } from 'react';
import { usePluginRegistry } from './registry';
import type { PluginCatalogEntry, MenuContribution } from './registry';

// ─── Public interfaces ────────────────────────────────────────────────────────

/**
 * A single route entry derived from a plugin's sidebar contribution.
 * Used to render navigation items in the sidebar "Plugins" group.
 *
 * Requirements: 6.1, 6.2
 */
export interface PluginRouteEntry {
  /** Stable view key derived from pluginId + entryId (e.g. "weather-query::sidebar-plugins-0") */
  viewKey: string;
  /** Canonical plugin ID */
  pluginId: string;
  /** Unique contribution entry ID */
  entryId: string;
  /** Display label for the navigation item */
  label: string;
  /** Relative icon path (undefined when not declared) */
  iconPath?: string;
  /** Explicit render order (null = auto-ordered) */
  order: number | null;
}

/**
 * A single menu entry for the sidebar navigation.
 * Extends PluginRouteEntry with optional subzone support.
 *
 * Requirements: 6.1, 6.2
 */
export interface PluginMenuEntry extends PluginRouteEntry {
  /** Optional sub-zone within the sidebar zone */
  subzone?: string;
  /** Whether this entry was synthesised from convention (true) or declared explicitly (false) */
  isDefault: boolean;
}

/**
 * A single widget entry for the dashboard.widgets zone.
 *
 * Requirements: 6.4
 */
export interface PluginWidgetEntry {
  /** Stable view key derived from pluginId + entryId */
  viewKey: string;
  /** Canonical plugin ID */
  pluginId: string;
  /** Unique contribution entry ID */
  entryId: string;
  /** Display label */
  label: string;
  /** Explicit render order (null = auto-ordered) */
  order: number | null;
}

/**
 * The complete set of plugin-derived route/menu/widget entries, grouped by zone.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
 */
export interface PluginRoutes {
  /**
   * Sidebar navigation entries (zone: sidebar.plugins).
   * Sorted: explicit order ascending, then auto-order alphabetically by label.
   * Requirements: 6.1, 6.2
   */
  sidebarEntries: PluginMenuEntry[];

  /**
   * Map from viewKey → pluginId for all sidebar entries.
   * Used by the dashboard to resolve which plugin to render for the active view.
   * Requirements: 4.2
   */
  viewMap: Record<string, string>;

  /**
   * Plugin Overview page entries (zone: page.plugins.overview).
   * Requirements: 6.3
   */
  overviewEntries: PluginRouteEntry[];

  /**
   * Settings page section entries (zone: page.settings.sections).
   * Requirements: 6.5
   */
  settingsEntries: PluginRouteEntry[];

  /**
   * Admin page tab entries (zone: page.admin.tabs or page.admin.subtabs).
   * Requirements: 6.5
   */
  adminEntries: PluginRouteEntry[];

  /**
   * Communications page tab entries (zone: page.communications.tabs).
   * Requirements: 6.5
   */
  commsEntries: PluginRouteEntry[];

  /**
   * Dashboard widget entries (zone: dashboard.widgets).
   * Requirements: 6.4
   */
  widgetEntries: PluginWidgetEntry[];
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

/**
 * Derives a stable, human-readable viewKey from a plugin ID and entry ID.
 * Replaces dots with dashes to keep the key URL-safe and readable.
 *
 * Requirements: 6.2
 */
function deriveViewKey(pluginId: string, entryId: string): string {
  // Normalise both parts: lowercase, replace dots/slashes with dashes
  const normPlugin = pluginId.toLowerCase().replace(/[./]/g, '-');
  const normEntry = entryId.toLowerCase().replace(/[./]/g, '-');
  return `${normPlugin}::${normEntry}`;
}

/**
 * Comparator that sorts entries with explicit order ascending,
 * then auto-order entries alphabetically by label (deterministic).
 *
 * Requirements: 6.1
 */
function sortEntries<T extends { order: number | null; label: string }>(entries: T[]): T[] {
  return [...entries].sort((a, b) => {
    const aHasOrder = a.order !== null;
    const bHasOrder = b.order !== null;

    // Both have explicit order → sort numerically
    if (aHasOrder && bHasOrder) return (a.order as number) - (b.order as number);

    // Only a has explicit order → a comes first
    if (aHasOrder) return -1;

    // Only b has explicit order → b comes first
    if (bHasOrder) return 1;

    // Neither has explicit order → sort alphabetically by label
    return a.label.localeCompare(b.label);
  });
}

/**
 * Converts a MenuContribution into a PluginRouteEntry.
 */
function contributionToRouteEntry(contribution: MenuContribution): PluginRouteEntry {
  return {
    viewKey: deriveViewKey(contribution.pluginId, contribution.entryId),
    pluginId: contribution.pluginId,
    entryId: contribution.entryId,
    label: contribution.label,
    iconPath: contribution.iconPath,
    order: contribution.order,
  };
}

/**
 * Converts a MenuContribution into a PluginMenuEntry (sidebar-specific).
 */
function contributionToMenuEntry(
  contribution: MenuContribution,
  isDefault: boolean
): PluginMenuEntry {
  return {
    ...contributionToRouteEntry(contribution),
    subzone: contribution.subzone,
    isDefault,
  };
}

/**
 * Converts a MenuContribution into a PluginWidgetEntry.
 */
function contributionToWidgetEntry(contribution: MenuContribution): PluginWidgetEntry {
  return {
    viewKey: deriveViewKey(contribution.pluginId, contribution.entryId),
    pluginId: contribution.pluginId,
    entryId: contribution.entryId,
    label: contribution.label,
    order: contribution.order,
  };
}

// ─── Core derivation function ─────────────────────────────────────────────────

/**
 * Derives a fully-typed `PluginRoutes` object from the plugin catalog.
 *
 * Processing rules per zone:
 * - `sidebar.plugins`:          explicit contributions + synthesised defaults for
 *                               GUI-capable plugins with no explicit sidebar entry.
 * - `page.plugins.overview`:    explicit contributions only.
 * - `page.settings.sections`:   explicit contributions only.
 * - `page.admin.tabs` /
 *   `page.admin.subtabs`:       explicit contributions only (merged into adminEntries).
 * - `page.communications.tabs`: explicit contributions only.
 * - `dashboard.widgets`:        explicit contributions only.
 *
 * All result arrays are sorted: explicit order ascending, auto-order last
 * but deterministic (alphabetical by label).
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
 *
 * @param plugins - The normalised plugin catalog from the registry.
 */
export function derivePluginRoutes(plugins: PluginCatalogEntry[]): PluginRoutes {
  const sidebarEntries: PluginMenuEntry[] = [];
  const overviewEntries: PluginRouteEntry[] = [];
  const settingsEntries: PluginRouteEntry[] = [];
  const adminEntries: PluginRouteEntry[] = [];
  const commsEntries: PluginRouteEntry[] = [];
  const widgetEntries: PluginWidgetEntry[] = [];

  // Track which plugins already have an explicit sidebar contribution so we
  // can synthesise a default only when none exists.
  const pluginsWithExplicitSidebar = new Set<string>();

  for (const plugin of plugins) {
    // Only process enabled, GUI-capable, prompt-first-valid plugins.
    if (!plugin.enabled || !plugin.has_gui || !plugin.promptFirstValid) continue;

    for (const contribution of plugin.menuContributions) {
      switch (contribution.zone) {
        case 'sidebar.plugins':
          sidebarEntries.push(contributionToMenuEntry(contribution, false));
          pluginsWithExplicitSidebar.add(plugin.id);
          break;

        case 'page.plugins.overview':
          overviewEntries.push(contributionToRouteEntry(contribution));
          break;

        case 'page.settings.sections':
          settingsEntries.push(contributionToRouteEntry(contribution));
          break;

        case 'page.admin.tabs':
        case 'page.admin.subtabs':
          adminEntries.push(contributionToRouteEntry(contribution));
          break;

        case 'page.communications.tabs':
          commsEntries.push(contributionToRouteEntry(contribution));
          break;

        case 'dashboard.widgets':
          widgetEntries.push(contributionToWidgetEntry(contribution));
          break;

        // Other zones (chat.toolbar, chat.context_panel, etc.) are not
        // surfaced as route entries — they are handled by their respective
        // host components directly.
        default:
          break;
      }
    }

    // Supplement sidebar with a convention-discovered default when the plugin
    // is GUI-capable but declared no explicit sidebar contribution.
    // Requirements: 6.2
    if (!pluginsWithExplicitSidebar.has(plugin.id)) {
      const defaultEntry: PluginMenuEntry = {
        viewKey: deriveViewKey(plugin.id, 'sidebar-plugins-default'),
        pluginId: plugin.id,
        entryId: `${plugin.id}.sidebar-plugins.default`,
        label: plugin.displayName,
        iconPath: undefined,
        order: null,
        isDefault: true,
      };
      sidebarEntries.push(defaultEntry);
    }
  }

  return {
    sidebarEntries: sortEntries(sidebarEntries),
    viewMap: Object.fromEntries(
      [...sidebarEntries].map((e) => [e.viewKey, e.pluginId])
    ),
    overviewEntries: sortEntries(overviewEntries),
    settingsEntries: sortEntries(settingsEntries),
    adminEntries: sortEntries(adminEntries),
    commsEntries: sortEntries(commsEntries),
    widgetEntries: sortEntries(widgetEntries),
  };
}

// ─── React hook ───────────────────────────────────────────────────────────────

/**
 * React hook that returns the current `PluginRoutes` derived from the
 * plugin registry catalog.
 *
 * The result is memoised: it only recomputes when the catalog changes.
 * Must be used inside a `<PluginRegistryProvider>`.
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
 *
 * @example
 * const { sidebarEntries, widgetEntries } = usePluginRoutes();
 */
export function usePluginRoutes(): PluginRoutes {
  const { getPluginsWithUI } = usePluginRegistry();
  return useMemo(() => derivePluginRoutes(getPluginsWithUI()), [getPluginsWithUI]);
}
