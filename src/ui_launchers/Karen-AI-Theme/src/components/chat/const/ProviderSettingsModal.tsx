import { useEffect, useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Label } from '@/components/ui/label';
import { Bot, ChevronDown, Info, Loader2 } from 'lucide-react';
import { getRuntimeDisplayName } from '@/lib/chat-response';
import { getRuntimeProviderBucket } from '@/lib/model-runtime-inventory';
import type { ProviderDetails } from '../types';

export type { ProviderDetails };

type ProviderGroupKey = 'builtIn' | 'local' | 'thirdParty' | 'custom';

interface ProviderSettingsModalProps {
  providers: ProviderDetails[];
  selectableProviders: ProviderDetails[];
  selectedProvider: string;
  selectedModel: string;
  applyModelSelection: (providerId: string, modelId: string) => Promise<void>;
  isUpdatingModelSelection: boolean;
}

interface ProviderGroupConfig {
  key: ProviderGroupKey;
  label: string;
  providers: ProviderDetails[];
}

const PROVIDER_GROUP_LABELS: Record<ProviderGroupKey, string> = {
  builtIn: 'Built-in Runtime',
  local: 'Local Providers',
  thirdParty: 'Cloud Providers',
  custom: 'Custom Integrations',
};

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const getProviderLabel = (provider: ProviderDetails | null | undefined): string => {
  return getRuntimeDisplayName(
    cleanString(provider?.id),
    cleanString(provider?.display_name),
  );
};

const getFirstAvailableModelId = (
  provider: ProviderDetails | null | undefined,
): string => {
  if (!provider) {
    return '';
  }

  /*
   * The backend is the source of truth for selected/default model.
   * We only fall back to the first advertised model so the modal remains usable
   * when a provider has models but no saved selected_model yet.
   */
  return (
    cleanString(provider.selected_model) ||
    cleanString(provider.default_model) ||
    cleanString(provider.models?.[0]?.id)
  );
};

const getProviderById = (
  providers: ProviderDetails[],
  providerId: string,
): ProviderDetails | null => {
  return providers.find((provider) => provider.id === providerId) ?? null;
};

const getFallbackProviderId = (
  providers: ProviderDetails[],
  preferredProviderId: string,
): string => {
  const preferred = cleanString(preferredProviderId);

  if (preferred && providers.some((provider) => provider.id === preferred)) {
    return preferred;
  }

  return providers[0]?.id || '';
};

const getProviderGroups = (
  providers: ProviderDetails[],
): ProviderGroupConfig[] => {
  /*
   * Provider buckets come from the existing runtime inventory helper.
   * Do not hardcode provider IDs here. That would recreate the old UI problem
   * where display logic accidentally became provider-routing logic.
   */
  const grouped = providers.reduce<Record<ProviderGroupKey, ProviderDetails[]>>(
    (groups, provider) => {
      const bucket = getRuntimeProviderBucket(provider) as ProviderGroupKey;
      const safeBucket: ProviderGroupKey = bucket in groups ? bucket : 'custom';

      groups[safeBucket].push(provider);
      return groups;
    },
    {
      builtIn: [],
      local: [],
      thirdParty: [],
      custom: [],
    },
  );

  return (Object.keys(PROVIDER_GROUP_LABELS) as ProviderGroupKey[])
    .map((key) => ({
      key,
      label: PROVIDER_GROUP_LABELS[key],
      providers: grouped[key],
    }))
    .filter((group) => group.providers.length > 0);
};

