import { describe, expect, it } from 'vitest';

import {
  normalizeDiscoveredProviderModels,
  normalizeModelSettingsResponse,
  normalizeRuntimeProviderCatalogResponse,
  reconcileDiscoveredModelSelection,
  canSaveProviderModelSelection,
  getProviderModelDiscoveryNotice,
} from '@/lib/model-runtime-inventory';

describe('managed provider model discovery', () => {
  it('shows every installed Ollama model, but never claims a saved default is installed', () => {
    const models = normalizeDiscoveredProviderModels('ollama', [
      { id: 'deepseek-r1:1.5b', name: 'DeepSeek R1', is_installed: true },
      { id: 'qwen2.5:7b', name: 'Qwen 2.5', is_installed: true },
      { id: 'not-present:latest', name: 'Configured default', is_installed: false },
    ]);
    expect(models.map((entry) => entry.id)).toEqual(['deepseek-r1:1.5b', 'qwen2.5:7b']);
    expect(reconcileDiscoveredModelSelection('qwen2.5:7b', models)).toBe('qwen2.5:7b');
    expect(reconcileDiscoveredModelSelection('not-present:latest', models)).toBe('deepseek-r1:1.5b');
  });

  it('does not require Ollama installed flags from cloud provider catalogs', () => {
    const models = normalizeDiscoveredProviderModels('gemini', [
      { id: 'gemini-2.5-flash', name: 'Gemini Flash' },
    ]);
    expect(models).toHaveLength(1);
  });

  it('blocks saving a stale model while inventory is loading or absent', () => {
    const inventory = [
      { id: 'qwen2.5:7b', name: 'Qwen 2.5', is_installed: true },
    ];
    const managed = { isLoading: false, manualEntryAllowed: false };
    expect(canSaveProviderModelSelection('qwen2.5:7b', inventory, managed)).toBe(true);
    expect(canSaveProviderModelSelection('saved-but-removed', inventory, managed)).toBe(false);
    expect(canSaveProviderModelSelection('qwen2.5:7b', inventory, { ...managed, isLoading: true })).toBe(false);
    expect(canSaveProviderModelSelection('qwen2.5:7b', [], managed)).toBe(false);
    expect(canSaveProviderModelSelection('custom-model', [], { ...managed, manualEntryAllowed: true })).toBe(true);
    expect(canSaveProviderModelSelection('', inventory, { ...managed, manualEntryAllowed: true })).toBe(false);
  });

  it('does not fabricate a selection when the selected runtime has no models', () => {
    expect(normalizeDiscoveredProviderModels('ollama', [
      { id: 'saved-only', name: 'Saved only' },
    ])).toEqual([]);
    expect(reconcileDiscoveredModelSelection('saved-only', [])).toBe('');
  });
});


describe('saved model identifiers are not runtime inventory', () => {
  it('does not offer a previously selected Ollama model before live discovery', () => {
    const response = normalizeModelSettingsResponse({
      selected_provider: 'ollama',
      selected_model: 'not-installed:latest',
      providers: [{
        id: 'ollama',
        display_name: 'Ollama',
        provider_type: 'local',
        selected_model: 'not-installed:latest',
        models: [],
      }],
    });
    expect(response.providers[0].models).toEqual([]);
    expect(response.selected_model).toBe('');
  });

  it('does not manufacture models for managed hyphenated cloud providers', () => {
    const response = normalizeModelSettingsResponse({
      selected_provider: 'gmi-cloud',
      selected_model: 'old-model',
      providers: [{
        id: 'gmi-cloud',
        display_name: 'GMI Cloud',
        provider_type: 'external',
        selected_model: 'old-model',
        models: [],
      }],
    });
    expect(response.providers[0].models).toEqual([]);
    expect(response.selected_model).toBe('');
  });

  it('keeps manual model entry only for custom providers', () => {
    const response = normalizeModelSettingsResponse({
      selected_provider: 'custom',
      selected_model: 'tenant-model',
      providers: [{
        id: 'custom',
        display_name: 'Custom',
        provider_type: 'custom',
        selected_model: 'tenant-model',
        models: [],
      }],
    });
    expect(response.providers[0].models.map((model) => model.id)).toEqual(['tenant-model']);
    expect(response.selected_model).toBe('tenant-model');
  });

  it('does not invent catalog inventory for managed providers', () => {
    const response = normalizeRuntimeProviderCatalogResponse({
      default_provider: 'gmi-cloud',
      default_model: 'stale-default',
      providers: [{
        id: 'gmi-cloud',
        label: 'GMI Cloud',
        category: 'external',
        default_model: 'stale-default',
        models: [],
      }],
    });
    expect(response.providers[0].models).toEqual([]);
  });
});


describe('provider inventory provenance', () => {
  it('labels catalog-only results without asserting real endpoint availability', () => {
    expect(getProviderModelDiscoveryNotice({
      discovery_status: 'catalog_only',
      inventory_source: 'configured_catalog',
    })).toContain('not verified');
  });

  it('labels mixed results but not fully live-verified inventories', () => {
    expect(getProviderModelDiscoveryNotice({
      discovery_status: 'ready',
      inventory_source: 'mixed',
    })).toContain('not verified');
    expect(getProviderModelDiscoveryNotice({
      discovery_status: 'ready',
      inventory_source: 'provider_live',
    })).toBe('');
    expect(getProviderModelDiscoveryNotice({
      discovery_status: 'ready',
      inventory_source: 'ollama_native',
    })).toBe('');
  });

  it('never treats a failed live request as permission to save saved catalog defaults', () => {
    expect(canSaveProviderModelSelection(
      'stale-catalog-model', [],
      { isLoading: false, manualEntryAllowed: false },
    )).toBe(false);
    expect(canSaveProviderModelSelection(
      'custom-manual-model', [],
      { isLoading: false, manualEntryAllowed: true },
    )).toBe(true);
  });
});
