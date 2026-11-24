import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { PluginHost } from '../../src/components/plugins/PluginHost';
import { mountStateRegistry } from '../../src/plugin_host/registry';

const loader = vi.hoisted(() => ({ resolve: vi.fn() }));
vi.mock('../../src/plugin_host/loader', () => ({
  normalizePluginId: (id: string) => id.trim().toLowerCase(),
  getRegisteredPluginIds: () => ['file-explorer'],
  resolvePluginComponentAsync: loader.resolve,
}));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe('PluginHost instance ownership', () => {
  it('does not report idle until the last host unmounts', async () => {
    const FileExplorer = React.lazy(async () => ({
      default: () => <div>Inventory</div>,
    }));
    loader.resolve.mockResolvedValue(FileExplorer);
    const first = render(<PluginHost pluginId="file-explorer" />);
    await waitFor(() => expect(mountStateRegistry.get('file-explorer')?.state).toBe('mounted'));
    const second = render(<PluginHost pluginId="file-explorer" />);
    await waitFor(() => expect(screen.getAllByText('Inventory')).toHaveLength(2));
    first.unmount();
    expect(mountStateRegistry.get('file-explorer')?.state).toBe('mounted');
    second.unmount();
    expect(mountStateRegistry.get('file-explorer')?.state).toBe('idle');
  });

  it('does not resurrect the observation after a closed host resolves', async () => {
    let resolve!: (value: null) => void;
    loader.resolve.mockReturnValue(new Promise<null>((done) => { resolve = done; }));
    const view = render(<PluginHost pluginId="file-explorer" />);
    expect(mountStateRegistry.get('file-explorer')?.state).toBe('loading');
    view.unmount();
    resolve(null);
    await Promise.resolve();
    expect(mountStateRegistry.get('file-explorer')?.state).toBe('idle');
  });
});
