import React, { useMemo } from 'react';
import Image from 'next/image';
import {
  Download,
  ExternalLink,
  GitBranch,
  Hash,
  Loader2,
  Package,
  Star,
  User,
} from 'lucide-react';

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { Plugin } from '@/types/plugin';

import { PluginStatusBadge } from './PluginStatusBadge';

interface PluginCardProps {
  plugin: Plugin;
  onInstall?: (pluginId: string, version?: string) => void;
  onDetails?: (pluginId: string) => void;
  onDiscover?: (pluginId: string) => void;
  loading?: boolean;
  className?: string;
}

const MAX_VISIBLE_TAGS = 3;

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

const getPluginTitle = (plugin: Plugin): string => {
  return cleanString(plugin.display_name) || cleanString(plugin.name) || cleanString(plugin.id) || 'Untitled Plugin';
};

const getPluginDescription = (plugin: Plugin): string => {
  return cleanString(plugin.description) || 'No description provided.';
};

const getPluginAuthor = (plugin: Plugin): string => {
  return cleanString(plugin.author) || 'Unknown author';
};

const getPluginVersion = (plugin: Plugin): string => {
  return cleanString(plugin.version) || 'unknown';
};

const getPluginCategory = (plugin: Plugin): string => {
  return cleanString(plugin.category);
};

const getPluginTags = (plugin: Plugin): string[] => {
  if (!Array.isArray(plugin.tags)) {
    return [];
  }

  const seen = new Set<string>();

  return plugin.tags
    .map((tag) => cleanString(tag))
    .filter((tag) => {
      if (!tag || seen.has(tag.toLowerCase())) {
        return false;
      }

      seen.add(tag.toLowerCase());
      return true;
    });
};

const getRatingLabel = (plugin: Plugin): string => {
  if (typeof plugin.rating !== 'number' || !Number.isFinite(plugin.rating)) {
    return '';
  }

  return plugin.rating.toFixed(1);
};

const getRatingCountLabel = (plugin: Plugin): string => {
  if (
    typeof plugin.rating_count !== 'number' ||
    !Number.isFinite(plugin.rating_count)
  ) {
    return '';
  }

  return Math.max(0, Math.floor(plugin.rating_count)).toLocaleString();
};

const getDownloadLabel = (plugin: Plugin): string => {
  if (
    typeof plugin.downloads !== 'number' ||
    !Number.isFinite(plugin.downloads)
  ) {
    return '';
  }

  return Math.max(0, Math.floor(plugin.downloads)).toLocaleString();
};

