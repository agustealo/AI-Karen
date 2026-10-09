import { vi, describe, it, expect } from 'vitest';

// Mock the require object before anything else is imported
vi.hoisted(() => {
  const moduleGlobal = globalThis as typeof globalThis & { require?: NodeRequire & { context?: unknown } };
  if (typeof moduleGlobal.require === 'undefined') {
    moduleGlobal.require = Object.assign(
      () => undefined,
      { resolve: require.resolve, cache: require.cache, extensions: require.extensions, main: require.main, context: undefined },
    ) as NodeRequire & { context?: unknown };
  }
  moduleGlobal.require.context = vi.fn(() => {
    const context = (key: string) => ({ default: () => null });
    context.keys = () => [] as string[];
    context.resolve = (key: string) => key;
    context.id = 'mock';
    return context;
  });
});

// Now import the module that calls require.context at top level
import { resolvePluginComponent, normalizePluginId, PLUGIN_IMPORT_MAP, type LoaderPluginEntry } from '../../src/plugin_host/loader';
import React from 'react';
import '@testing-library/jest-dom';

vi.mock('@/lib/api', () => ({
  default: { get: vi.fn() }
}));

vi.mock('@/lib/useAuth', () => ({
  useAuth: () => ({ user: { id: 'test-user', roles: ['user', 'admin'] } })
}));

vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react')>();
  return {
    ...actual,
    lazy: vi.fn((_importer: () => Promise<{ default: React.ComponentType }>) => {
      const LazyComp = () => actual.createElement('div', null, 'Lazy Component');
      (LazyComp as typeof LazyComp & { $typeof?: symbol }).$typeof = Symbol.for('react.lazy');
      return LazyComp;
    }),
  };
});

const mockCatalog: LoaderPluginEntry[] = [
  { name: 'weather-query', status: 'active', capabilities: { provides_ui: true } },
  { name: 'data-connector', status: 'active', capabilities: { provides_ui: true } },
];

describe('Plugin Loader', () => {
  it('should normalize plugin ids', () => {
    expect(normalizePluginId('Weather_Query')).toBe('weather-query');
  });

  it('should resolve components', () => {
    (PLUGIN_IMPORT_MAP as Record<string, () => Promise<{ default: () => null }>>)['weather-query'] = vi.fn().mockResolvedValue({ default: () => null });
    const component = resolvePluginComponent('weather-query', mockCatalog);
    expect(component).toBeTruthy();
  });
});
