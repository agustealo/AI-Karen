import { apiClient } from '@/lib/api';
import { getRuntimeDisplayName, getRuntimeGroupLabel, isBuiltInRuntimeProvider } from '@/lib/chat-response';

export interface RuntimeProviderModel {
  id: string;
  name: string;
  family?: string;
  source?: string;
  size_bytes?: number | null;
  capabilities?: string[];
  preferred_runtime?: string | null;
  compatible_runtimes?: string[];
  default?: boolean;
}

export interface RuntimeProviderDetails {
  id: string;
  display_name: string;
  description?: string;
  provider_type?: string;
  type?: string;
  selectable?: boolean;
  requires_api_key?: boolean;
  api_key_configured?: boolean;
  api_key_status?: string;
  api_key_env_var?: string | null;
  is_configured?: boolean;
  healthy?: boolean;
  user_selectable?: boolean;
  enabled?: boolean;
  policy_allowed?: boolean;
  policy_rejection_reason?: string | null;
  api_key_masked?: string | null;
  api_key_header?: string;
  api_key_prefix?: string;
  custom_headers?: Record<string, string>;
  docs_url?: string | null;
  base_url?: string | null;
  default_base_url?: string | null;
  default_model?: string | null;
  selected_model?: string | null;
  supports_base_url_override?: boolean;
  supports_model_discovery?: boolean;
  supports_model_pull?: boolean;
  supports_custom_auth?: boolean;
  supports_manual_model_entry?: boolean;
  runtime_source?: 'host' | 'container' | null;
  runtime_engine?: string;
  supports_streaming?: boolean;
  supports_tools?: boolean;
  degraded_reason?: string | null;
  required_config_fields?: string[];
  safe_diagnostic_metadata?: Record<string, unknown>;
  transport?: string;
  runtime_display_name?: string;
  runtime_group_label?: string;
  runtime_options?: Array<{
    source: 'host' | 'container';
    label: string;
    base_url: string;
    available: boolean;
    active?: boolean;
    status: string;
    message: string;
    setup_required?: boolean;
    setup_command?: string | null;
    install_supported?: boolean;
  }>;
  models: RuntimeProviderModel[];
}

export interface RuntimeSettingsResponse {
  selected_provider: string;
  selected_model: string;
  providers: RuntimeProviderDetails[];
  default_provider?: string;
  default_model?: string;
  active_provider?: string;
  active_model?: string;
  timeout_seconds?: number;
  auto_download?: boolean;
  fallback_hierarchy?: string[];
}

export interface RuntimeProviderCatalogModel {
  id: string;
  label: string;
  available?: boolean;
  default?: boolean;
  capabilities?: string[];
}

export interface RuntimeProviderCatalogProvider {
  id: string;
  label: string;
  category?: string;
  enabled?: boolean;
  configured?: boolean;
  healthy?: boolean;
  runtime_engine?: string;
  transport?: string;
  compatibility_profile?: string | null;
  api_key_env_var?: string | null;
  api_key_header?: string | null;
  api_key_prefix?: string | null;
  default_base_url?: string | null;
  base_url?: string | null;
  docs_url?: string | null;
  required_config_fields?: string[];
  safe_diagnostic_metadata?: Record<string, unknown>;
  default_model?: string | null;
  selected_model?: string | null;
  models?: RuntimeProviderCatalogModel[];
  degradation_reason?: string | null;
  allowed_for_current_user?: boolean;
  requires_api_key?: boolean;
  requires_base_url?: boolean;
}

export interface RuntimeProviderCatalogResponse {
  providers: RuntimeProviderCatalogProvider[];
  default_provider?: string;
  default_model?: string;
  fallback_order?: string[];
  catalog_version?: string;
}

export interface NormalizedRuntimeProvider extends RuntimeProviderDetails {
  runtime_display_name?: string;
  runtime_group_label?: string;
  models: RuntimeProviderModel[];
  compatibility_profile?: string | null;
  degradation_reason?: string | null;
  requires_base_url?: boolean;
  execution_family?: string | null;
  adapter_class?: string | null;
  adapter_module?: string | null;
  execution_notes?: string | null;
}