export const ProviderSettingsModal = ({
  providers,
  selectableProviders,
  selectedProvider,
  selectedModel,
  applyModelSelection,
  isUpdatingModelSelection,
}: ProviderSettingsModalProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [localProvider, setLocalProvider] = useState(selectedProvider);
  const [localModel, setLocalModel] = useState(selectedModel);

  const providerGroups = useMemo(
    () => getProviderGroups(selectableProviders),
    [selectableProviders],
  );

  const activeCloudProviders = useMemo(
    () =>
      providers.filter((provider) => {
        const bucket = getRuntimeProviderBucket(provider);
        return (
          bucket === 'thirdParty' &&
          provider.enabled !== false &&
          provider.user_selectable !== false &&
          provider.policy_allowed !== false &&
          provider.is_configured !== false
        );
      }),
    [providers],
  );

  const activeProviderDetails = useMemo(() => {
    return getProviderById(providers, localProvider);
  }, [providers, localProvider]);

  const providerModels = useMemo(() => activeProviderDetails?.models ?? [], [activeProviderDetails]);
  const activeProviderLabel =
    getProviderLabel(activeProviderDetails) || 'Select Runtime';

  const currentProviderDetails = useMemo(() => {
    return getProviderById(providers, selectedProvider);
  }, [providers, selectedProvider]);
  
  const currentProviderLabel = getProviderLabel(currentProviderDetails) || 'Models';

  /*
   * The modal keeps local draft state so users can browse providers/models
   * without immediately changing the active runtime. We reset that draft state
   * only when the modal opens, preserving the saved backend selection.
   */
  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const resolvedProviderId = getFallbackProviderId(
      selectableProviders,
      selectedProvider,
    );
    const resolvedProvider = getProviderById(providers, resolvedProviderId);

    setLocalProvider(resolvedProviderId);
    setLocalModel(cleanString(selectedModel) || getFirstAvailableModelId(resolvedProvider));
  }, [isOpen, providers, selectableProviders, selectedProvider, selectedModel]);

  /*
   * When the user switches provider inside the modal, choose that provider's
   * saved/default model. This avoids carrying an incompatible model ID from
   * the previously selected provider into the Apply call.
   */
  useEffect(() => {
    if (!isOpen || !activeProviderDetails) {
      return;
    }

    const modelExistsOnProvider = providerModels.some(
      (model) => model.id === localModel,
    );

    if (!modelExistsOnProvider) {
      setLocalModel(getFirstAvailableModelId(activeProviderDetails));
    }
  }, [isOpen, activeProviderDetails, providerModels, localModel]);

  const handleProviderSelect = (providerId: string) => {
    const nextProvider = getProviderById(providers, providerId);

    setLocalProvider(providerId);
    setLocalModel(getFirstAvailableModelId(nextProvider));
  };

  const handleApply = async () => {
    if (!localProvider || !localModel || isUpdatingModelSelection) {
      return;
    }

    /*
     * Provider/model persistence remains owned by the existing caller.
     * This modal only collects the draft selection and invokes the supplied
     * applyModelSelection callback.
     */
    await applyModelSelection(localProvider, localModel);
    setIsOpen(false);
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="flex h-9 items-center gap-2 border border-input bg-background px-3 font-medium hover:bg-accent hover:text-accent-foreground shadow-sm transition-all"
          aria-label="Open model and provider settings"
        >
          <Bot className="h-4 w-4 text-primary/70" />
          <span className="max-w-[150px] truncate text-[10px] font-bold uppercase tracking-tight">
            {currentProviderLabel}
          </span>
          <span className="text-[9px] opacity-40">/</span>
          <span className="max-w-[100px] truncate text-[10px] opacity-60">
            {selectedModel === 'auto' ? 'AUTO' : selectedModel}
          </span>
          <ChevronDown className="h-3 w-3 opacity-30" />
        </Button>
      </DialogTrigger>

      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-[850px]">
        <DialogHeader className="sr-only">
          <DialogTitle>AI Provider Settings</DialogTitle>
          <DialogDescription>
            Configure AI providers, models, and connection settings for Karen.
          </DialogDescription>
        </DialogHeader>

        <div className="flex h-[600px]">
          {/* Provider sidebar: display-only grouping. Runtime truth comes from backend provider records. */}
          <div className="flex w-[180px] flex-col gap-1 overflow-y-auto border-r border-border bg-muted/30 p-3">
            <div className="mb-2 px-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Runtime Providers
            </div>

            {activeCloudProviders.length === 0 ? (
              <Alert className="mb-3 border-border/60 bg-background/80 px-2 py-2 text-muted-foreground">
                <Info className="h-4 w-4" />
                <AlertDescription className="text-[11px] leading-snug">
                  No active cloud providers are configured. Built-in runtimes are still available.
                </AlertDescription>
              </Alert>
            ) : null}

            {providerGroups.length === 0 ? (
              <div className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">
              No providers were returned by the backend.
            </div>
          ) : (
            <div className="space-y-2">
              {providerGroups.map((group) => (
                  <div key={group.key} className="space-y-1">
                    <div className="px-2 text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
                      {group.label}
                    </div>

                    {group.providers.map((provider) => {
                      const isActive = localProvider === provider.id;
                      const label = getProviderLabel(provider);
                      const isSelectable =
                        provider.selectable !== false &&
                        selectableProviders.some((item) => item.id === provider.id);
                      const isConfigured = provider.enabled !== false;

                      return (
                        <button
                          key={provider.id}
                          type="button"
                          onClick={() => handleProviderSelect(provider.id)}
                          disabled={!isSelectable}
                          className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                            isActive
                              ? 'bg-primary font-medium text-primary-foreground'
                              : isSelectable
                                ? 'text-muted-foreground hover:bg-muted hover:text-foreground'
                                : 'cursor-not-allowed text-muted-foreground/50'
                          }`}
                          aria-pressed={isActive}
                          title={label}
                        >
                          <Bot
                            className={`h-4 w-4 ${
                              isActive ? 'opacity-100' : 'opacity-60'
                            }`}
                          />
                          <span className="truncate">{label}</span>
                          {!isConfigured && (
                            <span className="ml-auto rounded-full border border-border/50 px-1.5 py-0.5 text-[8px] uppercase tracking-wider">
                              Setup
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex min-w-0 flex-1 flex-col">
            <DialogHeader className="p-6 pb-2">
              <DialogTitle className="flex items-center gap-2">
                {activeProviderLabel} Models
              </DialogTitle>
              <DialogDescription className="text-xs">
                Choose from the providers and models already configured in settings.
              </DialogDescription>
            </DialogHeader>

            <ScrollArea className="flex-1 p-6 pt-2">
              <div className="space-y-3">
                <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Available Models
                </Label>

                <div className="grid grid-cols-2 gap-2">
                  {providerModels.map((model) => {
                    const isActive = localModel === model.id;
                    const isAuto = model.id === 'auto';
                    const displayName = isAuto ? 'Automatic Selection' : (model.name || model.id);

                    return (
                      <button
                        key={model.id}
                        type="button"
                        onClick={() => setLocalModel(model.id)}
                        className={`rounded-lg border p-3 text-left transition-all ${
                          isActive
                            ? 'border-primary bg-primary/5 ring-1 ring-primary'
                            : 'border-border hover:border-muted-foreground/30 hover:bg-muted/50'
                        }`}
                        aria-pressed={isActive}
                        title={model.id}
                      >
                        <div className="truncate text-sm font-medium leading-tight">
                          {displayName}
                        </div>
                        {!isAuto && (
                          <div className="mt-1 truncate text-[10px] text-muted-foreground">
                            {model.id}
                          </div>
                        )}
                        {isAuto && (
                          <div className="mt-1 truncate text-[9px] italic text-muted-foreground opacity-70">
                            Let Karen choose the best model
                          </div>
                        )}
                      </button>
                    );
                  })}

                  {providerModels.length === 0 && (
                    <div className="col-span-2 rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground">
                      No configured models found for this provider. Use Application
                      Settings to configure one.
                    </div>
                  )}
                </div>
              </div>
            </ScrollArea>

            <div className="flex justify-end gap-3 border-t border-border bg-muted/10 p-6 pt-4">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setIsOpen(false)}
                className="h-9"
                disabled={isUpdatingModelSelection}
              >
                Cancel
              </Button>

              <Button
                type="button"
                onClick={() => void handleApply()}
                disabled={
                  isUpdatingModelSelection ||
                  !localProvider ||
                  !localModel ||
                  providerModels.length === 0
                }
                className="h-9 min-w-[120px]"
              >
                {isUpdatingModelSelection ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : null}
                Apply Changes
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
