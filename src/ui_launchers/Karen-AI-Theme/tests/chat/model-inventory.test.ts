import { describe, expect, it } from 'vitest';

import {
  normalizeDiscoveredProviderModels,
  reconcileDiscoveredModelSelection,
  canSaveProviderModelSelection,
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
