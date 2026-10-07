'use client';

/**
 * @file ModelDownloads.tsx
 * @description Live backend model-download control plane.
 *
 * Runtime boundary:
 * - Backend owns policy, channels, jobs, installed inventory, discovery,
 *   validation, download queueing, and executor state.
 * - UI displays backend truth and sends user commands only.
 * - UI must not invent runtime compatibility or model availability.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  Cpu,
  Database,
  Download,
  FolderOpen,
  Gauge,
  HardDrive,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ServerCog,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Workflow,
} from 'lucide-react';

import { apiClient, ApiError } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import {
  isVllmCompatibleModel,
  sortProviderModels,
  type RuntimeProviderModel,
} from '@/lib/model-runtime-inventory';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

type DownloadPolicy = {
  master_enabled: boolean;
  core_runtime_enabled: boolean;
  plugin_channels_enabled: boolean;
  image_channels_enabled: boolean;
  audio_channels_enabled: boolean;
  vision_channels_enabled: boolean;
  gguf_external_enabled: boolean;
  trust_remote_code: boolean;
  block_new_downloads: boolean;
  pause_active_downloads: boolean;
  quarantine_failed_models: boolean;
  require_license_acceptance: boolean;
  max_concurrent_downloads: number;
};

type DownloadChannel = {
  id: string;
  label: string;
  group: string;
  storage_key: string;
  enabled: boolean;
  effective_enabled: boolean;
  locked_by_master: boolean;
  description: string;
  model_families: string[];
  modalities: string[];
  admin_only: boolean;
};

type DownloadJob = {
  job_id: string;
  model_id: string;
  revision?: string | null;
  channel_id: string;
  storage_key?: string | null;
  status: string;
  progress: number;
  message: string;
  error?: string | null;
  result?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  requested_by?: string | null;
  trust_remote_code: boolean;
  license_accepted: boolean;
  include_patterns?: string[] | null;
  exclude_patterns?: string[] | null;
  pin: boolean;
  force_redownload: boolean;
  pause_requested: boolean;
  cancel_requested: boolean;
  warnings: string[];
  detected_runtime?: string | null;
  detected_modality?: string | null;
  install_path?: string | null;
  channel?: DownloadChannel | null;
};

type DownloadValidation = {
  allowed: boolean;
  channel_id: string;
  model_id: string;
  revision?: string | null;
  storage_key?: string | null;
  install_path?: string | null;
  detected_runtime?: string | null;
  detected_modality?: string | null;
  warnings: string[];
  blocking_reasons: string[];
  license_required: boolean;
  trust_remote_code_allowed: boolean;
  metadata: Record<string, unknown>;
};

type ModelCatalogItem = {
  model_id: string;
  last_modified?: string | null;
  likes?: number | null;
  downloads?: number | null;
  storage_key?: string | null;
  tags: string[];
  total_size?: number | null;
  description?: string | null;
};

type RecommendedModel = {
  id: string;
  model_id: string;
  label: string;
  purpose: string;
  tier: 'essential' | 'recommended' | string;
  channel_id: string;
  expected_runtime?: string | null;
  approximate_size_bytes?: number | null;
  license?: string | null;
  include_patterns?: string[] | null;
  capabilities: string[];
  app_consumers: string[];
  installed: boolean;
  install_path?: string | null;
  status: string;
};

type RecommendedModelsResponse = {
  recommendations: RecommendedModel[];
  essential_ready: boolean;
  essential_installed: number;
  essential_total: number;
};

type ModelStorageSettings = {
  models_root: string;
  runtime_registry_root: string;
  registry_path: string;
  env_override: boolean;
};

type InstalledModelsResponse = {
  models: Array<
    RuntimeProviderModel & {
      size_bytes?: number | null;
      capabilities?: string[];
      preferred_runtime?: string | null;
      compatible_runtimes?: string[];
    }
  >;
  total: number;
  statistics: Record<string, unknown>;
};

type DiscoverySnapshot = {
  progress: Record<string, unknown>;
  statistics: Record<string, unknown>;
};

type EndpointErrors = Partial<
  Record<'policy' | 'channels' | 'jobs' | 'installed' | 'discovery', string>
>;

interface ModelDownloadsProps {
  adminMode?: boolean;
}

const ENDPOINTS = {
  policy: '/api/models/download/policy',
  channels: '/api/models/download/channels',
  jobs: '/api/models/download/jobs?limit=50',
  installed: '/api/models/installed?force_refresh=false',
  discovery: '/api/models/discovery?force_refresh=false',
  recommendations: '/api/models/download/recommendations',
  storage: '/api/models/download/storage',
  catalog: '/api/models/catalog?limit=24',
  validate: '/api/models/download/validate',
  download: '/api/models/download',
};

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (typeof error.details === 'string' && error.details.trim()) {
      return error.details.trim();
    }

    if (error.message.trim()) {
      return error.message.trim();
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }

  return fallback;
}

function parseCsvList(value: string): string[] {
  const seen = new Set<string>();

  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => {
      const normalized = item.toLowerCase();

      if (!item || seen.has(normalized)) {
        return false;
      }

      seen.add(normalized);
      return true;
    });
}

function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) {
    return '0 B';
  }

  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function statusTone(status: string): string {
  switch (status) {
    case 'completed':
      return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700';
    case 'running':
      return 'border-blue-500/30 bg-blue-500/10 text-blue-700';
    case 'queued':
    case 'paused':
    case 'pause_requested':
      return 'border-amber-500/30 bg-amber-500/10 text-amber-700';
    case 'failed':
    case 'cancelled':
      return 'border-red-500/30 bg-red-500/10 text-red-700';
    default:
      return 'border-border/60 bg-muted/20 text-muted-foreground';
  }
}

function groupChannels(
  channels: DownloadChannel[],
): Record<string, DownloadChannel[]> {
  return channels.reduce<Record<string, DownloadChannel[]>>((acc, channel) => {
    const bucket = channel.group || 'other';
    acc[bucket] = acc[bucket] || [];
    acc[bucket].push(channel);
    return acc;
  }, {});
}

function normalizeProgress(value: unknown): number {
  const numeric = Number(value);

  if (!Number.isFinite(numeric)) {
    return 0;
  }

  const percent = numeric > 1 ? numeric : numeric * 100;

  return Math.min(Math.max(percent, 0), 100);
}

function canPauseJob(status: string): boolean {
  return status === 'queued' || status === 'running';
}

function canResumeJob(status: string): boolean {
  return status === 'paused' || status === 'pause_requested';
}

function canCancelJob(status: string): boolean {
  return !['completed', 'failed', 'cancelled'].includes(status);
}

function isAdminOnlyChannelBlocked(
  channel: DownloadChannel | null,
  adminMode: boolean,
): boolean {
  return Boolean(channel?.admin_only && !adminMode);
}

function safeStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function compactCount(value?: number | null): string {
  if (!value || value < 1) return '0';
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function encodeModelPath(modelId: string): string {
  return modelId
    .split('/')
    .map((part) => encodeURIComponent(part))
    .join('/');
}

function SectionIcon({
  children,
  tone = 'primary',
}: {
  children: React.ReactNode;
  tone?: 'primary' | 'secondary' | 'positive' | 'warning';
}) {
  const toneClass =
    tone === 'secondary'
      ? 'bg-cyan-500/10 text-cyan-500'
      : tone === 'positive'
        ? 'bg-emerald-500/10 text-emerald-500'
        : tone === 'warning'
          ? 'bg-amber-500/10 text-amber-500'
          : 'bg-primary/10 text-primary';

  return (
    <div
      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border/40 ${toneClass}`}
    >
      {children}
    </div>
  );
}

function MetricTile({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="flex min-w-[138px] items-center gap-3 rounded-xl border border-border/40 bg-background/50 px-3 py-2.5 shadow-sm">
      <div className="text-primary">{icon}</div>
      <div className="min-w-0">
        <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-muted-foreground">
          {label}
        </div>
        <div className="truncate text-sm font-semibold text-foreground">{value}</div>
        {detail ? (
          <div className="truncate text-[10px] text-muted-foreground">{detail}</div>
        ) : null}
      </div>
    </div>
  );
}

export default function ModelDownloads({
  adminMode = false,
}: ModelDownloadsProps) {
  const { toast } = useToast();

  const [policy, setPolicy] = useState<DownloadPolicy | null>(null);
  const [channels, setChannels] = useState<DownloadChannel[]>([]);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [installed, setInstalled] = useState<InstalledModelsResponse | null>(null);
  const [discovery, setDiscovery] = useState<DiscoverySnapshot | null>(null);
  const [endpointErrors, setEndpointErrors] = useState<EndpointErrors>({});
  const [loading, setLoading] = useState(true);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [startingDownload, setStartingDownload] = useState(false);
  const [validating, setValidating] = useState(false);
  const [busyJobs, setBusyJobs] = useState<Record<string, boolean>>({});
  const [validation, setValidation] = useState<DownloadValidation | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalogItem[]>([]);
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [removingModels, setRemovingModels] = useState<Record<string, boolean>>({});
  const [retryingJobs, setRetryingJobs] = useState<Record<string, boolean>>({});
  const [recommendations, setRecommendations] = useState<RecommendedModelsResponse | null>(null);
  const [storageSettings, setStorageSettings] = useState<ModelStorageSettings | null>(null);
  const [modelsRootDraft, setModelsRootDraft] = useState('');
  const [savingModelsRoot, setSavingModelsRoot] = useState(false);
  const [installingRecommended, setInstallingRecommended] = useState<Record<string, boolean>>({});
  const [installingEssentials, setInstallingEssentials] = useState(false);

  const [modelId, setModelId] = useState('');
  const [revision, setRevision] = useState('');
  const [channelId, setChannelId] = useState('');
  const [includePatterns, setIncludePatterns] = useState('');
  const [excludePatterns, setExcludePatterns] = useState('');
  const [acceptLicense, setAcceptLicense] = useState(false);
  const [trustRemoteCode, setTrustRemoteCode] = useState(false);

  const loadState = useCallback(async () => {
    setLoading(true);

    const [
      policyResult,
      channelsResult,
      jobsResult,
      installedResult,
      discoveryResult,
      recommendationsResult,
      storageResult,
    ] = await Promise.allSettled([
      apiClient.get<DownloadPolicy>(ENDPOINTS.policy),
      apiClient.get<{ policy: DownloadPolicy; channels: DownloadChannel[] }>(
        ENDPOINTS.channels,
      ),
      apiClient.get<DownloadJob[]>(ENDPOINTS.jobs),
      apiClient.get<InstalledModelsResponse>(ENDPOINTS.installed),
      apiClient.get<DiscoverySnapshot>(ENDPOINTS.discovery),
      apiClient.get<RecommendedModelsResponse>(ENDPOINTS.recommendations),
      apiClient.get<ModelStorageSettings>(ENDPOINTS.storage),
    ]);

    const nextErrors: EndpointErrors = {};

    if (policyResult.status === 'fulfilled') {
      setPolicy(policyResult.value);
    } else {
      nextErrors.policy = getErrorMessage(
        policyResult.reason,
        'Download policy endpoint failed.',
      );
    }

    if (channelsResult.status === 'fulfilled') {
      const nextChannels = Array.isArray(channelsResult.value.channels)
        ? channelsResult.value.channels
        : [];
      setChannels(nextChannels);
    } else {
      nextErrors.channels = getErrorMessage(
        channelsResult.reason,
        'Download channels endpoint failed.',
      );
    }

    if (jobsResult.status === 'fulfilled') {
      setJobs(Array.isArray(jobsResult.value) ? jobsResult.value : []);
    } else {
      nextErrors.jobs = getErrorMessage(
        jobsResult.reason,
        'Download jobs endpoint failed.',
      );
    }

    if (installedResult.status === 'fulfilled') {
      setInstalled(installedResult.value);
    } else {
      nextErrors.installed = getErrorMessage(
        installedResult.reason,
        'Installed model inventory endpoint failed.',
      );
    }

    if (discoveryResult.status === 'fulfilled') {
      setDiscovery(discoveryResult.value);
    } else {
      nextErrors.discovery = getErrorMessage(
        discoveryResult.reason,
        'Model discovery endpoint failed.',
      );
    }

    if (recommendationsResult.status === 'fulfilled') {
      setRecommendations(recommendationsResult.value);
    }

    if (storageResult.status === 'fulfilled') {
      setStorageSettings(storageResult.value);
      setModelsRootDraft(storageResult.value.models_root);
    }

    setEndpointErrors(nextErrors);

    if (Object.keys(nextErrors).length > 0) {
      toast({
        title: 'Model download state partially loaded',
        description:
          'Some backend model-download endpoints failed. Showing the live data that could be loaded.',
        variant: 'destructive',
      });
    }

    setLoading(false);
  }, [toast]);

  const loadCatalog = useCallback(async (query: string) => {
    setCatalogLoading(true);
    setCatalogError(null);
    try {
      const params = new URLSearchParams({ limit: '24' });
      const trimmed = query.trim();
      if (trimmed.length >= 2) {
        params.set('query', trimmed);
      }
      const response = await apiClient.get<ModelCatalogItem[]>(
        `/api/models/catalog?${params.toString()}`,
      );
      setCatalog(Array.isArray(response) ? response : []);
    } catch (error) {
      setCatalog([]);
      setCatalogError(
        getErrorMessage(error, 'Karen could not load the model catalog.'),
      );
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  const refreshJobsOnly = useCallback(async () => {
    try {
      const response = await apiClient.get<DownloadJob[]>(ENDPOINTS.jobs);
      setJobs(Array.isArray(response) ? response : []);
    } catch (error) {
      setEndpointErrors((current) => ({
        ...current,
        jobs: getErrorMessage(error, 'Download jobs endpoint failed.'),
      }));
    }
  }, []);

  useEffect(() => {
    void loadState();
    void loadCatalog('');
  }, [loadCatalog, loadState]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadCatalog(catalogQuery);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [catalogQuery, loadCatalog]);


  useEffect(() => {
    setValidation(null);
  }, [
    modelId,
    revision,
    channelId,
    includePatterns,
    excludePatterns,
    acceptLicense,
    trustRemoteCode,
  ]);

  const groupedChannels = useMemo(() => groupChannels(channels), [channels]);

  const currentChannel = useMemo(
    () => channels.find((channel) => channel.id === channelId) ?? null,
    [channels, channelId],
  );

  const queueCount = useMemo(
    () =>
      jobs.filter((job) =>
        ['queued', 'running', 'paused', 'pause_requested'].includes(job.status),
      ).length,
    [jobs],
  );

  useEffect(() => {
    if (queueCount === 0) {
      return;
    }

    const interval = window.setInterval(() => {
      void refreshJobsOnly();
    }, 3000);

    return () => window.clearInterval(interval);
  }, [queueCount, refreshJobsOnly]);

  const installedModels = useMemo(
    () => sortProviderModels((installed?.models ?? []) as RuntimeProviderModel[]),
    [installed],
  );

  const vllmInstalledModels = useMemo(
    () => installedModels.filter((model) => isVllmCompatibleModel(model)),
    [installedModels],
  );

  const otherInstalledModels = useMemo(
    () => installedModels.filter((model) => !isVllmCompatibleModel(model)),
    [installedModels],
  );

  const discoveryProgress = discovery?.progress ?? {};
  const discoveryStats = discovery?.statistics ?? {};
  const activeJobs = jobs.filter((job) =>
    ['queued', 'running', 'paused', 'pause_requested'].includes(job.status),
  );
  const failedJobs = jobs.filter((job) => job.status === 'failed').length;
  const discoveryStatus = String(
    discoveryStats.discovery_status ?? discoveryStats.status ?? 'unknown',
  );
  const essentialStatus = recommendations
    ? recommendations.essential_ready
      ? 'Ready'
      : `${recommendations.essential_installed}/${recommendations.essential_total} ready`
    : 'Loading';

  const hasEndpointErrors = Object.keys(endpointErrors).length > 0;
  const channelBlocked = isAdminOnlyChannelBlocked(currentChannel, adminMode);
  const downloadsBlocked = Boolean(
    policy && (!policy.master_enabled || policy.block_new_downloads),
  );
  const canQueueDownload =
    Boolean(modelId.trim()) &&
    validation?.allowed === true &&
    validation.model_id === modelId.trim() &&
    !startingDownload &&
    !channelBlocked &&
    !downloadsBlocked;

  const updatePolicyField = useCallback(
    <K extends keyof DownloadPolicy>(key: K, value: DownloadPolicy[K]) => {
      setPolicy((current) => (current ? { ...current, [key]: value } : current));
    },
    [],
  );

  const savePolicy = useCallback(async () => {
    if (!policy) {
      return;
    }

    setSavingPolicy(true);

    try {
      const response = await apiClient.put<DownloadPolicy>(
        ENDPOINTS.policy,
        policy,
      );
      setPolicy(response);

      toast({
        title: 'Download policy saved',
        description: 'Model download safety settings were updated.',
      });
    } catch (error) {
      toast({
        title: 'Unable to save policy',
        description: getErrorMessage(
          error,
          'Karen could not save the model download policy.',
        ),
        variant: 'destructive',
      });
    } finally {
      setSavingPolicy(false);
    }
  }, [policy, toast]);

  const refreshAll = useCallback(async () => {
    setRefreshing(true);

    try {
      await loadState();
    } finally {
      setRefreshing(false);
    }
  }, [loadState]);

  const validateDownload = useCallback(async () => {
    const requestedModelId = modelId.trim();

    if (!requestedModelId) {
      toast({
        title: 'Model ID required',
        description: 'Enter a Hugging Face model identifier like owner/repo.',
        variant: 'destructive',
      });
      return;
    }

    setValidating(true);

    try {
      const response = await apiClient.post<DownloadValidation>(
        ENDPOINTS.validate,
        {
          model_id: requestedModelId,
          revision: revision.trim() || null,
          channel_id: currentChannel?.id || null,
          trust_remote_code: trustRemoteCode,
          accept_license: acceptLicense,
          include_patterns: parseCsvList(includePatterns),
          exclude_patterns: parseCsvList(excludePatterns),
        },
      );

      setValidation(response);

      toast({
        title: response.allowed ? 'Validation passed' : 'Validation blocked',
        description: response.allowed
          ? `Model will install to ${response.install_path ?? 'the configured channel'}.`
          : response.blocking_reasons.join('; ') || 'Backend policy blocked this download.',
        variant: response.allowed ? 'default' : 'destructive',
      });
    } catch (error) {
      toast({
        title: 'Validation failed',
        description: getErrorMessage(
          error,
          'Karen could not validate the requested download.',
        ),
        variant: 'destructive',
      });
    } finally {
      setValidating(false);
    }
  }, [
    acceptLicense,
    currentChannel?.id,
    excludePatterns,
    includePatterns,
    modelId,
    revision,
    toast,
    trustRemoteCode,
  ]);

  const startDownload = useCallback(async () => {
    const requestedModelId = modelId.trim();

    if (!requestedModelId) {
      toast({
        title: 'Model ID required',
        description: 'Enter a Hugging Face model identifier before starting a download.',
        variant: 'destructive',
      });
      return;
    }

    if (channelBlocked) {
      toast({
        title: 'Channel blocked',
        description: 'This channel is admin-only and cannot be used in this mode.',
        variant: 'destructive',
      });
      return;
    }

    if (downloadsBlocked) {
      toast({
        title: 'Downloads blocked',
        description: 'Backend policy is currently blocking new downloads.',
        variant: 'destructive',
      });
      return;
    }

    setStartingDownload(true);

    try {
      const response = await apiClient.post<{
        job_id: string;
        message: string;
        status: string;
      }>(ENDPOINTS.download, {
        model_id: requestedModelId,
        revision: revision.trim() || null,
        channel_id: currentChannel?.id || null,
        include_patterns: parseCsvList(includePatterns),
        exclude_patterns: parseCsvList(excludePatterns),
        trust_remote_code: trustRemoteCode,
        accept_license: acceptLicense,
      });

      toast({
        title: 'Download queued',
        description: `${response.job_id} is now ${response.status}.`,
      });

      await refreshAll();
    } catch (error) {
      toast({
        title: 'Download failed',
        description: getErrorMessage(
          error,
          'Karen could not queue the model download.',
        ),
        variant: 'destructive',
      });
    } finally {
      setStartingDownload(false);
    }
  }, [
    acceptLicense,
    channelBlocked,
    currentChannel?.id,
    downloadsBlocked,
    excludePatterns,
    includePatterns,
    modelId,
    refreshAll,
    revision,
    toast,
    trustRemoteCode,
  ]);

  const actOnJob = useCallback(
    async (jobId: string, action: 'cancel' | 'pause' | 'resume') => {
      const safeJobId = jobId.trim();

      if (!safeJobId) {
        return;
      }

      setBusyJobs((current) => ({ ...current, [safeJobId]: true }));

      try {
        await apiClient.post(
          `/api/models/download/jobs/${encodeURIComponent(safeJobId)}/${action}`,
          {},
        );

        await refreshAll();

        toast({
          title:
            action === 'cancel'
              ? 'Job cancelled'
              : action === 'pause'
                ? 'Job paused'
                : 'Job resumed',
          description: `Download job ${safeJobId} was updated.`,
        });
      } catch (error) {
        toast({
          title: `Unable to ${action} job`,
          description: getErrorMessage(
            error,
            `Karen could not ${action} the download job.`,
          ),
          variant: 'destructive',
        });
      } finally {
        setBusyJobs((current) => {
          const next = { ...current };
          delete next[safeJobId];
          return next;
        });
      }
    },
    [refreshAll, toast],
  );

  const retryJob = useCallback(
    async (job: DownloadJob) => {
      setRetryingJobs((current) => ({ ...current, [job.job_id]: true }));
      try {
        await apiClient.post(ENDPOINTS.download, {
          model_id: job.model_id,
          revision: job.revision || null,
          channel_id: job.channel_id || null,
          include_patterns: job.include_patterns || [],
          exclude_patterns: job.exclude_patterns || [],
          trust_remote_code: job.trust_remote_code,
          accept_license: job.license_accepted,
          pin: job.pin,
          force_redownload: true,
        });
        await refreshAll();
        toast({
          title: 'Retry queued',
          description: `${job.model_id} has been queued for a clean retry.`,
        });
      } catch (error) {
        toast({
          title: 'Retry failed',
          description: getErrorMessage(error, 'Karen could not retry this model download.'),
          variant: 'destructive',
        });
      } finally {
        setRetryingJobs((current) => {
          const next = { ...current };
          delete next[job.job_id];
          return next;
        });
      }
    },
    [refreshAll, toast],
  );

  const removeInstalledModel = useCallback(
    async (modelId: string) => {
      if (
        typeof window !== 'undefined' &&
        !window.confirm(
          `Remove ${modelId} from Karen and delete its local model files?`,
        )
      ) {
        return;
      }

      setRemovingModels((current) => ({ ...current, [modelId]: true }));
      try {
        await apiClient.delete(
          `/api/models/remove/${encodeModelPath(modelId)}?delete_files=true`,
        );
        await refreshAll();
        toast({
          title: 'Model removed',
          description: `${modelId} was removed from the local runtime inventory.`,
        });
      } catch (error) {
        toast({
          title: 'Unable to remove model',
          description: getErrorMessage(error, 'Karen could not remove this model.'),
          variant: 'destructive',
        });
      } finally {
        setRemovingModels((current) => {
          const next = { ...current };
          delete next[modelId];
          return next;
        });
      }
    },
    [refreshAll, toast],
  );

  const chooseCatalogModel = useCallback((item: ModelCatalogItem) => {
    setModelId(item.model_id);
    setRevision('');
    setValidation(null);
  }, []);

  const installRecommendedModel = useCallback(
    async (item: RecommendedModel) => {
      if (item.installed) return;
      if (policy?.require_license_acceptance && !acceptLicense) {
        toast({
          title: 'Accept the model license first',
          description: 'Use the license switch in the install panel before installing recommended models.',
          variant: 'destructive',
        });
        return;
      }

      setInstallingRecommended((current) => ({ ...current, [item.id]: true }));
      try {
        await apiClient.post(ENDPOINTS.download, {
          model_id: item.model_id,
          channel_id: item.channel_id,
          include_patterns: item.include_patterns || [],
          exclude_patterns: [],
          trust_remote_code: false,
          accept_license: acceptLicense,
        });
        toast({
          title: 'Recommended model queued',
          description: `${item.label} is queued for installation.`,
        });
        await refreshAll();
      } catch (error) {
        toast({
          title: `Unable to install ${item.label}`,
          description: getErrorMessage(error, 'Karen could not queue this recommended model.'),
          variant: 'destructive',
        });
      } finally {
        setInstallingRecommended((current) => {
          const next = { ...current };
          delete next[item.id];
          return next;
        });
      }
    },
    [acceptLicense, policy?.require_license_acceptance, refreshAll, toast],
  );

  const installEssentialModels = useCallback(async () => {
    const essentials = (recommendations?.recommendations ?? []).filter(
      (item) => item.tier === 'essential' && !item.installed,
    );
    if (essentials.length === 0) return;
    if (policy?.require_license_acceptance && !acceptLicense) {
      toast({
        title: 'Accept the model licenses first',
        description: 'Karen will not silently accept third-party model licenses on your behalf.',
        variant: 'destructive',
      });
      return;
    }

    setInstallingEssentials(true);
    try {
      for (const item of essentials) {
        await apiClient.post(ENDPOINTS.download, {
          model_id: item.model_id,
          channel_id: item.channel_id,
          include_patterns: item.include_patterns || [],
          exclude_patterns: [],
          trust_remote_code: false,
          accept_license: acceptLicense,
        });
      }
      toast({
        title: 'Karen essentials queued',
        description: `${essentials.length} required local model${essentials.length === 1 ? '' : 's'} queued.`,
      });
      await refreshAll();
    } catch (error) {
      toast({
        title: 'Unable to queue all essentials',
        description: getErrorMessage(error, 'One or more essential model downloads could not be queued.'),
        variant: 'destructive',
      });
      await refreshAll();
    } finally {
      setInstallingEssentials(false);
    }
  }, [acceptLicense, policy?.require_license_acceptance, recommendations, refreshAll, toast]);

  const saveModelsRoot = useCallback(async () => {
    const nextRoot = modelsRootDraft.trim();
    if (!nextRoot || nextRoot === storageSettings?.models_root) return;
    setSavingModelsRoot(true);
    try {
      const response = await apiClient.put<ModelStorageSettings>(
        ENDPOINTS.storage,
        { models_root: nextRoot },
      );
      setStorageSettings(response);
      setModelsRootDraft(response.models_root);
      toast({
        title: 'Model library folder updated',
        description: `New model downloads will use ${response.models_root}.`,
      });
      await refreshAll();
    } catch (error) {
      toast({
        title: 'Unable to change model library folder',
        description: getErrorMessage(error, 'Karen could not update the model library folder.'),
        variant: 'destructive',
      });
    } finally {
      setSavingModelsRoot(false);
    }
  }, [modelsRootDraft, refreshAll, storageSettings?.models_root, toast]);

  const renderPolicyRow = (
    label: string,
    description: string,
    key: keyof DownloadPolicy,
    disabled?: boolean,
  ) => {
    if (!policy) {
      return null;
    }

    const value = policy[key];

    return (
      <div className="flex items-start justify-between gap-4 rounded-xl border border-border/50 bg-muted/20 px-4 py-3">
        <div className="space-y-1">
          <div className="text-sm font-semibold text-foreground">{label}</div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </div>

        <Switch
          checked={Boolean(value)}
          disabled={disabled}
          onCheckedChange={(checked) =>
            updatePolicyField(key, checked as never)
          }
        />
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {hasEndpointErrors && (
        <Alert className="border-amber-500/30 bg-amber-500/10">
          <AlertTriangle className="h-4 w-4 !text-amber-600" aria-hidden="true" />
          <AlertTitle>Model download control plane partially available</AlertTitle>
          <AlertDescription className="space-y-1 text-xs">
            {Object.entries(endpointErrors).map(([name, message]) => (
              <p key={name}>
                <strong>{name}:</strong> {message}
              </p>
            ))}
          </AlertDescription>
        </Alert>
      )}

      <Card className="border-border/50 bg-gradient-to-br from-card via-card to-muted/20">
        <CardHeader>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-xl">
                <HardDrive className="h-5 w-5 text-primary" aria-hidden="true" />
                Model Downloads
              </CardTitle>
              <CardDescription>
                Core download policy, plugin channel gates, queue state, and
                installed model inventory.
              </CardDescription>
            </div>

            <div className="flex items-center gap-2">
              <Badge variant="outline">{queueCount} queued</Badge>
              <Badge variant="outline">{installedModels.length} installed</Badge>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void refreshAll()}
                disabled={refreshing}
              >
                {refreshing ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                Refresh
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {recommendations && (
        <Card className="border-border/50">
          <CardHeader>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />
                  Karen Recommended
                </CardTitle>
                <CardDescription>
                  First-run local models Karen is explicitly built to use.
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={recommendations.essential_ready ? 'secondary' : 'outline'}>
                  {recommendations.essential_installed}/{recommendations.essential_total} essentials ready
                </Badge>
                {!recommendations.essential_ready && (
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => void installEssentialModels()}
                    disabled={installingEssentials || downloadsBlocked}
                  >
                    {installingEssentials ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Download className="mr-2 h-4 w-4" aria-hidden="true" />
                    )}
                    Install Essentials
                  </Button>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {policy?.require_license_acceptance && (
              <div className="flex items-start justify-between gap-4 rounded-xl border border-border/50 bg-muted/20 px-4 py-3">
                <div>
                  <div className="text-sm font-semibold">Accept recommended model licenses</div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Required before Karen queues curated third-party models. License names are shown on each card.
                  </p>
                </div>
                <Switch checked={acceptLicense} onCheckedChange={setAcceptLicense} />
              </div>
            )}

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {recommendations.recommendations.map((item) => (
                <div
                  key={item.id}
                  className={[
                    'rounded-xl border p-4',
                    item.installed
                      ? 'border-emerald-500/30 bg-emerald-500/5'
                      : 'border-border/50 bg-muted/10',
                  ].join(' ')}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-sm font-semibold">{item.label}</span>
                        <Badge variant={item.tier === 'essential' ? 'secondary' : 'outline'} className="text-[9px]">
                          {item.tier}
                        </Badge>
                      </div>
                      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                        {item.purpose}
                      </p>
                    </div>
                    {item.installed && (
                      <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-label="Installed" />
                    )}
                  </div>

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <Badge variant="outline" className="text-[9px]">
                      {formatBytes(item.approximate_size_bytes)}
                    </Badge>
                    {item.license && (
                      <Badge variant="outline" className="text-[9px]">{item.license}</Badge>
                    )}
                    {item.expected_runtime && (
                      <Badge variant="outline" className="text-[9px]">{item.expected_runtime}</Badge>
                    )}
                  </div>

                  <div className="mt-3 text-[10px] text-muted-foreground">
                    Used by: {item.app_consumers.join(', ')}
                  </div>

                  <Button
                    type="button"
                    variant={item.installed ? 'outline' : 'default'}
                    size="sm"
                    className="mt-4 w-full"
                    disabled={item.installed || installingRecommended[item.id] || downloadsBlocked}
                    onClick={() => void installRecommendedModel(item)}
                  >
                    {item.installed ? (
                      'Installed'
                    ) : installingRecommended[item.id] ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                        Queueing...
                      </>
                    ) : (
                      <>
                        <Download className="mr-2 h-4 w-4" aria-hidden="true" />
                        Install
                      </>
                    )}
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Search className="h-4 w-4 text-primary" aria-hidden="true" />
            Find a Model
          </CardTitle>
          <CardDescription>
            Search the live model catalog, review the basics, then let Karen infer
            the correct runtime channel before installation.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              aria-label="Search model catalog"
              className="pl-9"
              placeholder="Search models, for example Qwen, Llama, embedding..."
              value={catalogQuery}
              onChange={(event) => setCatalogQuery(event.target.value)}
            />
          </div>

          {catalogError && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              <AlertTitle>Model catalog unavailable</AlertTitle>
              <AlertDescription>{catalogError}</AlertDescription>
            </Alert>
          )}

          {catalogLoading ? (
            <div className="flex min-h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Searching available models...
            </div>
          ) : catalog.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border/60 p-6 text-center text-sm text-muted-foreground">
              No catalog results were returned. You can still enter an exact
              Hugging Face model ID below.
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {catalog.map((item) => {
                const selected = item.model_id === modelId.trim();
                return (
                  <button
                    key={item.model_id}
                    type="button"
                    onClick={() => chooseCatalogModel(item)}
                    className={[
                      'rounded-xl border p-4 text-left transition-colors',
                      selected
                        ? 'border-primary/50 bg-primary/5'
                        : 'border-border/50 bg-muted/10 hover:bg-muted/30',
                    ].join(' ')}
                    aria-pressed={selected}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold">
                        {item.model_id}
                      </div>
                      <p className="mt-1 line-clamp-2 min-h-8 text-xs text-muted-foreground">
                        {item.description || 'Model metadata is available from the canonical catalog.'}
                      </p>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <Badge variant="outline" className="text-[9px]">
                        {compactCount(item.downloads)} downloads
                      </Badge>
                      <Badge variant="outline" className="text-[9px]">
                        {compactCount(item.likes)} likes
                      </Badge>
                      {item.total_size ? (
                        <Badge variant="outline" className="text-[9px]">
                          {formatBytes(item.total_size)}
                        </Badge>
                      ) : null}
                    </div>
                    {item.tags.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {item.tags.slice(0, 3).map((tag) => (
                          <Badge key={tag} variant="secondary" className="text-[8px]">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <HardDrive className="h-4 w-4 text-primary" aria-hidden="true" />
            Model Library Folder
          </CardTitle>
          <CardDescription>
            Choose where Karen stores downloaded local models. Active downloads must finish or be cancelled before changing folders.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              aria-label="Model library folder"
              value={modelsRootDraft}
              onChange={(event) => setModelsRootDraft(event.target.value)}
              placeholder="/path/to/karen-models"
              disabled={storageSettings?.env_override}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => void saveModelsRoot()}
              disabled={
                savingModelsRoot ||
                !modelsRootDraft.trim() ||
                modelsRootDraft.trim() === storageSettings?.models_root ||
                storageSettings?.env_override
              }
            >
              {savingModelsRoot ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Save className="mr-2 h-4 w-4" aria-hidden="true" />
              )}
              Save Folder
            </Button>
          </div>
          {storageSettings?.env_override && (
            <p className="text-xs text-muted-foreground">
              This folder is locked by KAREN_MODELS_ROOT. Change that environment setting to move the library.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Shield className="h-4 w-4 text-primary" aria-hidden="true" />
              Download Safety Panel
            </CardTitle>
            <CardDescription>
              Master gate first, then category switches, then channel-specific
              overrides.
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-4">
            {loading || !policy ? (
              <div
                className="flex items-center gap-2 text-sm text-muted-foreground"
                role="status"
                aria-live="polite"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading policy...
              </div>
            ) : (
              <>
                {renderPolicyRow(
                  'Master Downloads',
                  'Disable all download activity across runtime and plugin channels.',
                  'master_enabled',
                )}
                {renderPolicyRow(
                  'Core Runtime Models',
                  'Transformers, embeddings, rerankers, ONNX, and GGUF channels.',
                  'core_runtime_enabled',
                )}
                {renderPolicyRow(
                  'Plugin Channels',
                  'Image, audio, vision, and plugin-private model channels.',
                  'plugin_channels_enabled',
                )}

                <div className="grid gap-3 md:grid-cols-2">
                  {renderPolicyRow(
                    'Image Models',
                    'SD, FLUX, and diffusion pipelines.',
                    'image_channels_enabled',
                  )}
                  {renderPolicyRow(
                    'Audio Models',
                    'TTS and STT downloads.',
                    'audio_channels_enabled',
                  )}
                  {renderPolicyRow(
                    'Vision / OCR',
                    'OCR, document understanding, and multimodal helpers.',
                    'vision_channels_enabled',
                  )}
                  {renderPolicyRow(
                    'GGUF External Only',
                    'Allow external GGUF snapshots for local inference.',
                    'gguf_external_enabled',
                  )}
                </div>

                <div className="flex items-start justify-between gap-4 rounded-xl border border-border/50 bg-muted/20 px-4 py-3">
                  <div className="space-y-1">
                    <div className="text-sm font-semibold text-foreground">
                      trust_remote_code
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {adminMode
                        ? 'Admin-only. Locked off by default.'
                        : 'Locked by admin policy.'}
                    </div>
                  </div>
                  <Switch
                    checked={policy.trust_remote_code}
                    disabled={!adminMode}
                    onCheckedChange={(checked) =>
                      updatePolicyField('trust_remote_code', checked)
                    }
                  />
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  {renderPolicyRow(
                    'Block New Downloads',
                    'Prevent new jobs from entering the queue.',
                    'block_new_downloads',
                  )}
                  {renderPolicyRow(
                    'Pause Active Downloads',
                    'Best-effort pause gate for active jobs.',
                    'pause_active_downloads',
                  )}
                  {renderPolicyRow(
                    'Quarantine Failed Models',
                    'Mark failed artifacts as quarantined in discovery.',
                    'quarantine_failed_models',
                  )}
                  {renderPolicyRow(
                    'Require License Acceptance',
                    'Record acceptance before the executor starts.',
                    'require_license_acceptance',
                  )}
                </div>

                <div className="space-y-2 rounded-xl border border-border/50 bg-muted/20 px-4 py-3">
                  <Label htmlFor="max-concurrent-downloads">
                    Max concurrent downloads
                  </Label>
                  <Input
                    id="max-concurrent-downloads"
                    type="number"
                    min={1}
                    max={8}
                    value={policy.max_concurrent_downloads}
                    onChange={(event) =>
                      updatePolicyField(
                        'max_concurrent_downloads',
                        Math.min(Math.max(Number(event.target.value) || 1, 1), 8),
                      )
                    }
                  />
                </div>

                <div className="flex justify-end">
                  <Button
                    type="button"
                    onClick={() => void savePolicy()}
                    disabled={savingPolicy}
                  >
                    {savingPolicy ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Save className="mr-2 h-4 w-4" aria-hidden="true" />
                    )}
                    Save Policy
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Download className="h-4 w-4 text-primary" aria-hidden="true" />
              Start Download
            </CardTitle>
            <CardDescription>
              Validate first, then queue the model through the control plane.
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-4">
            {downloadsBlocked && (
              <Alert className="border-amber-500/30 bg-amber-500/10">
                <ShieldAlert className="h-4 w-4 !text-amber-600" aria-hidden="true" />
                <AlertTitle>New downloads blocked</AlertTitle>
                <AlertDescription>
                  Backend policy is currently blocking new download jobs.
                </AlertDescription>
              </Alert>
            )}

            {channelBlocked && (
              <Alert variant="destructive">
                <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                <AlertTitle>Admin-only channel</AlertTitle>
                <AlertDescription>
                  The selected channel requires admin mode.
                </AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              <Label htmlFor="model-id">Hugging Face model ID</Label>
              <Input
                id="model-id"
                placeholder="owner/repo"
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
              />
            </div>

            <div className="flex items-start justify-between gap-4 rounded-xl border border-border/50 bg-muted/20 px-4 py-3">
              <div className="space-y-1">
                <div className="text-sm font-semibold">Accept model license</div>
                <div className="text-xs text-muted-foreground">
                  Karen will tell you during validation when acceptance is required.
                </div>
              </div>
              <Switch checked={acceptLicense} onCheckedChange={setAcceptLicense} />
            </div>

            <details className="rounded-xl border border-border/50 bg-muted/10">
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">
                Advanced install options
              </summary>
              <div className="space-y-4 border-t border-border/40 p-4">
                <div className="space-y-2">
                  <Label htmlFor="revision">Revision</Label>
                  <Input
                    id="revision"
                    placeholder="main, commit SHA, or tag"
                    value={revision}
                    onChange={(event) => setRevision(event.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="channel">Runtime channel</Label>
                  <Select
                    value={channelId || '__auto__'}
                    onValueChange={(value) =>
                      setChannelId(value === '__auto__' ? '' : value)
                    }
                  >
                    <SelectTrigger id="channel">
                      <SelectValue placeholder="Automatic" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__auto__">Automatic (recommended)</SelectItem>
                      {channels.map((channel) => (
                        <SelectItem key={channel.id} value={channel.id}>
                          {channel.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    {currentChannel
                      ? currentChannel.description
                      : 'Karen will infer the safest compatible runtime channel from model metadata.'}
                  </p>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="include-patterns">Include files</Label>
                    <Input
                      id="include-patterns"
                      placeholder="*.safetensors, *.json"
                      value={includePatterns}
                      onChange={(event) => setIncludePatterns(event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="exclude-patterns">Exclude files</Label>
                    <Input
                      id="exclude-patterns"
                      placeholder="*.bin, *.msgpack"
                      value={excludePatterns}
                      onChange={(event) => setExcludePatterns(event.target.value)}
                    />
                  </div>
                </div>

                <div className="flex items-start justify-between gap-4 rounded-xl border border-border/50 bg-background/40 px-4 py-3">
                  <div className="space-y-1">
                    <div className="text-sm font-semibold">Allow remote model code</div>
                    <div className="text-xs text-muted-foreground">
                      Off by default. Only enable for a model you explicitly trust and when runtime policy permits it.
                    </div>
                  </div>
                  <Switch
                    checked={trustRemoteCode}
                    disabled={!adminMode}
                    onCheckedChange={setTrustRemoteCode}
                  />
                </div>
              </div>
            </details>

            {validation && (
              <div
                className={[
                  'rounded-xl border px-4 py-3',
                  validation.allowed
                    ? 'border-emerald-500/30 bg-emerald-500/10'
                    : 'border-red-500/30 bg-red-500/10',
                ].join(' ')}
              >
                <div className="flex items-center gap-2 text-sm font-semibold">
                  {validation.allowed ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden="true" />
                  ) : (
                    <ShieldAlert className="h-4 w-4 text-red-600" aria-hidden="true" />
                  )}
                  {validation.allowed ? 'Validation passed' : 'Validation blocked'}
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-border/40 bg-background/40 p-2 text-xs">
                    <span className="text-muted-foreground">Runtime</span>
                    <div className="mt-1 font-semibold">
                      {validation.detected_runtime || 'Not resolved'}
                    </div>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-background/40 p-2 text-xs">
                    <span className="text-muted-foreground">Model size</span>
                    <div className="mt-1 font-semibold">
                      {formatBytes(Number(validation.metadata.total_size || 0))}
                    </div>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-background/40 p-2 text-xs">
                    <span className="text-muted-foreground">License</span>
                    <div className="mt-1 font-semibold">
                      {String(validation.metadata.license || 'Not reported')}
                    </div>
                  </div>
                  <div className="rounded-lg border border-border/40 bg-background/40 p-2 text-xs">
                    <span className="text-muted-foreground">Install location</span>
                    <div className="mt-1 truncate font-mono text-[10px]" title={validation.install_path || ''}>
                      {validation.install_path || 'Not resolved'}
                    </div>
                  </div>
                </div>
                {validation.metadata.description ? (
                  <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                    {String(validation.metadata.description)}
                  </p>
                ) : null}
                {validation.warnings.length > 0 && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {validation.warnings.join(' • ')}
                  </p>
                )}
                {validation.blocking_reasons.length > 0 && (
                  <p className="mt-2 text-xs font-medium text-red-700">
                    {validation.blocking_reasons.join(' • ')}
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => void validateDownload()}
                disabled={validating || !modelId.trim()}
              >
                {validating && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                )}
                Validate
              </Button>
              <Button
                type="button"
                onClick={() => void startDownload()}
                disabled={!canQueueDownload}
              >
                {startingDownload ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Download className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                Queue Download
              </Button>
            </div>

            <p className="text-xs text-muted-foreground">
              Pause and cancel are best-effort once the executor is already running.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <RefreshCw className="h-4 w-4 text-primary" aria-hidden="true" />
            Download Queue
          </CardTitle>
          <CardDescription>
            Active and historical model download jobs from the control plane.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {jobs.length === 0 ? (
            <div className="flex h-32 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border/60 bg-muted/5 text-sm text-muted-foreground">
              <Download className="h-8 w-8 opacity-20" aria-hidden="true" />
              No active or recent download jobs.
            </div>
          ) : (
            <div className="space-y-4">
              {jobs.map((job) => (
                <div
                  key={job.job_id}
                  className={[
                    'rounded-xl border p-4 shadow-sm transition-colors',
                    statusTone(job.status),
                  ].join(' ')}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center gap-2 font-semibold">
                        <span className="truncate">{job.model_id}</span>
                        {job.revision && (
                          <Badge variant="secondary" className="text-[10px] font-mono">
                            {job.revision}
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs opacity-90">{job.message}</div>
                    </div>

                    <div className="flex items-center gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        disabled={!canPauseJob(job.status) || busyJobs[job.job_id]}
                        onClick={() => void actOnJob(job.job_id, 'pause')}
                      >
                        <Pause className="h-4 w-4" aria-hidden="true" />
                        <span className="sr-only">Pause</span>
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        disabled={!canResumeJob(job.status) || busyJobs[job.job_id]}
                        onClick={() => void actOnJob(job.job_id, 'resume')}
                      >
                        <Play className="h-4 w-4" aria-hidden="true" />
                        <span className="sr-only">Resume</span>
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-destructive hover:bg-destructive/10 hover:text-destructive"
                        disabled={!canCancelJob(job.status) || busyJobs[job.job_id]}
                        onClick={() => void actOnJob(job.job_id, 'cancel')}
                      >
                        <Square className="h-4 w-4" aria-hidden="true" />
                        <span className="sr-only">Cancel</span>
                      </Button>
                      {(job.status === 'failed' || job.status === 'cancelled') && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          disabled={retryingJobs[job.job_id]}
                          onClick={() => void retryJob(job)}
                        >
                          {retryingJobs[job.job_id] ? (
                            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                          ) : (
                            <RotateCcw className="h-4 w-4" aria-hidden="true" />
                          )}
                          <span className="sr-only">Retry download</span>
                        </Button>
                      )}
                    </div>
                  </div>

                  <div className="mt-4 space-y-2">
                    <div className="h-2 w-full overflow-hidden rounded-full bg-black/10">
                      <div
                        className="h-full bg-current transition-all duration-500"
                        style={{ width: `${normalizeProgress(job.progress)}%` }}
                        role="progressbar"
                        aria-valuenow={normalizeProgress(job.progress)}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      />
                    </div>
                    <div className="flex items-center justify-between text-[10px] font-medium opacity-80">
                      <span>{normalizeProgress(job.progress).toFixed(1)}%</span>
                      <span className="capitalize">{job.status.replace('_', ' ')}</span>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5 text-[9px]">
                    {job.detected_runtime && (
                      <Badge variant="outline">{job.detected_runtime}</Badge>
                    )}
                    {job.detected_modality && (
                      <Badge variant="outline">{job.detected_modality}</Badge>
                    )}
                    {job.result?.total_size ? (
                      <Badge variant="outline">
                        {formatBytes(Number(job.result.total_size))}
                      </Badge>
                    ) : null}
                  </div>
                  {job.error && (
                    <p className="mt-2 rounded-lg bg-destructive/10 p-2 text-xs text-destructive">
                      {job.error}
                    </p>
                  )}
                  {job.warnings.length > 0 && (
                    <p className="mt-2 text-xs opacity-80">{job.warnings.join(' • ')}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="border-border/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <HardDrive className="h-4 w-4 text-primary" aria-hidden="true" />
              Installed Models
            </CardTitle>
            <CardDescription>
              Inventory of locally cached model artifacts.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-3">
              <h3 className="text-sm font-semibold">vLLM Compatible</h3>
              {vllmInstalledModels.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground">
                  No vLLM-compatible models found.
                </div>
              ) : (
                <div className="space-y-2">
                  {vllmInstalledModels.map((model, idx) => (
                    <div
                      key={`${model.id}-${idx}`}
                      className="rounded-xl border border-border/50 bg-muted/20 p-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="truncate text-sm font-semibold">
                            {model.name || model.id}
                          </div>
                          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                            <span>{formatBytes(model.size_bytes)}</span>
                            <span>•</span>
                            <span>{model.source || 'local'}</span>
                          </div>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                          disabled={removingModels[model.id]}
                          onClick={() => void removeInstalledModel(model.id)}
                        >
                          {removingModels[model.id] ? (
                            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                          ) : (
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          )}
                          <span className="sr-only">Remove {model.name || model.id}</span>
                        </Button>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {safeStringList(model.capabilities).map((cap) => (
                          <Badge
                            key={cap}
                            variant="secondary"
                            className="text-[9px] px-1.5 py-0 h-4"
                          >
                            {cap}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <Separator className="bg-border/40" />

            <div className="space-y-3">
              <h3 className="text-sm font-semibold">Other Runtimes</h3>
              {otherInstalledModels.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground">
                  No other model runtimes found.
                </div>
              ) : (
                <div className="space-y-2">
                  {otherInstalledModels.map((model, idx) => (
                    <div
                      key={`${model.id}-${idx}`}
                      className="rounded-xl border border-border/50 bg-muted/20 p-3"
                    >

                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="truncate text-sm font-semibold">
                            {model.name || model.id}
                          </div>
                          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                            <span>{formatBytes(model.size_bytes)}</span>
                            <span>•</span>
                            <span>{model.source || 'local'}</span>
                          </div>
                        </div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                          disabled={removingModels[model.id]}
                          onClick={() => void removeInstalledModel(model.id)}
                        >
                          {removingModels[model.id] ? (
                            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                          ) : (
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          )}
                          <span className="sr-only">Remove {model.name || model.id}</span>
                        </Button>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {safeStringList(model.capabilities).map((cap) => (
                          <Badge
                            key={cap}
                            variant="secondary"
                            className="text-[9px] px-1.5 py-0 h-4"
                          >
                            {cap}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card className="border-border/50">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />
                Local Model Health
              </CardTitle>
              <CardDescription>
                What Karen can currently see in the local model inventory.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-2">
                {Object.entries(discoveryStats)
                  .slice(0, 6)
                  .map(([key, value]) => (
                    <div
                      key={key}
                      className="rounded-lg border border-border/50 bg-muted/20 p-3"
                    >
                      <div className="text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {key.replace(/_/g, ' ')}
                      </div>
                      <div className="mt-1 text-sm font-semibold">
                        {typeof value === 'object'
                          ? 'Available'
                          : String(value ?? 'Unknown')}
                      </div>
                    </div>
                  ))}
              </div>

              <details className="rounded-lg border border-border/50 bg-muted/10">
                <summary className="cursor-pointer px-3 py-2 text-xs font-semibold">
                  Technical discovery details
                </summary>
                <div className="space-y-3 border-t border-border/40 p-3">
                  <pre className="overflow-auto rounded-lg bg-background/50 p-3 text-[10px] font-mono leading-relaxed">
                    {JSON.stringify(discoveryProgress, null, 2)}
                  </pre>
                  <pre className="overflow-auto rounded-lg bg-background/50 p-3 text-[10px] font-mono leading-relaxed">
                    {JSON.stringify(discoveryStats, null, 2)}
                  </pre>
                </div>
              </details>
            </CardContent>
          </Card>

          <Card className="border-border/50">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <HardDrive className="h-4 w-4 text-primary" aria-hidden="true" />
                Channel Structure
              </CardTitle>
              <CardDescription>
                Download channel groupings and gated storage roots.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {Object.entries(groupedChannels).map(([group, channelsInGroup]) => (
                  <div key={group} className="space-y-2">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                      {group}
                    </h3>
                    <div className="grid gap-2">
                      {channelsInGroup.map((channel) => (
                        <div
                          key={channel.id}
                          className="rounded-lg border border-border/40 bg-muted/10 p-2 text-xs"
                        >
                          <div className="flex items-center justify-between font-semibold">
                            <span>{channel.label}</span>
                            <Badge variant="outline" className="text-[9px] h-4">
                              {channel.id}
                            </Badge>
                          </div>
                          <div className="mt-1 text-muted-foreground line-clamp-2">
                            {channel.description}
                          </div>
                          <div className="mt-2 flex items-center justify-between text-[9px] text-muted-foreground">
                            <span>
                              Root: <span className="font-mono">{channel.storage_key}</span>
                            </span>
                            {channel.admin_only && (
                              <Badge variant="destructive" className="h-3 text-[8px] px-1">
                                Admin Only
                              </Badge>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}