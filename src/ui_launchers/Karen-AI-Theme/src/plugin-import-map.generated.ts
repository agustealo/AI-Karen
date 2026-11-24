/**
 * Generated plugin import map (frontend).
 *
 * Single loading authority: `plugin_host/loader.ts` must import from here and
 * resolve ONLY installed UI packages under `src/plugin_repo/<plugin-id>/`.
 */
import type React from 'react';

export type PluginImporter = () => Promise<{
  default: React.ComponentType<Record<string, unknown>>;
}>;

export type PluginImportMap = Record<string, PluginImporter>;

export const PLUGIN_IMPORT_MAP: PluginImportMap = {
  "content-intelligence": () => import("@/plugin_repo/content-intelligence/ContentIntelligencePage"),
  "file-explorer": () => import("@/plugin_repo/file-explorer/FileExplorerPage"),
  "intelligent-search": () => import("@/plugin_repo/intelligent-search/IntelligentSearchPage"),
  "time-query": () => import("@/plugin_repo/time-query/TimeQueryPage"),
};