export function PluginCard({
  plugin,
  onInstall,
  onDetails,
  onDiscover,
  loading = false,
  className = '',
}: PluginCardProps) {
  const pluginId = cleanString(plugin.id);
  const title = getPluginTitle(plugin);
  const description = getPluginDescription(plugin);
  const author = getPluginAuthor(plugin);
  const version = getPluginVersion(plugin);
  const category = getPluginCategory(plugin);
  const safeIconUrl = getSafeUrl(plugin.icon);
  const safeMarketplaceUrl = getSafeUrl(plugin.marketplace_url);

  const tags = useMemo(() => getPluginTags(plugin), [plugin]);
  const visibleTags = tags.slice(0, MAX_VISIBLE_TAGS);
  const hiddenTagCount = Math.max(0, tags.length - MAX_VISIBLE_TAGS);

  const ratingLabel = getRatingLabel(plugin);
  const ratingCountLabel = getRatingCountLabel(plugin);
  const downloadLabel = getDownloadLabel(plugin);

  const canInstall = plugin.status === 'available' && Boolean(onInstall) && pluginId;
  const canOpenDetails = Boolean(onDetails) && pluginId;
  const canDiscover = Boolean(onDiscover) && pluginId;

  const handleInstall = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();

    if (canInstall) {
      onInstall?.(pluginId, cleanString(plugin.version) || undefined);
    }
  };

  const handleDetails = (
    event:
      | React.MouseEvent<HTMLElement>
      | React.KeyboardEvent<HTMLElement>,
  ) => {
    event.stopPropagation();

    if (canOpenDetails) {
      onDetails?.(pluginId);
    }
  };

  const handleDiscover = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();

    if (canDiscover) {
      onDiscover?.(pluginId);
    }
  };

  const handleOpenMarketplace = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();

    if (!safeMarketplaceUrl || typeof window === 'undefined') {
      return;
    }

    window.open(safeMarketplaceUrl, '_blank', 'noopener,noreferrer');
  };

  /*
   * PluginCard is display and command UI only.
   * Plugin status, category, marketplace metadata, and installability come from
   * the plugin registry/marketplace payload, not from frontend inference.
   */
  return (
    <Card
      role={canOpenDetails ? 'button' : undefined}
      tabIndex={canOpenDetails ? 0 : undefined}
      className={`group cursor-pointer transition-all duration-200 hover:shadow-lg ${className}`.trim()}
      onClick={(event) => {
        if (canOpenDetails) {
          handleDetails(event);
        }
      }}
      onKeyDown={(event) => {
        if (!canOpenDetails) {
          return;
        }

        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          handleDetails(event);
        }
      }}
      aria-label={canOpenDetails ? `View details for ${title}` : undefined}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-2">
              {safeIconUrl && (
                <Image
                  src={safeIconUrl}
                  alt=""
                  width={32}
                  height={32}
                  className="h-8 w-8 rounded-md object-cover"
                  aria-hidden="true"
                />
              )}

              <CardTitle className="truncate text-lg font-semibold" title={title}>
                {title}
              </CardTitle>
            </div>

            <CardDescription className="line-clamp-2 text-xs">
              {description}
            </CardDescription>
          </div>

          <PluginStatusBadge status={plugin.status} />
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pb-3">
        <div className="flex flex-wrap gap-2">
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <User className="h-3 w-3" aria-hidden="true" />
            <span className="max-w-32 truncate" title={author}>
              {author}
            </span>
          </div>

          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <GitBranch className="h-3 w-3" aria-hidden="true" />
            <span>v{version}</span>
          </div>

          {category && (
            <Badge variant="secondary" className="text-xs" title={category}>
              {category}
            </Badge>
          )}
        </div>

        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {visibleTags.map((tag) => (
              <Badge key={tag} variant="outline" className="py-0 text-xs">
                <Hash className="mr-1 h-2 w-2" aria-hidden="true" />
                {tag}
              </Badge>
            ))}

            {hiddenTagCount > 0 && (
              <Badge
                variant="outline"
                className="py-0 text-xs"
                title={tags.slice(MAX_VISIBLE_TAGS).join(', ')}
              >
                +{hiddenTagCount}
              </Badge>
            )}
          </div>
        )}

        {(ratingLabel || downloadLabel) && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {ratingLabel && ratingCountLabel && (
              <div className="flex items-center gap-1">
                <Star
                  className="h-3 w-3 fill-yellow-400 text-yellow-400"
                  aria-hidden="true"
                />
                <span>{ratingLabel}</span>
                <span className="opacity-60">({ratingCountLabel})</span>
              </div>
            )}

            {downloadLabel && (
              <div className="flex items-center gap-1">
                <Package className="h-3 w-3" aria-hidden="true" />
                <span>{downloadLabel}</span>
              </div>
            )}
          </div>
        )}
      </CardContent>

      <CardFooter className="flex gap-2 border-t pt-3">
        {plugin.status === 'available' ? (
          <>
            <Button
              type="button"
              size="sm"
              className="flex-1"
              onClick={handleInstall}
              disabled={loading || !canInstall}
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  Enabling...
                </>
              ) : (
                <>
                  <Download className="mr-1 h-4 w-4" aria-hidden="true" />
                  Install
                </>
              )}
            </Button>

            {onDiscover && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handleDiscover}
                disabled={!canDiscover}
              >
                Discover
              </Button>
            )}
          </>
        ) : plugin.status === 'installed' ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="w-full"
            onClick={(event) => handleDetails(event)}
            disabled={!canOpenDetails}
          >
            Manage
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="w-full"
            onClick={(event) => handleDetails(event)}
            disabled={!canOpenDetails}
          >
            View Details
          </Button>
        )}

        {safeMarketplaceUrl && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={handleOpenMarketplace}
            aria-label={`Open marketplace page for ${title}`}
          >
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}