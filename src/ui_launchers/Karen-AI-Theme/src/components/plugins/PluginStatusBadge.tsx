import React from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  HelpCircle,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { PluginStatus } from '@/types/plugin';

interface PluginStatusBadgeProps {
  status: PluginStatus | 'disabled' | 'error';
  showIcon?: boolean;
  className?: string;
}

type StatusConfig = {
  label: string;
  description: string;
  icon: LucideIcon;
  className: string;
};

/*
 * These are visual hints for known statuses only.
 * Plugin lifecycle/status authority belongs to the backend/plugin registry.
 * Unknown statuses must still render safely instead of crashing the UI.
 */
const STATUS_CONFIG: Record<string, StatusConfig> = {
  installed: {
    label: 'Installed',
    description: 'Plugin is currently installed.',
    icon: CheckCircle2,
    className:
      'border-green-500/20 bg-green-500/10 text-green-600 dark:text-green-400',
  },
  available: {
    label: 'Available',
    description: 'Plugin is available for installation from the store.',
    icon: Download,
    className:
      'border-blue-500/20 bg-blue-500/10 text-blue-600 dark:text-blue-400',
  },
  compatible: {
    label: 'Compatible',
    description: 'Plugin is compatible with your Karen AI version.',
    icon: Clock,
    className:
      'border-yellow-500/20 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400',
  },
  incompatible: {
    label: 'Incompatible',
    description: 'Plugin is not compatible with your current setup.',
    icon: XCircle,
    className:
      'border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-400',
  },
  disabled: {
    label: 'Disabled',
    description: 'Plugin is installed but currently disabled.',
    icon: AlertTriangle,
    className:
      'border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-400',
  },
  error: {
    label: 'Error',
    description: 'Plugin reported an error state.',
    icon: XCircle,
    className:
      'border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-400',
  },
};

const DEFAULT_STATUS_CONFIG: StatusConfig = {
  label: 'Unknown',
  description: 'Plugin status is not recognized by this UI.',
  icon: HelpCircle,
  className:
    'border-muted-foreground/20 bg-muted/40 text-muted-foreground',
};

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const toTitleCase = (value: string): string => {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
};

const getStatusConfig = (status: unknown): StatusConfig => {
  const normalizedStatus = cleanString(status).toLowerCase();

  if (!normalizedStatus) {
    return DEFAULT_STATUS_CONFIG;
  }

  const knownConfig = STATUS_CONFIG[normalizedStatus];

  if (knownConfig) {
    return knownConfig;
  }

  return {
    ...DEFAULT_STATUS_CONFIG,
    label: toTitleCase(normalizedStatus),
    description: `Plugin status: ${normalizedStatus}.`,
  };
};

export function PluginStatusBadge({
  status,
  showIcon = true,
  className = '',
}: PluginStatusBadgeProps) {
  const config = getStatusConfig(status);
  const Icon = config.icon;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="outline"
            className={`${config.className} ${className}`.trim()}
            aria-label={`Plugin status: ${config.label}`}
          >
            {showIcon && (
              <Icon className="mr-1 h-3 w-3" aria-hidden={true} />
            )}
            {config.label}
          </Badge>
        </TooltipTrigger>

        <TooltipContent>
          <p>{config.description}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
