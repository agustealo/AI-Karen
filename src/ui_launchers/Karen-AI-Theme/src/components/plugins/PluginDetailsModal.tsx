import React, { useMemo } from 'react';
import Image from 'next/image';
import {
  Calendar,
  CheckCircle2,
  Download,
  GitBranch,
  Loader2,
  Package,
  Shield,
  Star,
  User,
  XCircle,
} from 'lucide-react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import type { PluginDetails } from '@/types/plugin';
import { cn } from '@/lib/utils';

import { PluginStatusBadge } from './PluginStatusBadge';

interface PluginDetailsModalProps {
  details: PluginDetails | null;
  loading?: boolean;
  error?: string | null;
  installing?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInstall?: () => void;
  onEnable?: () => void;
  onDisable?: () => void;
}

type ExternalLinkConfig = {
  label: string;
  url: string;
  icon: React.ReactNode;
};

const DEFAULT_PLUGIN_TITLE = 'Untitled Plugin';
const DEFAULT_PLUGIN_DESCRIPTION = 'No description provided.';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const getSafeUrl = (value: unknown): string => {
  const rawUrl = cleanString(value);

  if (!rawUrl) {
    return '';
  }

  try {
    const parsed = new URL(rawUrl);

    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.toString();
    }
  } catch {
    return '';
  }

  return '';
};

const openExternalUrl = (url: string): void => {
  if (!url || typeof window === 'undefined') {
    return;
  }

  window.open(url, '_blank', 'noopener,noreferrer');
};

const getPluginTitle = (plugin: NonNullable<PluginDetails['plugin']>): string => {
  return (
    cleanString(plugin.display_name) ||
    cleanString(plugin.name) ||
    cleanString(plugin.id) ||
    DEFAULT_PLUGIN_TITLE
  );
};

const getPluginDescription = (
  plugin: NonNullable<PluginDetails['plugin']>,
): string => {
  return cleanString(plugin.description) || DEFAULT_PLUGIN_DESCRIPTION;
};

const getPluginAuthor = (plugin: NonNullable<PluginDetails['plugin']>): string => {
  return cleanString(plugin.author) || 'Unknown author';
};

const getPluginVersion = (plugin: NonNullable<PluginDetails['plugin']>): string => {
  return cleanString(plugin.version) || 'unknown';
};

const getInstalledDateLabel = (value: unknown): string => {
  const rawDate = cleanString(value);

  if (!rawDate) {
    return '';
  }

  const parsed = new Date(rawDate);

  if (Number.isNaN(parsed.getTime())) {
    return '';
  }

  return parsed.toLocaleDateString();
};

const getRatingLabel = (plugin: NonNullable<PluginDetails['plugin']>): string => {
  const rating = plugin.rating;

  if (typeof rating !== 'number' || !Number.isFinite(rating)) {
    return '';
  }

  return rating.toFixed(1);
};

const getRatingCountLabel = (plugin: NonNullable<PluginDetails['plugin']>): string => {
  const ratingCount = plugin.rating_count;

  if (typeof ratingCount !== 'number' || !Number.isFinite(ratingCount)) {
    return '0';
  }

  return Math.max(0, Math.floor(ratingCount)).toLocaleString();
};

const getDownloadLabel = (plugin: NonNullable<PluginDetails['plugin']>): string => {
  const downloads = plugin.downloads;

  if (typeof downloads !== 'number' || !Number.isFinite(downloads)) {
    return '';
  }

  return Math.max(0, Math.floor(downloads)).toLocaleString();
};

const getUniqueStrings = (values: unknown): string[] => {
  if (!Array.isArray(values)) {
    return [];
  }

  const seen = new Set<string>();

  return values
    .map((value) => cleanString(value))
    .filter((value) => {
      const normalized = value.toLowerCase();

      if (!value || seen.has(normalized)) {
        return false;
      }

      seen.add(normalized);
      return true;
    });
};

const isPluginCompatible = (plugin: NonNullable<PluginDetails['plugin']>): boolean => {
  // Only the backend catalog decides compatibility. Do not reinterpret
  // manifest version bounds in the presentation layer.
  return plugin.status !== 'incompatible';
};

