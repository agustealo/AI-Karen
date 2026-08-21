import { useCallback } from 'react';
import { apiClient } from '@/lib/api';
import { formatModelSwitchError } from '@/lib/model-switch-errors';
import { normalizeModelSettingsResponse, type NormalizedRuntimeInventory, type RuntimeSettingsResponse } from '@/lib/model-runtime-inventory';
import type {
  ModelDetails,
  ProviderDetails,
} from './types';

interface ToastOptions {
  title: string;
  description?: string;
  variant?: 'default' | 'destructive';
}

type ToastFn = (options: ToastOptions) => void;

type SetModelSettings = React.Dispatch<
  React.SetStateAction<NormalizedRuntimeInventory | null>
>;

type SetStringState = React.Dispatch<React.SetStateAction<string>>;

type SetBooleanState = React.Dispatch<React.SetStateAction<boolean>>;

const MODEL_SETTINGS_ENDPOINT = '/api/settings/model';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const isSelectableProvider = (provider: ProviderDetails): boolean => {
  const providerType = cleanString(provider.provider_type).toLowerCase();
  const isBuiltinProvider =
    providerType === 'builtin' ||
    provider.id === 'builtin_transformers' ||
    provider.id === 'builtin_vllm';

  if (isBuiltinProvider) {
    return true;
  }

  return (
    provider.selectable !== false &&
    provider.enabled !== false &&
    provider.user_selectable !== false &&
    provider.policy_allowed !== false &&
    provider.is_configured !== false &&
    !provider.policy_rejection_reason
  );
};

const getProviderDisplayName = (provider: ProviderDetails | null | undefined): string => {
  return (
    cleanString(provider?.display_name) ||
    cleanString(provider?.id) ||
    'selected provider'
  );
};

const getModelDisplayName = (model: ModelDetails | null | undefined): string => {
  return cleanString(model?.name) || cleanString(model?.id);
};

const getAllowedProviders = (
  modelSettings: NormalizedRuntimeInventory | null,
): ProviderDetails[] => {
  return (modelSettings?.providers ?? [])
    .filter(isSelectableProvider)
    .filter((provider) => cleanString(provider.id));
};

const resolveSelectedProviderId = (
  providers: ProviderDetails[],
  preferredProviderId?: string | null,
): string => {
  const preferred = cleanString(preferredProviderId);

  return (
    providers.find((provider) => provider.id === preferred)?.id ||
    providers[0]?.id ||
    ''
  );
};

const resolveSelectedModelId = (
  providers: ProviderDetails[],
  providerId: string,
  preferredModelId?: string | null,
): string => {
  const provider = providers.find((item) => item.id === providerId);

  if (!provider) {
    return cleanString(preferredModelId);
  }

  const preferred = cleanString(preferredModelId);
  const providerModelIds = new Set(provider.models.map((model) => model.id));

  if (preferred && providerModelIds.has(preferred)) {
    return preferred;
  }

  if (cleanString(provider.selected_model)) {
    return cleanString(provider.selected_model);
  }

  if (cleanString(provider.default_model)) {
    return cleanString(provider.default_model);
  }

  return provider.models[0]?.id || preferred || '';
};

const findProvider = (
  providers: ProviderDetails[],
  providerId: string,
): ProviderDetails | null => {
  return providers.find((provider) => provider.id === providerId) ?? null;
};

const findModel = (
  provider: ProviderDetails | null,
  modelId: string,
): ModelDetails | null => {
  if (!provider) {
    return null;
  }

  return provider.models.find((model) => model.id === modelId) ?? null;
};

export function useModelSettings() {
  const getSelectableProviders = useCallback(
    (modelSettings: NormalizedRuntimeInventory | null): ProviderDetails[] => {
      return getAllowedProviders(modelSettings);
    },
    [],
  );

  const applyModelSelection = useCallback(
    async (
      providerId: string,
      modelId: string,
      modelSettings: NormalizedRuntimeInventory | null,
      setModelSettings: SetModelSettings,
      setSelectedProvider: SetStringState,
      setSelectedModel: SetStringState,
      setIsUpdatingModelSelection: SetBooleanState,
      toast: ToastFn,
    ) => {
      const requestedProviderId = cleanString(providerId);
      const requestedModelId = cleanString(modelId);

      if (!modelSettings) {
        toast({
          title: 'Model settings unavailable',
          description:
            'Karen could not apply the model selection because settings have not loaded yet.',
          variant: 'destructive',
        });
        return;
      }

      const selectableProviders = getAllowedProviders(modelSettings);
      const provider = findProvider(selectableProviders, requestedProviderId);

      if (!provider) {
        toast({
          title: 'Provider unavailable',
          description:
            requestedProviderId
              ? `Karen could not find a selectable provider named "${requestedProviderId}".`
              : 'Karen could not find the selected provider.',
          variant: 'destructive',
        });
        return;
      }

      if (!requestedModelId) {
        toast({
          title: 'Model required',
          description: `Select a model for ${getProviderDisplayName(provider)} before applying settings.`,
          variant: 'destructive',
        });
        return;
      }

      const selectedModel = findModel(provider, requestedModelId);

      setIsUpdatingModelSelection(true);

      try {
        const response = await apiClient.put<RuntimeSettingsResponse>(
          MODEL_SETTINGS_ENDPOINT,
          {
            provider: requestedProviderId,
            model: requestedModelId,
          },
        );

        const normalizedSettings = normalizeModelSettingsResponse(response);
        const allowedProviders = getAllowedProviders(normalizedSettings);

        const resolvedProviderId = resolveSelectedProviderId(
          allowedProviders,
          normalizedSettings.selected_provider || requestedProviderId,
        );

        const resolvedModelId = resolveSelectedModelId(
          allowedProviders,
          resolvedProviderId,
          normalizedSettings.selected_model || requestedModelId,
        );

        setModelSettings(normalizedSettings);
        setSelectedProvider(resolvedProviderId);
        setSelectedModel(resolvedModelId);

        toast({
          title: 'Settings applied',
          description: `Karen is now using ${
            getModelDisplayName(selectedModel) || requestedModelId
          } via ${getProviderDisplayName(provider)}.`,
        });
      } catch (error) {
        toast({
          title: 'Model switch failed',
          description: formatModelSwitchError(
            error,
            getProviderDisplayName(provider),
          ),
          variant: 'destructive',
        });
      } finally {
        setIsUpdatingModelSelection(false);
      }
    },
    [],
  );

  return {
    applyModelSelection,
    getSelectableProviders,
  };
}