export interface NormalizedRuntimeInventory {
  selected_provider: string;
  selected_model: string;
  providers: NormalizedRuntimeProvider[];
  selectableProviders: NormalizedRuntimeProvider[];
  builtInProviders: NormalizedRuntimeProvider[];
  localProviders: NormalizedRuntimeProvider[];
  thirdPartyProviders: NormalizedRuntimeProvider[];
  customProviders: NormalizedRuntimeProvider[];
  systemFallbackProvider: NormalizedRuntimeProvider | null;
  timeout_seconds?: number;
  auto_download?: boolean;
  fallback_hierarchy?: string[];
}

export type RuntimeProviderBucket = 'builtIn' | 'local' | 'thirdParty' | 'custom';

export const isVllmCompatibleModel = (model: RuntimeProviderModel | Record<string, unknown>): boolean => {
  const preferredRuntime = String(model.preferred_runtime || '').toLowerCase();

  if (preferredRuntime === 'vllm' || preferredRuntime === 'builtin_vllm') {
    return true;
  }

  const compatibleRuntimes = Array.isArray(model.compatible_runtimes)
    ? model.compatible_runtimes.map((runtime) => String(runtime).toLowerCase())
    : [];

  return (
    compatibleRuntimes.includes('vllm') ||
    compatibleRuntimes.includes('builtin_vllm')
  );
};

export const sortProviderModels = <T extends RuntimeProviderModel>(
  models: T[],
): T[] => {
  return [...models].sort((left, right) => {
    const leftVllm = isVllmCompatibleModel(left) ? 0 : 1;
    const rightVllm = isVllmCompatibleModel(right) ? 0 : 1;

    if (leftVllm !== rightVllm) {
      return leftVllm - rightVllm;
    }

    const leftRuntime = String(
      (left as { preferred_runtime?: unknown; model_format?: unknown }).preferred_runtime ||
      (left as { preferred_runtime?: unknown; model_format?: unknown }).model_format ||
      '',
    ).toLowerCase();
    const rightRuntime = String(
      (right as { preferred_runtime?: unknown; model_format?: unknown }).preferred_runtime ||
      (right as { preferred_runtime?: unknown; model_format?: unknown }).model_format ||
      '',
    ).toLowerCase();

    if (leftRuntime !== rightRuntime) {
      return leftRuntime.localeCompare(rightRuntime);
    }

    const leftName = String(
      (left as { display_name?: unknown }).display_name || left.name || left.id || '',
    ).toLowerCase();
    const rightName = String(
      (right as { display_name?: unknown }).display_name || right.name || right.id || '',
    ).toLowerCase();

    return leftName.localeCompare(rightName);
  });
};

export const getRuntimeProviderBucket = (
  provider: RuntimeProviderDetails,
): RuntimeProviderBucket => {
  const providerType = String(provider.provider_type || '').toLowerCase();

  if (isBuiltInRuntimeProvider(provider.id)) return 'builtIn';
  if (provider.id === 'custom' || providerType === 'custom' || provider.supports_custom_auth) return 'custom';
  if (providerType === 'local' || (provider.id === 'ollama' && providerType === 'hybrid')) return 'local';
  return 'thirdParty';
};

const sortRank = (provider: RuntimeProviderDetails): number => {
  switch (getRuntimeProviderBucket(provider)) {
    case 'builtIn':
      return 0;
    case 'local':
      return 1;
    case 'thirdParty':
      return 2;
    case 'custom':
      return 3;
  }
};

const normalizeModels = (
  provider: RuntimeProviderDetails,
  selectedProvider: string,
  selectedModel: string,
): RuntimeProviderModel[] => {
  const seen = new Set<string>();
  const models = (provider.models || []).filter((model) => {
    if (!model.id) return false;
    if (seen.has(model.id)) return false;
    seen.add(model.id);
    return true;
  });
  const fallbackModelId =
    provider.selected_model ||
    provider.default_model ||
    (selectedProvider === provider.id ? selectedModel : null) ||
    '';

  return models.length > 0
    ? models
      : fallbackModelId
        ? [{ id: fallbackModelId, name: fallbackModelId, source: 'saved' }]
        : [];
};

/**
 * Dynamically load models from the transformers directory
 * This scans the backend /api/local/transformers/models endpoint
 * which returns all downloaded models.
 */
export async function loadDynamicTransformersModels(): Promise<RuntimeProviderModel[]> {
  try {
    const response = await apiClient.get<{ models: string[] }>(
      '/api/local/transformers/models'
    );

    return response.models.map((modelName: string) => ({
      id: modelName,
      name: modelName,
      family: 'transformers',
      source: 'runtime',
    }));
  } catch (error) {
    console.error('Failed to load transformers models:', error);
    return [];
  }
}

