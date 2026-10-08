/**
  * Unified Plugin Loader — single authority for frontend plugin resolution.
  *
  * Design principles:
  * - Resolves components ONLY from installed packages in plugin_repo
  * - Uses generated import map for Next.js bundler safety
  * - Validates plugin state before loading
  * - No hardcoded dependencies - all loading goes through loader service
  * - Supports manifest-defined entry points and fallback conventions
  *
  * Requirements: 3.1, 3.2, 3.3, 3.4, 29, 30, 34, 35
  */

import React from 'react';
import { PLUGIN_IMPORT_MAP } from '@/plugin-import-map.generated';

// ─── Types ────────────────────────────────────────────────────────────────────

/** Minimal shape of a backend catalog entry needed by the loader. */
/** Minimal shape of a backend catalog entry needed by the loader. */
export interface LoaderPluginEntry {
  name: string;
  status: string;
  capabilities?: {
    provides_ui?: boolean;
  };
  ui_entry_points?: UIEntryPoint[];
}

/** A single UI entry point declared by a plugin. */
export interface UIEntryPoint {
  entry_id: string;
  component: string;
  zone: string;
  label?: string;
  order?: number;
}

type PluginImporter = () => Promise<{ default: React.ComponentType<Record<string, unknown>> }>;

/** Backend catalog response - can be direct array or wrapped */
// Direct array response from backend
interface BackendCatalog {
  status?: string;
  data?: {
    plugins: { plugin_id: string; status: string; has_component: boolean; ui_entry_points?: UIEntryPoint[]; capabilities?: { provides_ui?: boolean } }[];
    total?: number;
  };
  // Direct array response from backend
  length?: number;
  map?: Record<string, unknown>;
}

// ─── Fallback component factory ───────────────────────────────────────────────

// ─── Static Discovery Removed ──────────────────────────────────────────────────
// 
// Static discovery has been removed in favor of generated import maps only.
// All plugin components must now be installed in plugin_repo/ directory
// and discovered through the generated registry system.

/**
  * Import map from generated registry - only includes installed packages.
  * This replaces the old static discovery + legacy fallback approach.
  */
const generatedImportMap: Record<string, PluginImporter> = PLUGIN_IMPORT_MAP;

// Backward-compatible export: other frontend modules/tests import this symbol from loader.ts.
export { PLUGIN_IMPORT_MAP };

/**
 * Refresh the import map.
 *
 * In production this is a no-op because the map is a static module generated
 * at build/materialization time. We still invalidate the catalog cache so UI
 * state refreshes after lifecycle actions.
 */
export async function refreshImportMap(): Promise<void> {
  invalidateCatalogCache();
}

// ─── Backend Catalog Cache ───────────────────────────────────────────────────

let cachedCatalog: LoaderPluginEntry[] | null = null;
let catalogFetchPromise: Promise<LoaderPluginEntry[]> | null = null;
let lastCatalogFetch = 0;
const CATALOG_CACHE_TTL = 5 * 60 * 1000; // 5 minutes

/**
 * Fetch the backend plugin catalog.
 * Uses caching to avoid excessive API calls.
 */
async function fetchBackendCatalog(): Promise<LoaderPluginEntry[]> {
  const now = Date.now();

  // Return cached if still fresh
  if (cachedCatalog && now - lastCatalogFetch < CATALOG_CACHE_TTL) {
    return cachedCatalog;
  }

  // Reuse in-flight request
  if (catalogFetchPromise) {
    return catalogFetchPromise;
  }

  // Fetch from backend
  catalogFetchPromise = fetch('/api/extensions/list', {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  })
    .then((res) => {
      if (!res.ok) {
        throw new Error(`Backend catalog fetch failed: ${res.status}`);
      }
      return res.json() as Promise<BackendCatalog>;
    })
    .then((response) => {
      // Handle both wrapped and direct array responses
      const pluginsArray = Array.isArray(response) ? response : response.data?.plugins;
      if (!Array.isArray(pluginsArray)) {
        throw new Error('Invalid plugin catalog response');
      }
      cachedCatalog = pluginsArray.map((p) => ({
        name: p.name,
        status: p.status,
        capabilities: {
          provides_ui: p.has_component || p.capabilities?.provides_ui || false,
        },
      }));
      lastCatalogFetch = now;
      catalogFetchPromise = null;
      return cachedCatalog!;
    })
    .catch((error) => {
      console.warn('[PluginLoader] Failed to fetch backend catalog:', error);
      catalogFetchPromise = null;
      // Preserve failure as failure: an empty list means a successfully
      // discovered empty catalog, not a backend outage.
      throw error;
    });

  return catalogFetchPromise;
}

