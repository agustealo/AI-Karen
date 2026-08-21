"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Bot,
  CheckCircle2,
  ExternalLink,
  KeyRound,
  Loader2,
  RefreshCw,
  Save,
  Server,
  HardDrive,
  XCircle,
  PlusCircle,
  ShieldCheck,
  Settings2,
  Info,
  InfoIcon,
  Sparkles,
  Square,
} from 'lucide-react';
import { Alert, AlertDescription } from '../ui/alert';
import { Label } from '../ui/label';
import { Input } from '../ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue, SelectSeparator } from '../ui/select';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Separator } from '../ui/separator';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';
import { ApiError, apiClient } from '@/lib/api';
import { useIsMobile } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';
import {
  getRuntimeDisplayName,
} from '@/lib/chat-response';
import {
  normalizeModelSettingsResponse,
  type RuntimeSettingsResponse,
  sortProviderModels,
} from '@/lib/model-runtime-inventory';

interface ProviderModel {
  id: string;
  name: string;
  family?: string;
  source?: string;
  compatible_runtimes?: string[];
  preferred_runtime?: string | null;
  compatibility_confidence?: string | null;
  model_format?: string | null;
  artifact_kind?: string | null;
}

type ModelSettingsResponse = RuntimeSettingsResponse & {
  chat_response_mode?: unknown;
};

type ChatResponseMode = 'streaming_first' | 'auto' | 'non_streaming';

const CHAT_RESPONSE_MODES: ChatResponseMode[] = [
  'streaming_first',
  'auto',
  'non_streaming',
];

interface ProviderModelsResponse {
  provider: string;
  base_url?: string | null;
  models: ProviderModel[];
}

function formatErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function formatExecutionFamilyLabel(value: string): string {
  switch (value) {
    case 'builtin_runtime':
      return 'Built-in runtime';
    case 'first_class_adapter':
      return 'First-class adapter';
    case 'openai_compatible':
    case 'openai_compatible_unknown':
      return 'OpenAI-compatible shared adapter';
    case 'emergency_adapter':
      return 'Emergency fallback adapter';
    default:
      return value.replace(/_/g, ' ');
  }
}

function formatProviderCredentialMessage(providerName: string, message: string): string {
  const trimmed = message.trim();
  const lowered = trimmed.toLowerCase();

  if (lowered.includes('token expired') || lowered.includes('expired') || lowered.includes('incorrect') || lowered.includes('401') || lowered.includes('unauthorized')) {
    return `${providerName} rejected the saved credential. Replace the stored API key/token and try again.`;
  }

  if (lowered.includes('api key') || lowered.includes('credential') || lowered.includes('forbidden')) {
    return `${providerName} credential validation failed: ${trimmed}`;
  }

  return `${providerName} validation failed: ${trimmed}`;
}

function normalizeChatResponseMode(value: unknown): ChatResponseMode {
  return CHAT_RESPONSE_MODES.includes(value as ChatResponseMode)
    ? (value as ChatResponseMode)
    : 'streaming_first';
}

function normalizeDisplayBaseUrl(address?: string | null): string {
  return (address || '').trim().replace(/\/api\/?$/, '').replace(/\/$/, '');
}

const PROVIDER_TYPE_LABELS: Record<string, string> = {
  'local': 'Local',
  'remote': 'Remote',
  'hybrid': 'Local (Hybrid)',
  'builtin': 'Built-in',
  'custom': 'Custom',
};