export function PluginDetailsModal({
  details,
  loading = false,
  error = null,
  installing = false,
  open,
  onOpenChange,
  onInstall,
  onEnable,
  onDisable,
}: PluginDetailsModalProps) {
  // All React hooks must be called unconditionally at the top level
  const dependencies = useMemo(
    () => getUniqueStrings(details?.plugin?.dependencies),
    [details?.plugin?.dependencies],
  );
  const tags = useMemo(() => getUniqueStrings(details?.plugin?.tags), [details?.plugin?.tags]);
  const externalLinks = useMemo<ExternalLinkConfig[]>(() => {
    const links: ExternalLinkConfig[] = [];
    const plugin = details?.plugin;

    if (!plugin) {
      return links;
    }

    const homepageUrl = getSafeUrl(plugin.homepage_url);
    const repositoryUrl = getSafeUrl(plugin.repository_url);
    const marketplaceUrl = getSafeUrl(plugin.marketplace_url);

    if (homepageUrl) {
      links.push({
        label: 'Homepage',
        url: homepageUrl,
        icon: 'external-link',
      });
    }

    if (repositoryUrl) {
      links.push({
        label: 'Repository',
        url: repositoryUrl,
        icon: 'github',
      });
    }

    if (marketplaceUrl) {
      links.push({
        label: 'Marketplace',
        url: marketplaceUrl,
        icon: 'shopping-bag',
      });
    }

    return links;
  }, [details?.plugin]);

  // Keep the dialog mounted through pending and failed lookups. A details
  // request must never turn Manage into a silent no-op.
  if (!details?.plugin) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Plugin details</DialogTitle>
            <DialogDescription>
              {loading ? 'Loading plugin information...' : error || 'Plugin details are unavailable.'}
            </DialogDescription>
          </DialogHeader>
          {loading && <Loader2 className="h-5 w-5 animate-spin" aria-label="Loading plugin details" />}
        </DialogContent>
      </Dialog>
    );
  }

  const plugin = details.plugin;

  // Computed values (not hooks)
  const title = getPluginTitle(plugin);
  const description = getPluginDescription(plugin);
  const author = getPluginAuthor(plugin);
  const version = getPluginVersion(plugin);
  const safeIconUrl = getSafeUrl(plugin?.icon);
  const installedDateLabel = getInstalledDateLabel(plugin?.installed_at);
  const ratingLabel = getRatingLabel(plugin);
  const ratingCountLabel = getRatingCountLabel(plugin);
  const downloadLabel = getDownloadLabel(plugin);
  const compatibilityInfo = plugin?.compatibility;
  const isCompatible = isPluginCompatible(plugin);
  const installed = Boolean(details.installed);
  const updateAvailable = Boolean(details.update_available);
  const canInstall = Boolean(onInstall) && !installed && isCompatible && !loading && !plugin.activation_blocked_reason;

  /*
   * PluginDetailsModal displays registry/marketplace metadata and invokes the
   * install callback supplied by the owning page. It must not perform plugin
   * discovery, lifecycle routing, or compatibility decisions beyond displaying
   * the resolved data it has been given.
   */
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <div className="flex items-start gap-4">
            {safeIconUrl && (
              <Image
                src={safeIconUrl}
                alt=""
                width={64}
                height={64}
                className="h-16 w-16 rounded-lg object-cover"
                aria-hidden="true"
              />
            )}

            <div className="min-w-0 flex-1">
              <DialogTitle className="text-xl">{title}</DialogTitle>

              <DialogDescription className="mt-1">
                {description}
              </DialogDescription>

              <div className="mt-2 flex flex-wrap items-center gap-2">
                <PluginStatusBadge status={plugin.runtime_status === 'disabled' ? 'disabled' : plugin.status} />

                {updateAvailable && (
                  <Badge variant="secondary" className="text-xs">
                    Update Available
                  </Badge>
                )}
              </div>
            </div>
          </div>
        </DialogHeader>

        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

        {plugin.activation_blocked_reason && (
          <p role="status" className="text-sm text-amber-700 dark:text-amber-400">
            This plugin is installed in quarantine. Activation requires a verified isolated execution runtime.
          </p>
        )}

        <div className="space-y-6 py-4">
          <div className="flex flex-wrap gap-3">
            <div className="flex items-center gap-1 text-sm text-muted-foreground">
              <User className="h-4 w-4" aria-hidden="true" />
              <span>{author}</span>
            </div>

            <div className="flex items-center gap-1 text-sm text-muted-foreground">
              <GitBranch className="h-4 w-4" aria-hidden="true" />
              <span>v{version}</span>
            </div>

            {plugin.license && (
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Shield className="h-4 w-4" aria-hidden="true" />
                <span>{plugin.license}</span>
              </div>
            )}

            {installedDateLabel && (
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Calendar className="h-4 w-4" aria-hidden="true" />
                <span>Installed {installedDateLabel}</span>
              </div>
            )}
          </div>

          {details.analytics && (ratingLabel || downloadLabel) && (
            <div className="flex flex-wrap gap-4">
              {ratingLabel && (
                <div className="flex items-center gap-2">
                  <Star
                    className="h-4 w-4 fill-yellow-400 text-yellow-400"
                    aria-hidden="true"
                  />
                  <span className="font-semibold">{ratingLabel}</span>
                  <span className="text-sm text-muted-foreground">
                    ({ratingCountLabel} reviews)
                  </span>
                </div>
              )}

              {downloadLabel && (
                <div className="flex items-center gap-2">
                  <Package className="h-4 w-4" aria-hidden="true" />
                  <span className="font-semibold">{downloadLabel}</span>
                  <span className="text-sm text-muted-foreground">downloads</span>
                </div>
              )}
            </div>
          )}

          {compatibilityInfo && (
            <div className="space-y-2">
              <h4 className="text-sm font-medium">Compatibility</h4>

              <div
                className={cn(
                  'flex items-start gap-2 rounded-md p-3',
                  isCompatible
                    ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                    : 'bg-red-500/10 text-red-600 dark:text-red-400',
                )}
              >
                {isCompatible ? (
                  <CheckCircle2
                    className="mt-0.5 h-5 w-5 shrink-0"
                    aria-hidden="true"
                  />
                ) : (
                  <XCircle
                    className="mt-0.5 h-5 w-5 shrink-0"
                    aria-hidden="true"
                  />
                )}

                <div className="flex-1">
                  {isCompatible ? (
                    <p className="text-sm">
                      The backend has not reported an incompatibility for this plugin.
                    </p>
                  ) : (
                    <p className="text-sm">
                      The plugin catalog marks this plugin incompatible with this setup.
                      {compatibilityInfo.min_karen_version && (
                        <span>
                          {' '}
                          Requires version {compatibilityInfo.min_karen_version} or higher.
                        </span>
                      )}
                      {compatibilityInfo.max_karen_version && (
                        <span>
                          {' '}
                          Requires version {compatibilityInfo.max_karen_version} or lower.
                        </span>
                      )}
                    </p>
                  )}

                  {compatibilityInfo.requirements &&
                    compatibilityInfo.requirements.length > 0 && (
                      <div className="mt-2">
                        <p className="mb-1 text-sm font-medium">Requirements:</p>
                        <ul className="list-inside list-disc space-y-1 text-xs">
                          {getUniqueStrings(compatibilityInfo.requirements).map(
                            (requirement) => (
                              <li key={requirement}>{requirement}</li>
                            ),
                          )}
                        </ul>
                      </div>
                    )}
                </div>
              </div>
            </div>
          )}

          {dependencies.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm font-medium">Dependencies</h4>
              <div className="flex flex-wrap gap-2">
                {dependencies.map((dependency) => (
                  <Badge key={dependency} variant="outline" className="text-xs">
                    {dependency}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {tags.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm font-medium">Tags</h4>
              <div className="flex flex-wrap gap-2">
                {tags.map((tag) => (
                  <Badge key={tag} variant="secondary" className="text-xs">
                    {tag}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {externalLinks.length > 0 && (
            <>
              <Separator />

              <div className="flex flex-wrap gap-2">
                {externalLinks.map((link) => (
                  <Button
                    key={link.label}
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => openExternalUrl(link.url)}
                  >
                    {link.icon}
                    {link.label}
                  </Button>
                ))}
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          {installed ? (
            <div className="flex w-full justify-end gap-2">
              {plugin.runtime_status === 'disabled' && !plugin.activation_blocked_reason && onEnable && (
                <Button type="button" onClick={onEnable} disabled={installing || loading}>
                  {installing ? 'Enabling...' : 'Enable'}
                </Button>
              )}
              {['enabled', 'active', 'loaded'].includes(plugin.runtime_status || '') && onDisable && (
                <Button type="button" variant="destructive" onClick={onDisable} disabled={installing || loading}>
                  {installing ? 'Disabling...' : 'Disable'}
                </Button>
              )}
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              onClick={onInstall}
              disabled={installing || loading || !canInstall}
              className="flex-1"
            >
              {installing ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  Installing...
                </>
              ) : (
                <>
                  <Download className="mr-2 h-4 w-4" aria-hidden="true" />
                  Install Plugin
                </>
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
