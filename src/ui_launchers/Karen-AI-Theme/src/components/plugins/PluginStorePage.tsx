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

import { usePluginStore } from '@/stores/PluginStore';
import type { PluginCategory } from '@/types/plugin';

import { CategoryFilter } from './CategoryFilter';
import { PluginGrid } from './PluginGrid';
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
    loading,
    error,
    searchParams,
    searchResponse,
    categories,
    trendingPlugins,
    trendingStatus,
    trendingError,
    installingPlugins,
    setSearchParams,
    searchPlugins,
    refreshPlugins,
    installPlugin,
    loadCategories,
    loadTrending,
    getPluginDetails,
    clearError,
  } = usePluginStore();

  const [activeTab, setActiveTab] = useState<PluginStoreTab>('browse');
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

  const installedPlugins = useMemo(() => {
    return Array.isArray(plugins)
      ? plugins.filter((plugin) => plugin.status === 'installed')
      : [];
  }, [plugins]);

  const selectedCategoryLabel = useMemo(() => {
    if (!selectedCategory) {
      return '';
    }

    const match = categories.find((category) => category.name === selectedCategory);

    return cleanString(match?.display_name) || cleanString(selectedCategory);
  }, [categories, selectedCategory]);

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
  }, [loadCategories, searchPlugins]);

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
      } catch (installError) {
        setOperationError(getErrorMessage(installError));
      }
    },
    [installPlugin],
  );

  const handleDetails = useCallback(
    (pluginId: string) => {
      setOperationError('');
      void getPluginDetails(pluginId);
    },
    [getPluginDetails],
  );

  const handleDiscover = useCallback(
    (pluginId: string) => {
      setOperationError('');
      void getPluginDetails(pluginId);
    },
    [getPluginDetails],
  );

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

  const handleRefresh = useCallback(() => {
    setOperationError('');
    void refreshPlugins();
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
      const response = await fetch('/api/plugins/store/' + encodeURIComponent(uninstallId) + '/installation', {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!response.ok) {
        const detail: unknown = await response.json().catch(() => null);
        const message = detail && typeof detail === 'object' ? (detail as { detail?: unknown }).detail : null;
        throw new Error(typeof message === 'string' ? message : 'Uninstall failed');
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
      const form = new FormData();
      form.append('plugin_id', uploadId);
      form.append('archive', uploadFile);
      const response = await fetch('/api/plugins/store/upload', {
        method: 'POST',
        credentials: 'include',
        body: form,
      });
      if (!response.ok) {
        const detail: unknown = await response.json().catch(() => null);
        const message = detail && typeof detail === 'object'
          ? (detail as { detail?: unknown }).detail
          : null;
        throw new Error(typeof message === 'string' ? message : 'Plugin upload failed');
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

              {categories.length > 0 && (
                <CategoryFilter
                  categories={categories}
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
              {loading ? (
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
                  loading={loading}
                  onDetails={handleDetails}
                  installingPlugins={installingPlugins}
                  emptyMessage="No installed plugins found"
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}