/**
 * Determine if a provider should be selectable in UI.
 * Previously we blocked Transformers, but now we allow it as a valid local option.
 * We only show providers that are enabled AND configured (e.g. have API keys or local services detected).
 */
const isProviderSelectable = (provider: RuntimeProviderDetails): boolean => {
  return (
    provider.enabled !== false &&
    provider.user_selectable !== false &&
    provider.policy_allowed !== false &&
    provider.is_configured !== false
  );
};

export function normalizeModelSettingsResponse(response: RuntimeSettingsResponse): NormalizedRuntimeInventory {
  const providerMap = new Map<string, RuntimeProviderDetails>();
  (response.providers || []).forEach((provider) => {
    providerMap.set(provider.id, provider);
  });
  const providers = Array.from(providerMap.values())
    .sort((a, b) => sortRank(a) - sortRank(b) || getRuntimeDisplayName(a.id, a.display_name).localeCompare(getRuntimeDisplayName(b.id, b.display_name)))
    .map((provider) => {
      // Use standard model normalization for all providers.
      // The backend provides discovered models in the provider.models array.
      const normalizedModels = normalizeModels(provider, response.selected_provider, response.selected_model);
      const providerType = String((provider as { provider_type?: string; type?: string }).provider_type || provider.type || '').toLowerCase();
      const diagnostic = provider.safe_diagnostic_metadata || {};
      return {
        ...provider,
        provider_type: providerType || provider.provider_type,
        requires_api_key: provider.requires_api_key ?? provider.api_key_status === 'missing',
        api_key_configured: provider.api_key_configured ?? provider.api_key_status === 'configured',
        selectable: provider.user_selectable,
        runtime_display_name: getRuntimeDisplayName(provider.id, provider.display_name) || '',
        runtime_group_label: getRuntimeGroupLabel(provider.id) || 'Custom',
        runtime_engine: String(diagnostic['runtime_engine'] || provider.runtime_engine || provider.id.replace('builtin_', '')),
        execution_family: String(diagnostic['execution_family'] || ''),
        adapter_class: String(diagnostic['adapter_class'] || ''),
        adapter_module: String(diagnostic['adapter_module'] || ''),
        execution_notes: String(diagnostic['execution_notes'] || ''),
        models: normalizedModels,
      };
    });

  const selectableProviders = providers.filter((provider) => isProviderSelectable(provider));
  const builtInProviders = providers.filter((provider) => getRuntimeProviderBucket(provider) === 'builtIn');
  const localProviders = providers.filter((provider) => getRuntimeProviderBucket(provider) === 'local');
  const customProviders = providers.filter((provider) => getRuntimeProviderBucket(provider) === 'custom');
  const thirdPartyProviders = providers.filter((provider) => getRuntimeProviderBucket(provider) === 'thirdParty');

  const systemFallbackProvider: NormalizedRuntimeProvider | null = null;

  const selectedProvider =
    providers.find((provider) => provider.id === response.selected_provider)?.id ||
    providers[0]?.id ||
    '';
  const selectedModel =
    providers.find((provider) => provider.id === selectedProvider)?.selected_model ||
    providers.find((provider) => provider.id === selectedProvider)?.models[0]?.id ||
    response.selected_model ||
    '';

  return {
    selected_provider: selectedProvider,
    selected_model: selectedModel,
    providers,
    selectableProviders,
    builtInProviders,
    localProviders,
    thirdPartyProviders,
    customProviders,
    systemFallbackProvider,
    timeout_seconds: response.timeout_seconds,
    auto_download: response.auto_download,
    fallback_hierarchy: response.fallback_hierarchy,
  };
}