/**
 * Invalidate the catalog cache, forcing a fresh fetch on next access.
 */
export function invalidateCatalogCache(): void {
  cachedCatalog = null;
  lastCatalogFetch = 0;
}

// ─── Loader API ───────────────────────────────────────────────────────────────

/**
 * Normalises a plugin ID for import-map lookup.
 * Converts underscores to hyphens so "data_connector" matches "data-connector".
 */
export function normalizePluginId(id: string): string {
  return id.trim().toLowerCase().replace(/_/g, '-');
}

/**
 * Returns all valid UI entry points for a plugin from the backend catalog entry.
 * Falls back to a single synthetic entry when the catalog entry declares
 * `capabilities.provides_ui: true` but has no explicit `ui_entry_points`.
 * Returns an empty array when the plugin is not GUI-capable, disabled, or
 * not present in the import map.
 */
export function resolvePluginEntries(
  pluginId: string,
  catalog: LoaderPluginEntry[]
): UIEntryPoint[] {
  const normalised = normalizePluginId(pluginId);

  // First check if plugin is in import map - this is the authoritative source
  if (!(normalised in generatedImportMap)) return [];

  // Try to find entry in catalog for additional validation
  const entry = catalog.find(
    (p) => normalizePluginId(p.name) === normalised
  );

  // The import map proves only bundling, not backend authorization or
  // installation. A missing backend entry must never be treated as enabled.
  if (!entry) return [];

  // Validate catalog entry
  if (!['active', 'registered', 'enabled', 'loaded'].includes(entry.status)) return [];
  if (!entry.capabilities?.provides_ui) return [];

  if (entry.ui_entry_points && entry.ui_entry_points.length > 0) {
    return entry.ui_entry_points;
  }

  return [{ entry_id: 'default', component: normalised, zone: 'sidebar.plugins' }];
}

/**
 * Resolves a plugin ID to a React.lazy-wrapped component.
 *
 * Returns `null` when the plugin is not active, not GUI-capable, or not in
 * the generated import map. Accepts both hyphenated and underscored plugin IDs.
 * 
  * Uses only generated import maps from installed packages in plugin_repo.
 */
export function resolvePluginComponent(
  pluginId: string,
  catalog: LoaderPluginEntry[],
  entryId?: string
): React.LazyExoticComponent<React.ComponentType<Record<string, unknown>>> | null {
  const entries = resolvePluginEntries(pluginId, catalog);
  if (entries.length === 0) return null;

  if (entryId !== undefined) {
    const match = entries.find((e) => e.entry_id === entryId);
    if (!match) return null;
  }

  const normalised = normalizePluginId(pluginId);
  
  // Only use generated import map - no static fallback
  const importer = generatedImportMap[normalised];
  if (!importer) {
    console.warn(`[PluginLoader] Plugin ${normalised} not found in generated import map`);
    return null;
  }

  return React.lazy(importer);
}

/**
 * Async version of resolvePluginComponent that fetches the backend catalog.
 */
export async function resolvePluginComponentAsync(
  pluginId: string,
  entryId?: string
): Promise<React.LazyExoticComponent<React.ComponentType<Record<string, unknown>>> | null> {
  const catalog = await fetchBackendCatalog();
  return resolvePluginComponent(pluginId, catalog, entryId);
}

/** List plugin IDs that have a bundled importer entry. */
export function getRegisteredPluginIds(): string[] {
  return Object.keys(generatedImportMap).sort();
}

/**
  * Returns statistics about the plugin loader.
  */
export function getLoaderStats(): {
  generatedCount: number;
  totalCount: number;
  pluginIds: string[];
} {
  const generatedCount = Object.keys(generatedImportMap).length;
  return {
    generatedCount,
    totalCount: Object.keys(generatedImportMap).length,
    pluginIds: Object.keys(generatedImportMap),
  };
}
