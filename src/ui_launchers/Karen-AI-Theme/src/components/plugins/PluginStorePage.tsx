'use client';

/**
 * @file PluginStorePage.tsx
 * @description Main page for browsing and managing plugins from the plugin store.
 *
 * Store/API ownership:
 * - usePluginStore owns marketplace queries, install state, plugin details, and errors.
 * - This page coordinates UI controls only.
 * - Plugin lifecycle truth must stay in the backend/store, not inferred here.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Loader2,
  Package,
  PlugZap,
  RefreshCw,
  Star,
  TrendingUp,
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
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs';

import pluginStoreService from '@/lib/PluginStoreService';
import { usePluginStore } from '@/stores/PluginStore';
import type { PluginCategory } from '@/types/plugin';

import { CategoryFilter } from './CategoryFilter';
import { PluginGrid } from './PluginGrid';
import { PluginDetailsModal } from './PluginDetailsModal';
import { SearchBar } from './SearchBar';

type PluginStoreTab = 'browse' | 'trending' | 'installed';

const DEFAULT_BROWSE_EMPTY_MESSAGE =
  'No plugins found. Try adjusting your search or filters.';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const getErrorMessage = (error: unknown): string => {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  if (typeof error === 'string' && error.trim()) {
    return error.trim();
  }

  return 'Plugin operation failed.';
};

export default function PluginStorePage() {
  const {
    plugins,
    installedPlugins,
    installedPage,
    installedSearchResponse,
    installedLoading,
    installedError,
    loading,
    error,
    searchParams,
    searchResponse,
    categories,
    trendingPlugins,
    trendingStatus,
    trendingError,
    installingPlugins,
    selectedPlugin,
    detailsLoading,
    detailsError,
    setSearchParams,
    searchPlugins,
    loadInstalled,
    refreshPlugins,
    installPlugin,
    disablePlugin,
    loadCategories,
    loadTrending,
    getPluginDetails,
    clearSelectedPlugin,
    clearError,
  } = usePluginStore();

  const [activeTab, setActiveTab] = useState<PluginStoreTab>('browse');
  useEffect(() => {
    if (activeTab === 'trending' && trendingStatus === 'idle') {
      void loadTrending();
    }
  }, [activeTab, trendingStatus, loadTrending]);
  const [selectedCategory, setSelectedCategory] = useState<
    PluginCategory | undefined
  >(searchParams.category);
  const [operationError, setOperationError] = useState('');
  const [operationSuccess, setOperationSuccess] = useState('');
  const [uploadId, setUploadId] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uninstallId, setUninstallId] = useState('');
  const [uninstalling, setUninstalling] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const safeCategories = useMemo(() => (Array.isArray(categories) ? categories : []), [categories]);

  const selectedCategoryLabel = useMemo(() => {
    if (!selectedCategory) {
      return '';
    }

    const match = safeCategories.find((category) => category.name === selectedCategory);

    return cleanString(match?.display_name) || cleanString(selectedCategory);
  }, [safeCategories, selectedCategory]);

  const browseEmptyMessage = selectedCategory
    ? `No plugins found in ${selectedCategoryLabel || selectedCategory}`
    : DEFAULT_BROWSE_EMPTY_MESSAGE;

  useEffect(() => {
    /*
     * Initial marketplace hydration belongs to the store. The page calls the
     * existing store actions once and lets the store manage request/cache state.
     */
    void loadCategories();
    void searchPlugins();
    void loadInstalled();
  }, [loadCategories, searchPlugins, loadInstalled]);

  const handleSearch = useCallback(
    (params: typeof searchParams) => {
      setOperationError('');
      setSearchParams(params);

      /*
       * Keep the current store pattern: update params first, then ask the store
       * to search. Do not duplicate query construction in this component.
       */
      void searchPlugins();
    },
    [searchPlugins, setSearchParams],
  );

  const handleInstall = useCallback(
    async (pluginId: string, version?: string) => {
      setOperationError('');

      try {
        await installPlugin(pluginId, version);
        setDetailsOpen(false);
        clearSelectedPlugin();
      } catch (installError) {
        setOperationError(getErrorMessage(installError));
      }
    },
    [installPlugin, clearSelectedPlugin],
  );

  const handleDisable = useCallback(
    async (pluginId: string) => {
      setOperationError('');
      setOperationSuccess('');
      try {
        await disablePlugin(pluginId);
        setDetailsOpen(false);
        clearSelectedPlugin();
        setOperationSuccess(`Plugin '${pluginId}' disabled successfully.`);
      } catch (cause) {
        setOperationError(getErrorMessage(cause));
      }
    },
    [disablePlugin, clearSelectedPlugin],
  );

  const handleDetails = useCallback(
    (pluginId: string) => {
      setOperationError('');
      setDetailsOpen(true);
      void getPluginDetails(pluginId);
    },
    [getPluginDetails],
  );

  const handleDetailsOpenChange = useCallback(
    (open: boolean) => {
      setDetailsOpen(open);
      if (!open) clearSelectedPlugin();
    },
    [clearSelectedPlugin],
  );

  const handleDiscover = handleDetails;

  const handleCategoryChange = useCallback(
    (category: PluginCategory | undefined) => {
      setSelectedCategory(category);
      setSearchParams({
        category,
        page: 1,
      });
      void searchPlugins();
    },
    [searchPlugins, setSearchParams],
  );

  const handlePageChange = useCallback(
    (page: number) => {
      setSearchParams({ page });
      void searchPlugins();
    },
    [searchPlugins, setSearchParams],
  );

  const handleRefresh = useCallback(async () => {
    setOperationError('');
    try {
      await refreshPlugins();
    } catch (cause) {
      setOperationError(getErrorMessage(cause));
    }
  }, [refreshPlugins]);

  const handleUninstall = useCallback(async () => {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(uninstallId)) {
      setOperationError('Choose a valid installed plugin ID.');
      return;
    }
    if (!window.confirm('Uninstall plugin ' + uninstallId + '? Its installed package will be removed.')) return;
    setUninstalling(true);
    setOperationError('');
    setOperationSuccess('');
    try {
      const result = await pluginStoreService.uninstallPlugin(uninstallId);
      if (result?.success !== true || result.uninstalled !== true) {
        throw new Error('Plugin uninstall did not confirm package removal.');
      }
      setUninstallId('');
      try {
        await refreshPlugins();
        setOperationSuccess('Plugin package uninstalled successfully.');
      } catch (refreshError) {
        setOperationError('Plugin package was uninstalled, but the plugin list could not be refreshed: ' + getErrorMessage(refreshError));
      }
    } catch (cause) {
      setOperationError(getErrorMessage(cause));
    } finally {
      setUninstalling(false);
    }
  }, [uninstallId, refreshPlugins]);

  const handleUpload = useCallback(async () => {
    if (!uploadFile || !/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(uploadId)) {
      setOperationError('Select a ZIP file and a valid plugin ID.');
      return;
    }
    setUploading(true);
    setOperationError('');
    setOperationSuccess('');
    try {
      const result = await pluginStoreService.uploadPlugin(uploadId, uploadFile);
      if (result?.success !== true || result.installed !== true || result.enabled !== false) {
        throw new Error('Plugin upload did not confirm a disabled installation.');
      }
      setUploadFile(null);
      setUploadId('');
      try {
        await refreshPlugins();
        setOperationSuccess('Plugin package installed. It remains disabled until explicitly enabled.');
      } catch (refreshError) {
        setOperationError('Plugin package was installed disabled, but the plugin list could not be refreshed: ' + getErrorMessage(refreshError));
      }
    } catch (cause) {
      setOperationError(getErrorMessage(cause));
    } finally {
      setUploading(false);
    }
  }, [uploadFile, uploadId, refreshPlugins]);

  const handleBrowseFromInstalled = useCallback(() => {
    setActiveTab('browse');
    void searchPlugins();
  }, [searchPlugins]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center space-x-3">
          <PlugZap className="h-8 w-8 text-primary" aria-hidden="true" />

          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              Plugin Store
            </h2>
            <p className="text-sm text-muted-foreground">
              Discover and install plugins to enhance Karen AI capabilities.
            </p>
          </div>
        </div>

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={loading}
        >
          <RefreshCw
            className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`}
            aria-hidden="true"
          />
          Refresh
        </Button>
      </div>

      {(error || operationError) && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{operationError || error}</span>

            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setOperationError('');
                clearError();
              }}
              className="h-7 self-start sm:self-auto"
            >
              Dismiss
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Upload a Plugin</CardTitle>
          <CardDescription>
            Upload a ZIP package manually. Karen validates the package and installs it disabled.
            Enabling it is a separate action.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Plugin ID
            <input className="rounded border bg-background px-3 py-2" value={uploadId}
              onChange={(event) => setUploadId(event.target.value)}
              placeholder="plugin-id" aria-label="Plugin ID" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Package (.zip)
            <input type="file" accept=".zip,application/zip" aria-label="Plugin ZIP package"
              onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} />
          </label>
          <Button type="button" onClick={() => void handleUpload()} disabled={uploading || !uploadFile}>
            {uploading ? 'Uploading...' : 'Upload & Install'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Uninstall a Plugin</CardTitle>
          <CardDescription>Disable the plugin first, then remove its installed package. This does not delete bundled source files in free_plugins.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">Installed plugin ID
            <select className="rounded border bg-background px-3 py-2" value={uninstallId}
              onChange={(event) => setUninstallId(event.target.value)}>
              <option value="">Choose a plugin</option>
              {installedPlugins.map(plugin =>
                <option key={plugin.id} value={plugin.id}>{plugin.name}</option>)}
            </select>
          </label>
          <Button type="button" variant="destructive" disabled={!uninstallId || uninstalling}
            onClick={() => void handleUninstall()}>
            {uninstalling ? 'Uninstalling...' : 'Uninstall plugin'}
          </Button>
        </CardContent>
      </Card>

      {operationSuccess && <p role="status" className="text-sm text-green-700 dark:text-green-400">{operationSuccess}</p>}

      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as PluginStoreTab)}
        className="w-full"
      >
        <TabsList className="grid w-full grid-cols-3 lg:w-[400px]">
          <TabsTrigger value="browse">
            <Package className="mr-2 h-4 w-4" aria-hidden="true" />
            Browse
          </TabsTrigger>

          <TabsTrigger value="trending">
            <TrendingUp className="mr-2 h-4 w-4" aria-hidden="true" />
            Trending
          </TabsTrigger>

          <TabsTrigger value="installed">
            <Star className="mr-2 h-4 w-4" aria-hidden="true" />
            Installed
          </TabsTrigger>
        </TabsList>

        <TabsContent value="browse" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Discover Plugins</CardTitle>
              <CardDescription>
                Browse the marketplace and install plugins to extend Karen
                AI&apos;s capabilities.
              </CardDescription>
            </CardHeader>

            <CardContent className="space-y-4">
              <div className="flex flex-col gap-4 lg:flex-row">
                <div className="flex-1">
                  <SearchBar
                    params={searchParams}
                    onSearch={handleSearch}
                    placeholder="Search for plugins..."
                  />
                </div>
              </div>

              {safeCategories.length > 0 && (
                <CategoryFilter
                  categories={safeCategories}
                  selectedCategory={selectedCategory}
                  onCategoryChange={handleCategoryChange}
                />
              )}

              <PluginGrid
                plugins={plugins}
                loading={loading}
                total={searchResponse?.total}
                page={searchParams.page}
                perPage={searchParams.per_page}
                totalPages={searchResponse?.total_pages}
                hasNext={searchResponse?.has_next}
                hasPrev={(searchParams.page ?? 1) > 1}
                onPageChange={handlePageChange}
                onInstall={handleInstall}
                onDisable={handleDisable}
                onDetails={handleDetails}
                onDiscover={handleDiscover}
                installingPlugins={installingPlugins}
                emptyMessage={browseEmptyMessage}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="trending" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Trending Plugins</CardTitle>
              <CardDescription>
                Popular plugins being installed by the community.
              </CardDescription>
            </CardHeader>

            <CardContent>
              {trendingStatus === 'loading' ? (
                <div
                  className="flex flex-col items-center justify-center py-12"
                  role="status"
                  aria-live="polite"
                >
                  <Loader2
                    className="mb-4 h-8 w-8 animate-spin text-primary"
                    aria-hidden="true"
                  />
                  <p className="text-sm text-muted-foreground">
                    Loading trending plugins...
                  </p>
                </div>
              ) : trendingStatus === 'unavailable' || trendingStatus === 'error' ? (
                <div className="flex flex-col items-center justify-center gap-3 py-12 text-center" role="status">
                  <TrendingUp className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
                  <p className="text-sm text-muted-foreground">{trendingError}</p>
                  {trendingStatus === 'error' && <Button variant="outline" onClick={() => void loadTrending()}>Retry trending</Button>}
                </div>
              ) : trendingPlugins.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <TrendingUp
                    className="mb-4 h-12 w-12 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <p className="text-sm text-muted-foreground">
                    No trending plugins available yet.
                  </p>
                </div>
              ) : (
                <PluginGrid
                  plugins={trendingPlugins}
                  loading={loading}
                  onInstall={handleInstall}
                  onDisable={handleDisable}
                  onDetails={handleDetails}
                  onDiscover={handleDiscover}
                  installingPlugins={installingPlugins}
                  emptyMessage="No trending plugins found"
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="installed" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Installed Plugins</CardTitle>
              <CardDescription>
                Manage plugins that are currently installed on your system.
              </CardDescription>
            </CardHeader>

            <CardContent>
              {installedError ? (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                  <AlertTitle>Installed plugins unavailable</AlertTitle>
                  <AlertDescription>{installedError}</AlertDescription>
                </Alert>
              ) : installedLoading ? (
                <div
                  className="flex flex-col items-center justify-center py-12"
                  role="status"
                  aria-live="polite"
                >
                  <Loader2
                    className="mb-4 h-8 w-8 animate-spin text-primary"
                    aria-hidden="true"
                  />
                  <p className="text-sm text-muted-foreground">
                    Loading installed plugins...
                  </p>
                </div>
              ) : installedPlugins.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Package
                    className="mb-4 h-12 w-12 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <p className="mb-2 text-sm text-muted-foreground">
                    No plugins installed yet.
                  </p>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleBrowseFromInstalled}
                  >
                    Browse Plugin Store
                  </Button>
                </div>
              ) : (
                <PluginGrid
                  plugins={installedPlugins}
                  loading={installedLoading}
                  total={installedSearchResponse?.total}
                  page={installedPage}
                  perPage={installedSearchResponse?.per_page}
                  totalPages={installedSearchResponse?.total_pages}
                  hasNext={installedSearchResponse?.has_next}
                  hasPrev={installedPage > 1}
                  onPageChange={(page) => { void loadInstalled(page); }}
                  onInstall={handleInstall}
                  onDisable={handleDisable}
                  onDetails={handleDetails}
                  installingPlugins={installingPlugins}
                  emptyMessage="No installed plugins found"
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <PluginDetailsModal
        open={detailsOpen}
        onOpenChange={handleDetailsOpenChange}
        details={selectedPlugin}
        loading={detailsLoading}
        error={detailsError}
        installing={Boolean(selectedPlugin?.plugin && installingPlugins.has(selectedPlugin.plugin.id))}
        onInstall={() => {
          const plugin = selectedPlugin?.plugin;
          if (plugin) void handleInstall(plugin.id, plugin.version);
        }}
        onEnable={() => {
          const plugin = selectedPlugin?.plugin;
          if (plugin) void handleInstall(plugin.id);
        }}
        onDisable={() => {
          const plugin = selectedPlugin?.plugin;
          if (plugin) void handleDisable(plugin.id);
        }}
      />
    </div>
  );
}