export function normalizeRuntimeProviderCatalogResponse(
  response: RuntimeProviderCatalogResponse,
): NormalizedRuntimeInventory {
  const providers = (response.providers || [])
    .map((provider) => {
      const normalizedModels = sortProviderModels(
        (provider.models || []).map((model) => ({
          id: model.id,
          name: model.label || model.id,
          family: provider.category || 'runtime',
          source: provider.runtime_engine || 'catalog',
          capabilities: model.capabilities || [],
          preferred_runtime: provider.runtime_engine || provider.category || undefined,
        })),
      );
      const fallbackModelId =
        provider.selected_model ||
        provider.default_model ||
        response.default_model ||
        '';
      const diagnostic = provider.safe_diagnostic_metadata || {};
      const resolvedModels: RuntimeProviderModel[] =
        normalizedModels.length > 0
          ? normalizedModels
          : fallbackModelId
            ? [{
                id: fallbackModelId,
                name: fallbackModelId,
                family: provider.category || 'runtime',
                source: provider.runtime_engine || 'catalog',
                capabilities: ['chat'],
                preferred_runtime: provider.runtime_engine || provider.category || undefined,
                default: true,
              }]
            : [];

      const normalizedProvider: NormalizedRuntimeProvider = {
        id: provider.id,
        display_name: provider.label || provider.id,
        description: provider.degradation_reason || undefined,
        provider_type: provider.category || 'external',
        selectable: provider.enabled !== false && provider.allowed_for_current_user !== false,
        requires_api_key: Boolean(provider.requires_api_key),
        api_key_env_var: provider.api_key_env_var || null,
        api_key_configured: provider.configured !== false,
        is_configured: provider.configured !== false,
        healthy: provider.healthy !== false,
        user_selectable: provider.allowed_for_current_user !== false,
        enabled: provider.enabled !== false,
        policy_allowed: provider.allowed_for_current_user !== false,
        policy_rejection_reason: provider.allowed_for_current_user === false ? 'not_allowed_for_current_user' : null,
        runtime_engine:
          String(diagnostic['runtime_engine'] || provider.runtime_engine || provider.id.replace('builtin_', '')),
        transport: provider.transport,
        compatibility_profile: provider.compatibility_profile || undefined,
        degradation_reason: provider.degradation_reason || null,
        requires_base_url: Boolean(provider.requires_base_url),
        execution_family: String(diagnostic['execution_family'] || ''),
        adapter_class: String(diagnostic['adapter_class'] || ''),
        adapter_module: String(diagnostic['adapter_module'] || ''),
        execution_notes: String(diagnostic['execution_notes'] || ''),
        api_key_header: provider.api_key_header || undefined,
        api_key_prefix: provider.api_key_prefix || undefined,
        default_base_url: provider.default_base_url || undefined,
        base_url: provider.base_url || undefined,
        docs_url: provider.docs_url || undefined,
        required_config_fields: provider.required_config_fields || [],
        safe_diagnostic_metadata: provider.safe_diagnostic_metadata || {},
        models: resolvedModels,
        default_model: provider.default_model || resolvedModels.find((model) => model.default)?.id || resolvedModels[0]?.id || response.default_model || null,
        selected_model: provider.selected_model || resolvedModels.find((model) => model.default)?.id || resolvedModels[0]?.id || response.default_model || null,
        runtime_display_name: getRuntimeDisplayName(provider.id, provider.label) || '',
        runtime_group_label: getRuntimeGroupLabel(provider.id) || 'Custom',
      };

      return normalizedProvider;
    })
    .sort((a, b) =>
      sortRank(a) - sortRank(b) ||
      getRuntimeDisplayName(a.id, a.display_name).localeCompare(getRuntimeDisplayName(b.id, b.display_name))
    );

  const selectableProviders = providers.filter((provider) => isProviderSelectable(provider));
  const builtInProviders = providers.filter((provider) => getRuntimeProviderBucket(provider) === 'builtIn');
  const localProviders = providers.filter((provider) => getRuntimeProviderBucket(provider) === 'local');
  const customProviders = providers.filter((provider) => getRuntimeProviderBucket(provider) === 'custom');
  const thirdPartyProviders = providers.filter((provider) => getRuntimeProviderBucket(provider) === 'thirdParty');

  const selectedProvider =
    providers.find((provider) => provider.id === response.default_provider)?.id ||
    selectableProviders[0]?.id ||
    providers[0]?.id ||
    '';
  const selectedModel =
    response.default_model ||
    providers.find((provider) => provider.id === selectedProvider)?.selected_model ||
    providers.find((provider) => provider.id === selectedProvider)?.models[0]?.id ||
    '';

  return {
    selected_provider: selectedProvider,
    selected_model: selectedModel,
    providers,
    selectableProviders,
    builtInProviders,
    localProviders,
    thirdPartyProviders,
    customProviders,
    systemFallbackProvider: providers.find((provider) => provider.id === "builtin_transformers") || null,
    timeout_seconds: undefined,
    auto_download: undefined,
    fallback_hierarchy: response.fallback_order,
  };
}