export default function ModelSettings() {
  const isMobile = useIsMobile();
  const [settings, setSettings] = useState<ModelSettingsResponse | null>(null);
  const [selectedProvider, setSelectedProvider] = useState('builtin_vllm');
  const [selectedModel, setSelectedModel] = useState('');
  const [runtimeSource, setRuntimeSource] = useState<'host' | 'container'>('host');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [isEditingApiKey, setIsEditingApiKey] = useState(false);
  const [apiKeyHeader, setApiKeyHeader] = useState('Authorization');
  const [apiKeyPrefix, setApiKeyPrefix] = useState('Bearer');
  const [availableModels, setAvailableModels] = useState<ProviderModel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [isClearingKey, setIsClearingKey] = useState(false);
  const [chatResponseMode, setChatResponseMode] = useState<ChatResponseMode>('streaming_first');

  // Custom Provider State
  const [isCustomDialogOpen, setIsCustomDialogOpen] = useState(false);
  const [isAddingCustom, setIsAddingCustom] = useState(false);
  const [customProviderForm, setCustomProviderForm] = useState({
    name: '',
    displayName: '',
    description: '',
    baseUrl: '',
    model: '',
    authHeader: 'Authorization',
    authPrefix: 'Bearer',
  });

  const [apiKeyValidationState, setApiKeyValidationState] = useState<'idle' | 'validating' | 'valid' | 'invalid'>('idle');
  const [apiKeyValidationMessage, setApiKeyValidationMessage] = useState('');
  const validationRequestId = useRef(0);
  const { toast } = useToast();

  const normalizedSettings = useMemo(
    () => (settings ? normalizeModelSettingsResponse(settings) : null),
    [settings],
  );

  const canSelectProvider = useCallback((provider?: { selectable?: boolean; requires_api_key?: boolean } | null) => {
    if (!provider) return false;
    if (provider.selectable !== false) return true;
    return Boolean(provider.requires_api_key);
  }, []);

  const selectedProviderDetails = useMemo(() => {
    return normalizedSettings?.providers.find((p) => p.id === selectedProvider) ?? null;
  }, [normalizedSettings, selectedProvider]);

  const selectableCloudProviders = useMemo(
    () => (normalizedSettings?.thirdPartyProviders || []).filter((provider) => canSelectProvider(provider)),
    [normalizedSettings?.thirdPartyProviders, canSelectProvider],
  );

  const selectedProviderLabel = useMemo(() => {
    if (!selectedProviderDetails) return '';
    return getRuntimeDisplayName(selectedProviderDetails.id, selectedProviderDetails.display_name);
  }, [selectedProviderDetails]);

  const connectionTarget = useMemo(() => {
    const value = selectedProviderDetails?.safe_diagnostic_metadata?.connection_target;
    return typeof value === 'string' ? value : '';
  }, [selectedProviderDetails]);

  const usesRuntimeOptions = Boolean(selectedProviderDetails?.runtime_options?.length);

  const selectedRuntimeOption = useMemo(() => {
    if (!usesRuntimeOptions) return null;
    return selectedProviderDetails?.runtime_options?.find((option) => option.source === runtimeSource) ?? null;
  }, [selectedProviderDetails, runtimeSource, usesRuntimeOptions]);

  const fallbackProviderModels = useMemo(
    () =>
      (selectedProviderDetails?.models ?? []).map((model) => ({
        id: model.id,
        name: model.name,
        source: model.source ?? 'runtime',
      })),
    [selectedProviderDetails],
  );

  const applyNormalizedSettings = useCallback((response: ModelSettingsResponse) => {
    const normalized = normalizeModelSettingsResponse(response);
    setSettings(response);
    setSelectedProvider(normalized.selected_provider);
    setSelectedModel(normalized.selected_model);
    setChatResponseMode(normalizeChatResponseMode(response.chat_response_mode));
    setApiKey('');
    setIsEditingApiKey(false);
    setApiKeyValidationState('idle');
    setApiKeyValidationMessage('');
    return normalized;
  }, []);

  const loadSettings = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await apiClient.get<ModelSettingsResponse>('/api/settings/model');
      applyNormalizedSettings(response);
    } catch (error) {
      toast({
        title: 'Unable to load model settings',
        description: formatErrorMessage(error, 'Karen could not load the saved model configuration.'),
        variant: 'destructive',
      });
    } finally {
      setIsLoading(false);
    }
  }, [applyNormalizedSettings, toast]);

  const loadProviderModels = useCallback(async (
    providerId: string,
    providerBaseUrl?: string,
    fallbackModels: ProviderModel[] = [],
  ) => {
    if (!providerId) return;
    setIsLoadingModels(true);
    try {
      const query = providerBaseUrl?.trim() ? `?base_url=${encodeURIComponent(providerBaseUrl.trim())}` : '';
      const response = await apiClient.get<ProviderModelsResponse>(`/api/settings/model/providers/${encodeURIComponent(providerId)}/models${query}`);
      setAvailableModels(sortProviderModels(response.models || []));
    } catch (error) {
      setAvailableModels(fallbackModels);
      toast({
        title: 'Model discovery failed',
        description: formatErrorMessage(error, `Karen could not refresh models for ${providerId}.`),
        variant: 'destructive',
      });
    } finally {
      setIsLoadingModels(false);
    }
  }, [toast]);

  useEffect(() => { void loadSettings(); }, [loadSettings]);

  useEffect(() => {
    if (!selectedProviderDetails) return;
    const providerDefaultModel = selectedProviderDetails.selected_model || selectedProviderDetails.default_model || selectedProviderDetails.models[0]?.id || '';
    const providerBaseUrl = usesRuntimeOptions
      ? normalizeDisplayBaseUrl(selectedProviderDetails.base_url || selectedProviderDetails.default_base_url || '')
      : (selectedProviderDetails.base_url || selectedProviderDetails.default_base_url || '');
    if (usesRuntimeOptions) {
      setRuntimeSource(selectedProviderDetails.runtime_source === 'container' ? 'container' : 'host');
    }
    setBaseUrl(usesRuntimeOptions ? providerBaseUrl : normalizeDisplayBaseUrl(providerBaseUrl));
    setApiKey('');
    setIsEditingApiKey(false);
    setApiKeyValidationState('idle');
    setApiKeyValidationMessage('');
    setApiKeyHeader(selectedProviderDetails.api_key_header || 'Authorization');
    setApiKeyPrefix(selectedProviderDetails.api_key_prefix ?? 'Bearer');
    setAvailableModels(fallbackProviderModels);
    setSelectedModel(providerDefaultModel);
    void loadProviderModels(selectedProviderDetails.id, providerBaseUrl, fallbackProviderModels);
  }, [fallbackProviderModels, loadProviderModels, selectedProviderDetails, usesRuntimeOptions]);

  useEffect(() => {
    if (!usesRuntimeOptions) return;
    if (!selectedRuntimeOption) return;
    setBaseUrl(normalizeDisplayBaseUrl(selectedRuntimeOption.base_url));
  }, [selectedProviderDetails, selectedRuntimeOption, usesRuntimeOptions]);

  useEffect(() => {
    if (!selectedProviderDetails?.requires_api_key || !isEditingApiKey) {
      setApiKeyValidationState(selectedProviderDetails?.api_key_configured ? 'valid' : 'idle');
      setApiKeyValidationMessage(
        selectedProviderDetails?.api_key_configured
          ? `${selectedProviderLabel || selectedProviderDetails?.display_name} key is stored.`
          : '',
      );
      return;
    }
    const candidateKey = apiKey.trim();
    if (!candidateKey) {
      setApiKeyValidationState(selectedProviderDetails.api_key_configured ? 'valid' : 'idle');
      setApiKeyValidationMessage('');
      return;
    }
    const currentRequestId = ++validationRequestId.current;
    setApiKeyValidationState('validating');
    setApiKeyValidationMessage(`Validating ${selectedProviderLabel || selectedProviderDetails.display_name} key...`);

    const timeoutId = window.setTimeout(async () => {
      try {
        const response = await apiClient.post<{ valid: boolean; message: string; }>('/api/settings/model/validate', {
          provider: selectedProviderDetails.id,
          model: selectedModel,
          api_key: candidateKey,
          base_url: selectedProviderDetails.supports_base_url_override ? baseUrl.trim() || undefined : undefined,
        });
        if (validationRequestId.current !== currentRequestId) return;
        setApiKeyValidationState(response.valid ? 'valid' : 'invalid');
        setApiKeyValidationMessage(
          response.valid
            ? response.message
            : formatProviderCredentialMessage(selectedProviderLabel || selectedProviderDetails.display_name, response.message),
        );
      } catch (error) {
        if (validationRequestId.current !== currentRequestId) return;
        setApiKeyValidationState('invalid');
        setApiKeyValidationMessage(
          formatProviderCredentialMessage(
            selectedProviderLabel || selectedProviderDetails.display_name,
            formatErrorMessage(error, `Unable to validate ${selectedProviderLabel || selectedProviderDetails.display_name} key.`),
          ),
        );
      }
    }, 450);
    return () => { window.clearTimeout(timeoutId); };
  }, [apiKey, baseUrl, isEditingApiKey, selectedModel, selectedProviderDetails, selectedProviderLabel]);

  const validateProviderCredentialsBeforeSave = async (): Promise<boolean> => {
    if (!selectedProviderDetails?.requires_api_key) return true;

    if (apiKeyValidationState === 'validating') {
      const message = `Validation for ${selectedProviderLabel || selectedProviderDetails.display_name} is still in progress. Wait for it to finish before saving.`;
      setApiKeyValidationState('invalid');
      setApiKeyValidationMessage(message);
      toast({ title: 'Credential check still running', description: message, variant: 'destructive' });
      return false;
    }

    try {
      const response = await apiClient.post<{ valid: boolean; message: string; }>('/api/settings/model/validate', {
        provider: selectedProviderDetails.id,
        model: selectedModel.trim(),
        api_key: apiKey.trim() || undefined,
        base_url: selectedProviderDetails.supports_base_url_override ? baseUrl.trim() || undefined : undefined,
      });

      if (!response.valid) {
        const message = formatProviderCredentialMessage(selectedProviderLabel || selectedProviderDetails.display_name, response.message);
        setApiKeyValidationState('invalid');
        setApiKeyValidationMessage(message);
        setIsEditingApiKey(true);
        toast({
          title: `${selectedProviderLabel || selectedProviderDetails.display_name} credential rejected`,
          description: message,
          variant: 'destructive',
        });
        return false;
      }

      setApiKeyValidationState('valid');
      setApiKeyValidationMessage(response.message);
      return true;
    } catch (error) {
      const message = formatProviderCredentialMessage(
        selectedProviderLabel || selectedProviderDetails.display_name,
        formatErrorMessage(error, `Unable to validate ${selectedProviderLabel || selectedProviderDetails.display_name} key.`),
      );
      setApiKeyValidationState('invalid');
      setApiKeyValidationMessage(message);
      setIsEditingApiKey(true);
      toast({
        title: `${selectedProviderLabel || selectedProviderDetails.display_name} credential rejected`,
        description: message,
        variant: 'destructive',
      });
      return false;
    }
  };

  const handleSave = async () => {
    if (!selectedProviderDetails) return;
    if (!selectedModel.trim()) {
      toast({ title: 'Model required', description: 'Select or enter the model Karen should use.', variant: 'destructive' });
      return;
    }
    setIsSaving(true);
    try {
      const submittedApiKey = isEditingApiKey ? apiKey.trim() : '';
      if (selectedProviderDetails.requires_api_key) {
        const needsNewKey = isEditingApiKey || !selectedProviderDetails.api_key_configured;
        if (needsNewKey) {
          const credentialsValid = await validateProviderCredentialsBeforeSave();
          if (!credentialsValid) return;
        }
      } else if (submittedApiKey && apiKeyValidationState === 'invalid') {
        throw new Error(apiKeyValidationMessage || `${selectedProviderLabel || selectedProviderDetails.display_name} API key validation failed.`);
      }
      const response = await apiClient.put<ModelSettingsResponse>('/api/settings/model', {
        provider: selectedProvider,
        model: selectedModel.trim(),
        base_url: selectedProviderDetails.supports_base_url_override ? baseUrl.trim() : undefined,
        runtime_source: usesRuntimeOptions ? runtimeSource : undefined,
        api_key: submittedApiKey || undefined,
        api_key_header: selectedProviderDetails.supports_custom_auth ? apiKeyHeader.trim() : undefined,
        api_key_prefix: selectedProviderDetails.supports_custom_auth ? apiKeyPrefix : undefined,
        chat_response_mode: chatResponseMode,
      });
      applyNormalizedSettings(response);
      toast({ title: 'Model settings saved', description: `${selectedProviderLabel || selectedProviderDetails.display_name} is configured.` });
    } catch (error) {
      const message = formatProviderCredentialMessage(
        selectedProviderLabel || selectedProviderDetails.display_name,
        formatErrorMessage(error, 'Karen could not save configuration.'),
      );
      setApiKeyValidationState('invalid');
      setApiKeyValidationMessage(message);
      setIsEditingApiKey(true);
      toast({ title: `Save failed for ${selectedProviderLabel || selectedProviderDetails.display_name}`, description: message, variant: 'destructive' });
    } finally { setIsSaving(false); }
  };

  const handleClearApiKey = async () => {
    if (!selectedProviderDetails?.api_key_configured) return;
    setIsClearingKey(true);
    try {
      const response = await apiClient.put<ModelSettingsResponse>('/api/settings/model', {
        provider: selectedProvider,
        model: selectedModel.trim(),
        runtime_source: usesRuntimeOptions ? runtimeSource : undefined,
        clear_api_key: true,
      });
      applyNormalizedSettings(response);
      setApiKey('');
      toast({ title: 'API key removed', description: `${selectedProviderLabel || selectedProviderDetails.display_name} credentials cleared.` });
    } catch (error) {
      toast({ title: 'Unable to clear API key', description: formatErrorMessage(error, 'Failed to clear credential.'), variant: 'destructive' });
    } finally { setIsClearingKey(false); }
  };

  const handleCreateCustomProvider = async () => {
    if (!customProviderForm.name.trim() || !customProviderForm.displayName.trim() || !customProviderForm.baseUrl.trim() || !customProviderForm.model.trim()) {
      toast({ title: 'Missing details', description: 'All fields except description are required.', variant: 'destructive' });
      return;
    }
    setIsAddingCustom(true);
    try {
      const response = await apiClient.post<ModelSettingsResponse>('/api/settings/model/providers/custom', {
        name: customProviderForm.name.trim(),
        display_name: customProviderForm.displayName.trim(),
        description: customProviderForm.description.trim() || undefined,
        base_url: customProviderForm.baseUrl.trim(),
        model: customProviderForm.model.trim(),
        api_key_header: customProviderForm.authHeader.trim() || undefined,
        api_key_prefix: customProviderForm.authPrefix,
      });
      applyNormalizedSettings(response);
      setIsCustomDialogOpen(false);
      setCustomProviderForm({ name: '', displayName: '', description: '', baseUrl: '', model: '', authHeader: 'Authorization', authPrefix: 'Bearer' });
      toast({ title: 'Custom provider added', description: `${customProviderForm.displayName} is now available.` });
    } catch (error) {
      toast({ title: 'Failed to add provider', description: formatErrorMessage(error, 'Could not create provider.'), variant: 'destructive' });
    } finally { setIsAddingCustom(false); }
  };

  if (isLoading) {
    return (
      <Card className="border-none bg-transparent shadow-none">
        <CardContent className="flex h-64 items-center justify-center">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">Initializing Model Intelligence...</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className={cn("grid gap-8 pb-32", !isMobile && "grid-cols-12")}>
        {/* Main Configuration Card */}
        <div className={cn("space-y-6", !isMobile ? "col-span-12 xl:col-span-8" : "w-full")}>
          <Card className="border-border/40 shadow-sm transition-all hover:shadow-md">
            <CardHeader className="border-b bg-muted/20 pb-4">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-xl font-bold flex items-center gap-2">
                    <Bot className="h-5 w-5 text-primary" /> Model Selection
                  </CardTitle>
                  <CardDescription>Select the brain and runtime environment for Karen.</CardDescription>
                </div>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="outline" size="icon" className="rounded-full">
                        <InfoIcon className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs">
                      Provider behavior depends on backend runtime availability, credential status, and configured fallback policy.
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </CardHeader>
            <CardContent className="pt-6 space-y-8">
              {/* Provider Selection */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <Label htmlFor="ai-provider" className="text-sm font-semibold uppercase tracking-wider text-muted-foreground/80">Select Provider</Label>
                  <Dialog open={isCustomDialogOpen} onOpenChange={setIsCustomDialogOpen}>
                    <DialogTrigger asChild>
                      <Button variant="ghost" size="sm" className="h-8 text-primary hover:text-primary hover:bg-primary/5">
                        <PlusCircle className="mr-2 h-4 w-4" /> Add Custom
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="sm:max-w-[500px]">
                      <DialogHeader>
                        <DialogTitle>Add Custom AI Provider</DialogTitle>
                        <DialogDescription>Add any OpenAI-compatible endpoint that Karen should communicate with.</DialogDescription>
                      </DialogHeader>
                      <div className="grid gap-4 py-4">
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label htmlFor="c-p-id">Unique ID</Label>
                            <Input id="c-p-id" value={customProviderForm.name} onChange={(e) => setCustomProviderForm({...customProviderForm, name: e.target.value})} placeholder="e.g. together-ai" />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="c-p-display">Display Name</Label>
                            <Input id="c-p-display" value={customProviderForm.displayName} onChange={(e) => setCustomProviderForm({...customProviderForm, displayName: e.target.value})} placeholder="Together AI" />
                          </div>
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="c-p-url">Base URL</Label>
                          <Input id="c-p-url" value={customProviderForm.baseUrl} onChange={(e) => setCustomProviderForm({...customProviderForm, baseUrl: e.target.value})} placeholder="https://api.together.xyz/v1" />
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-2">
                            <Label htmlFor="c-p-model">Default Model</Label>
                            <Input id="c-p-model" value={customProviderForm.model} onChange={(e) => setCustomProviderForm({...customProviderForm, model: e.target.value})} placeholder="mistralai/Mixtral-8x7B" />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="c-p-header">Auth Header</Label>
                            <Input id="c-p-header" value={customProviderForm.authHeader} onChange={(e) => setCustomProviderForm({...customProviderForm, authHeader: e.target.value})} />
                          </div>
                        </div>
                      </div>
                      <DialogFooter>
                        <Button variant="outline" onClick={() => setIsCustomDialogOpen(false)}>Cancel</Button>
                        <Button onClick={handleCreateCustomProvider} disabled={isAddingCustom}>
                          {isAddingCustom ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />} Create Provider
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                </div>

                {!selectableCloudProviders.length ? (
                  <Alert className="border-border/60 bg-muted/20 text-muted-foreground">
                    <Info className="h-4 w-4" />
                    <AlertDescription>
                      No active cloud providers are configured. Built-in runtimes are still available.
                    </AlertDescription>
                  </Alert>
                ) : null}
                
                <Select
                  value={selectedProvider}
                  onValueChange={(providerId) => {
                    const provider = normalizedSettings?.providers.find((item) => item.id === providerId);

                    if (!canSelectProvider(provider)) {
                      toast({
                        title: 'Provider unavailable',
                        description: 'This provider is currently unavailable.',
                        variant: 'destructive',
                      });
                      return;
                    }

                    setSelectedProvider(providerId);
                  }}
                >
                  <SelectTrigger id="ai-provider" className="h-12 border-border/60 bg-background text-base font-medium transition-all hover:border-primary/40 focus:ring-primary/20">
                    <SelectValue placeholder="Identify your AI runtime..." />
                  </SelectTrigger>
                  <SelectContent className="max-h-[min(80vh,500px)]">
                    <SelectGroup>
                      <SelectLabel className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground"><Server className="h-3 w-3" /> Built-in Runtime</SelectLabel>
                      {normalizedSettings?.builtInProviders.map((p) => (
                        <SelectItem
                          key={p.id}
                          value={p.id}
                          disabled={!canSelectProvider(p)}
                          className="cursor-pointer py-3 text-foreground hover:bg-primary/5 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45"
                        >
                          <div className="flex items-center gap-3">
                            <span className="font-semibold">{getRuntimeDisplayName(p.id, p.display_name)}</span>
                            <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-primary/70">Core</Badge>
                            {p.selectable === false && !p.requires_api_key ? (
                              <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-muted-foreground/70">
                                Locked
                              </Badge>
                            ) : p.requires_api_key && !p.api_key_configured ? (
                              <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-amber-600/70">
                                Needs Key
                              </Badge>
                            ) : null}
                          </div>
                        </SelectItem>
                      ))}
                    </SelectGroup>
                    <SelectSeparator className="my-2" />
                    <SelectGroup>
                      <SelectLabel className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground"><HardDrive className="h-3 w-3" /> Local Providers</SelectLabel>
                      {normalizedSettings?.localProviders.map((p) => (
                        <SelectItem
                          key={p.id}
                          value={p.id}
                          disabled={!canSelectProvider(p)}
                          className="cursor-pointer py-3 text-foreground hover:bg-primary/5 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45"
                        >
                          <div className="flex items-center gap-3">
                            <span className="font-semibold">{getRuntimeDisplayName(p.id, p.display_name)}</span>
                            <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-emerald-600/70">Local</Badge>
                            {p.selectable === false && !p.requires_api_key ? (
                              <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-muted-foreground/70">
                                Locked
                              </Badge>
                            ) : p.requires_api_key && !p.api_key_configured ? (
                              <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-amber-600/70">
                                Needs Key
                              </Badge>
                            ) : null}
                          </div>
                        </SelectItem>
                      ))}
                    </SelectGroup>
                    <SelectSeparator className="my-2" />
                    <SelectGroup>
                      <SelectLabel className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground"><HardDrive className="h-3 w-3" /> Cloud Providers</SelectLabel>
                      {normalizedSettings?.thirdPartyProviders.length ? (
                        normalizedSettings.thirdPartyProviders.map((p) => (
                          <SelectItem
                            key={p.id}
                            value={p.id}
                            disabled={!canSelectProvider(p)}
                            className="cursor-pointer py-3 text-foreground hover:bg-primary/5 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45"
                          >
                            <div className="flex items-center gap-3">
                              <span className="font-semibold">{getRuntimeDisplayName(p.id, p.display_name)}</span>
                              <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-emerald-600/70">Third-Party</Badge>
                              {p.selectable === false && !p.requires_api_key ? (
                                <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-muted-foreground/70">
                                  Locked
                                </Badge>
                              ) : p.requires_api_key && !p.api_key_configured ? (
                                <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-amber-600/70">
                                  Needs Key
                                </Badge>
                              ) : null}
                            </div>
                          </SelectItem>
                        ))
                      ) : (
                        <div className="rounded-xl border border-dashed border-border/50 bg-muted/5 px-3 py-2 text-xs text-muted-foreground">
                          No active cloud providers are configured. Built-in runtimes are still available.
                        </div>
                      )}
                    </SelectGroup>
                    {normalizedSettings?.customProviders.length ? (
                      <>
                        <SelectSeparator className="my-2" />
                        <SelectGroup>
                          <SelectLabel className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground"><Settings2 className="h-3 w-3" /> Custom Integrations</SelectLabel>
                          {normalizedSettings?.customProviders.map((p) => (
                            <SelectItem
                              key={p.id}
                              value={p.id}
                              disabled={!canSelectProvider(p)}
                              className="cursor-pointer py-3 text-foreground hover:bg-primary/5 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-45"
                            >
                              <div className="flex items-center gap-3">
                                <span className="font-semibold">{getRuntimeDisplayName(p.id, p.display_name)}</span>
                                <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-purple-600/70">API</Badge>
                                {p.selectable === false && !p.requires_api_key ? (
                                  <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-muted-foreground/70">
                                    Locked
                                  </Badge>
                                ) : p.requires_api_key && !p.api_key_configured ? (
                                  <Badge variant="outline" className="h-5 text-[9px] font-bold uppercase tracking-widest text-amber-600/70">
                                    Needs Key
                                  </Badge>
                                ) : null}
                              </div>
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </>
                    ) : null}
                  </SelectContent>
                </Select>
              </div>

              {/* Chat Response Mode Selection */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <Label htmlFor="chat-response-mode" className="text-sm font-semibold uppercase tracking-wider text-muted-foreground/80">Chat Response Mode</Label>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button variant="ghost" size="icon" className="rounded-full h-6 w-6">
                          <InfoIcon className="h-3.5 w-3.5" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent className="max-w-xs">
                        Controls how Karen delivers responses. Streaming first provides real-time tokens. Non-streaming waits for complete responses.
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
                <Select
                  value={chatResponseMode}
                  onValueChange={(value) => setChatResponseMode(normalizeChatResponseMode(value))}
                >
                  <SelectTrigger id="chat-response-mode" className="h-11 border-border/60 bg-muted/10 text-base font-medium transition-all hover:border-primary/40 focus:ring-primary/20">
                    <SelectValue placeholder="Select response mode..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="streaming_first">
                      <div className="flex items-center gap-2">
                        <Sparkles className="h-4 w-4 text-primary" />
                        <div>
                          <div className="font-semibold">Streaming First</div>
                          <div className="text-xs text-muted-foreground">Real-time token delivery</div>
                        </div>
                      </div>
                    </SelectItem>
                    <SelectItem value="auto">
                      <div className="flex items-center gap-2">
                        <RefreshCw className="h-4 w-4 text-primary" />
                        <div>
                          <div className="font-semibold">Auto</div>
                          <div className="text-xs text-muted-foreground">Based on provider capabilities</div>
                        </div>
                      </div>
                    </SelectItem>
                    <SelectItem value="non_streaming">
                      <div className="flex items-center gap-2">
                        <Square className="h-4 w-4 text-primary" />
                        <div>
                          <div className="font-semibold">Non-Streaming</div>
                          <div className="text-xs text-muted-foreground">Wait for complete response</div>
                        </div>
                      </div>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Separator className="bg-border/30" />

              {/* Dynamic Contextual Configuration */}
              {selectedProviderDetails && (
                <div className="animate-in fade-in slide-in-from-top-4 duration-500 space-y-8">
                  <div className="grid gap-8">
                    {/* Endpoint & Discovery Row */}
                      <div className="grid items-start gap-6 md:grid-cols-[65fr_35fr]">
                        {usesRuntimeOptions ? (
                          <div className="space-y-3 md:col-span-2 md:self-start">
                            <Label htmlFor="runtime-source" className="flex items-center gap-2 font-semibold">
                              <Server className="h-4 w-4 text-primary" /> Runtime Source
                            </Label>
                            <Select
                              value={runtimeSource}
                              onValueChange={(value: 'host' | 'container') => {
                                setRuntimeSource(value);
                                const nextOption = selectedProviderDetails.runtime_options?.find((option) => option.source === value);
                                if (nextOption) {
                                  const nextBaseUrl = normalizeDisplayBaseUrl(nextOption.base_url);
                                  setBaseUrl(nextBaseUrl);
                                  void loadProviderModels(
                                    selectedProviderDetails.id,
                                    nextBaseUrl,
                                    fallbackProviderModels,
                                  );
                                }
                              }}
                            >
                              <SelectTrigger id="runtime-source" className="h-11 bg-muted/20">
                                <SelectValue placeholder="Choose runtime source" />
                              </SelectTrigger>
                              <SelectContent>
                                {(selectedProviderDetails.runtime_options ?? []).map((option) => (
                                  <SelectItem key={option.source} value={option.source}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>

                            <div className="grid gap-3 lg:grid-cols-2">
                              {(selectedProviderDetails.runtime_options ?? []).map((option) => (
                                <div
                                  key={option.source}
                                  className={cn(
                                    "rounded-2xl border p-4 transition-all",
                                    option.source === runtimeSource ? "border-primary/40 bg-primary/5" : "border-border/40 bg-muted/10",
                                  )}
                                >
                                  <div className="flex items-center justify-between gap-3">
                                    <div className="space-y-1">
                                      <p className="text-sm font-semibold">{option.label}</p>
                                      <p className="text-[10px] uppercase tracking-widest text-muted-foreground">{option.status}</p>
                                    </div>
                                    <Badge variant="outline" className={cn("text-[10px] uppercase", option.available ? "text-emerald-600" : "text-amber-600")}>
                                      {option.available ? "Available" : "Setup Required"}
                                    </Badge>
                                  </div>
                                  <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{option.message}</p>
                                  <div className="mt-3 rounded-lg border border-border/40 bg-background/60 px-3 py-2 font-mono text-[11px] text-muted-foreground">
                                    {option.base_url}
                                  </div>
                                  {option.setup_command && (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="mt-3 h-8 text-[10px] uppercase tracking-widest"
                                      onClick={async () => {
                                        await navigator.clipboard.writeText(option.setup_command || '');
                                        toast({ title: 'Setup command copied', description: option.setup_command || '' });
                                      }}
                                    >
                                      Copy Setup Command
                                    </Button>
                                  )}
                                </div>
                              ))}
                            </div>

                            <div className="space-y-3">
                              <Label htmlFor="base-url" className="flex items-center gap-2 font-semibold">
                                <Server className="h-4 w-4 text-primary" /> Derived API Endpoint
                              </Label>
                              <Input id="base-url" value={baseUrl} readOnly className="h-11 bg-muted/20 font-mono" />
                            </div>
                          </div>
                        ) : selectedProviderDetails.supports_base_url_override && (
                          <div className="space-y-3 md:self-start">
                            <Label htmlFor="base-url" className="flex items-center gap-2 font-semibold">
                              <Server className="h-4 w-4 text-primary" /> API Endpoint
                            </Label>
                            <Input id="base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={selectedProviderDetails.default_base_url || "https://..."} className="h-11 bg-muted/20" />
                          </div>
                        )}
                        
                        <div className="space-y-3 md:self-start">
                          <div className="flex items-center justify-between">
                            <Label htmlFor="model-picker" className="font-semibold">Model Identification</Label>
                            {selectedProviderDetails.supports_model_discovery && (
                              <Button
                                variant="outline"
                                size="icon"
                                onClick={() => loadProviderModels(selectedProvider, baseUrl, fallbackProviderModels)}
                                disabled={isLoadingModels}
                                className="h-7 w-7"
                                title="Refresh model discovery"
                              >
                                {isLoadingModels ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                              </Button>
                            )}
                          </div>
                          {availableModels.length > 0 ? (
                            <Select value={selectedModel} onValueChange={setSelectedModel}>
                              <SelectTrigger id="model-picker" className="h-11 bg-muted/20">
                                <SelectValue placeholder="Discovering models..." />
                              </SelectTrigger>
                              <SelectContent>
                                {availableModels.map(m => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}
                              </SelectContent>
                            </Select>
                          ) : (
                            <Input id="model-picker" value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} placeholder="Type model id (e.g. gpt-4o)" className="h-11 bg-muted/20 font-mono" />
                          )}
                        </div>
                      </div>

                      {/* API Key Section */}
                      {selectedProviderDetails.requires_api_key && (
                        <div className="rounded-2xl border border-border/50 bg-muted/5 p-6 space-y-4 md:col-span-2 mt-2 border-t pt-6">
                          <div className="space-y-1">
                            <Label htmlFor="api-key" className="flex items-center gap-2 font-semibold">
                              <KeyRound className="h-4 w-4 text-primary" /> Credentials
                            </Label>
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-bold">Encrypted Backend Storage</p>
                          </div>

                          {selectedProviderDetails.api_key_configured && (
                            <div className="flex justify-end">
                              <Button variant="outline" size="sm" onClick={handleClearApiKey} disabled={isClearingKey} className="h-7 text-[10px] font-bold border-destructive/40 bg-destructive/5 text-destructive hover:bg-destructive/10">
                                Clear Secret
                              </Button>
                            </div>
                          )}

                          <div className="relative">
                            <Input
                              id="api-key"
                              type={isEditingApiKey ? "password" : "text"}
                              value={isEditingApiKey ? apiKey : (selectedProviderDetails.api_key_masked || '')}
                              readOnly={!isEditingApiKey && selectedProviderDetails.api_key_configured}
                              onFocus={() => {
                                setIsEditingApiKey(true);
                                setApiKey('');
                              }}
                              onChange={(e) => setApiKey(e.target.value)}
                              placeholder={`Enter ${selectedProviderLabel || selectedProviderDetails.display_name} API Secret...`}
                              className="h-12 border-border/60 bg-background/50 pr-10 font-mono text-sm leading-relaxed tracking-widest transition-all focus:border-primary/40 focus:ring-primary/10"
                            />
                            <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
                              {apiKeyValidationState === 'validating' && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
                              {apiKeyValidationState === 'valid' && <CheckCircle2 className="h-4 w-4 text-emerald-500 shadow-sm" />}
                              {apiKeyValidationState === 'invalid' && <XCircle className="h-4 w-4 text-destructive" />}
                            </div>
                          </div>

                          {apiKeyValidationMessage && (
                            <div className={cn("flex items-center gap-2 text-xs font-medium px-2 py-1.5 rounded-lg border",
                              apiKeyValidationState === 'valid' ? "bg-emerald-50/10 border-emerald-500/20 text-emerald-600" : "bg-destructive/5 border-destructive/20 text-destructive")}>
                              <Info className="h-3 w-3 shrink-0" /> {apiKeyValidationMessage}
                            </div>
                          )}
                        </div>
                      )}
                      {normalizedSettings?.systemFallbackProvider && (
                        <div className="rounded-2xl border border-dashed border-border/50 bg-muted/5 p-4 text-xs text-muted-foreground md:col-span-2">
                          Automatic fallback runtime: <span className="font-semibold text-foreground">{normalizedSettings.systemFallbackProvider.runtime_display_name}</span>
                        </div>
                      )}

                      {selectedProviderDetails.selectable === false && (
                        <Alert className="border-amber-500/30 bg-amber-500/10 md:col-span-2">
                          <InfoIcon className="h-4 w-4 !text-amber-600" aria-hidden="true" />
                          <AlertDescription className="text-xs">
                            This provider is visible for status but is not currently selectable. Backend provider registry controls availability.
                          </AlertDescription>
                        </Alert>
                      )}
                    </div>

                  <div className="flex justify-end pt-4">
                    <Button onClick={handleSave} disabled={isSaving} className="h-11 w-full sm:w-auto px-8 font-bold shadow-lg shadow-primary/20 transition-all hover:scale-[1.02] active:scale-95">
                      {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-5 w-5" />}
                      Finalize Intelligence Settings
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Sidebar Context Card */}
        {!isMobile && selectedProviderDetails && (
          <div className="xl:col-span-4 space-y-6 animate-in fade-in slide-in-from-right-8 duration-700">
            <Card className="border-border/40 shadow-sm sticky top-6">
              <CardHeader className="bg-muted/10">
                <div className="flex items-center gap-2">
                  <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                    <ShieldCheck className="h-4 w-4 text-primary" />
                  </div>
                  <div>
                    <CardTitle className="text-sm font-bold uppercase tracking-widest">{selectedProviderLabel || selectedProviderDetails.display_name}</CardTitle>
                    <p className="text-[10px] text-muted-foreground uppercase font-bold tracking-tight">Active Node Status</p>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-4 space-y-6">
                <div className="space-y-4">
                  <div className="rounded-xl border border-border/60 bg-muted/5 px-4 py-3">
                    <p className="text-xs leading-relaxed text-muted-foreground/90 font-medium italic">&quot;{selectedProviderDetails.description}&quot;</p>
                  </div>
                  
                  <div className="grid gap-2">
                    <div className="flex items-center justify-between text-xs font-semibold">
                      <span className="text-muted-foreground">Type</span>
                      <span className="uppercase tracking-widest text-primary/80">
                        {PROVIDER_TYPE_LABELS[selectedProviderDetails.provider_type?.toLowerCase() || ''] || selectedProviderDetails.provider_type}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs font-semibold">
                      <span className="text-muted-foreground">Auth</span>
                      <span className={cn("uppercase tracking-widest", selectedProviderDetails.requires_api_key ? "text-amber-600" : "text-emerald-600")}>
                        {selectedProviderDetails.requires_api_key ? "Restricted" : "Open"}
                      </span>
                    </div>
                    {selectedProviderDetails.selected_model && (
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <span className="text-muted-foreground">Active Model</span>
                        <span className="max-w-[120px] truncate font-mono text-primary/70">{selectedProviderDetails.selected_model}</span>
                      </div>
                    )}
                    {usesRuntimeOptions && selectedRuntimeOption && (
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <span className="text-muted-foreground">Runtime Source</span>
                        <span className="uppercase tracking-widest text-primary/80">{selectedRuntimeOption.label}</span>
                      </div>
                    )}
                    {normalizedSettings?.systemFallbackProvider && (
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <span className="text-muted-foreground">Automatic Fallback</span>
                        <span className="uppercase tracking-widest text-primary/80">{normalizedSettings.systemFallbackProvider.runtime_display_name}</span>
                      </div>
                    )}
                    {selectedProviderDetails.runtime_engine && (
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <span className="text-muted-foreground">Runtime Engine</span>
                        <span className="uppercase tracking-widest text-primary/80">{selectedProviderDetails.runtime_engine}</span>
                      </div>
                    )}
                    {selectedProviderDetails.execution_family && (
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <span className="text-muted-foreground">Execution</span>
                        <span className="tracking-widest text-primary/80">{formatExecutionFamilyLabel(selectedProviderDetails.execution_family)}</span>
                      </div>
                    )}
                    {selectedProviderDetails.adapter_class && (
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <span className="text-muted-foreground">Adapter</span>
                        <span className="max-w-[120px] truncate font-mono text-primary/70">{selectedProviderDetails.adapter_class}</span>
                      </div>
                    )}
                    {connectionTarget && (
                      <div className="flex items-center justify-between text-xs font-semibold">
                        <span className="text-muted-foreground">Connection Target</span>
                        <span className="max-w-[120px] truncate font-mono text-[10px] text-primary/70">{connectionTarget}</span>
                      </div>
                    )}
                    {selectedProviderDetails.execution_notes && (
                      <div className="flex flex-col gap-1 mt-2 p-2 rounded bg-muted/40 border border-border/30">
                        <span className="text-[10px] font-bold uppercase text-muted-foreground">Execution Notes</span>
                        <span className="text-[10px] text-muted-foreground leading-tight">{selectedProviderDetails.execution_notes}</span>
                      </div>
                    )}
                    {selectedProviderDetails.degraded_reason && (
                      <div className="flex flex-col gap-1 mt-2 p-2 rounded bg-destructive/10 border border-destructive/20">
                        <span className="text-[10px] font-bold uppercase text-destructive">Degradation Reason</span>
                        <span className="text-[10px] text-destructive leading-tight italic">{selectedProviderDetails.degraded_reason}</span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="space-y-3">
                  <h4 className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/80">Capabilities</h4>
                  <div className="flex flex-wrap gap-2">
                    {selectedProviderDetails.supports_model_discovery && <Badge variant="outline" className="h-6 text-[9px] font-bold bg-primary/5 uppercase">Discovery</Badge>}
                    {selectedProviderDetails.supports_model_pull && <Badge variant="outline" className="h-6 text-[9px] font-bold bg-emerald-50/10 uppercase">Local Pull</Badge>}
                    {selectedProviderDetails.supports_manual_model_entry && <Badge variant="outline" className="h-6 text-[9px] font-bold bg-blue-50/10 uppercase">Manual Node</Badge>}
                  </div>
                </div>

                {selectedProviderDetails.docs_url && (
                  <Button variant="secondary" className="w-full text-xs font-bold gap-2" asChild>
                    <a href={selectedProviderDetails.docs_url} target="_blank" rel="noreferrer">
                      Integration Protocol <ExternalLink className="h-3 w-3" />
                    </a>
                  </Button>
                )}
              </CardContent>
            </Card>

            <Alert className="bg-primary/5 border-primary/20">
              <InfoIcon className="h-4 w-4 !text-primary" />
              <AlertDescription className="text-[10px] font-semibold leading-relaxed text-primary/80">
                Karen intelligently routes prompts based on your selection. Cloud providers offer greater reasoning capabilities, while Local ensures 100% data sovereignity.
              </AlertDescription>
            </Alert>
          </div>
        )}
      </div>
    </div>
  );
}
