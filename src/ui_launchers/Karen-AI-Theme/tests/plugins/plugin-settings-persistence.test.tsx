import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import apiClient from '@/lib/api';
import {
  PluginSettingsProvider,
  usePluginSettings,
  usePluginSettingsManager,
} from '@/plugin_host/plugin-settings';

vi.mock('@/lib/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const settings = {
  plugin_id: 'settings-test',
  settings: { region: 'east', enabled: false },
  schema: [
    { key: 'region', label: 'Region', type: 'string', readOnly: false },
    { key: 'enabled', label: 'Enabled', type: 'boolean', readOnly: false },
    { key: 'api_key', label: 'API Key', type: 'password', readOnly: true },
  ],
  revision: 3,
  stored: true,
};

function Probe() {
  const state = usePluginSettings('settings-test');
  const manager = usePluginSettingsManager();
  return (
    <div>
      <span data-testid="loaded">{String(state.loaded)}</span>
      <span data-testid="modified">{String(state.modified)}</span>
      <span data-testid="revision">{state.revision}</span>
      <span data-testid="region">{String(state.values.region ?? '')}</span>
      <span data-testid="error">{state.error ?? ''}</span>
      <button onClick={() => { void manager.refreshSettings('settings-test'); }}>Load</button>
      <button onClick={() => manager.updateSetting('settings-test', 'region', 'west')}>Edit</button>
      <button onClick={() => manager.updateSetting('settings-test', 'api_key', 'must-not-submit')}>Edit secret</button>
      <button onClick={() => { void manager.savePluginSettings('settings-test'); }}>Save</button>
      <button onClick={() => { void manager.resetPluginSettings('settings-test'); }}>Reset</button>
    </div>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(settings);
});
afterEach(cleanup);

describe('governed tenant plugin settings UI', () => {
  it('rejects malformed GET instead of fabricating a saved empty configuration', async () => {
    vi.mocked(apiClient.get).mockResolvedValue(null);
    render(<PluginSettingsProvider><Probe /></PluginSettingsProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await waitFor(() => expect(screen.getByTestId('error').textContent).toContain('invalid response'));
    expect(screen.getByTestId('loaded').textContent).toBe('true');
    expect(screen.getByTestId('revision').textContent).toBe('0');
    expect(screen.getByTestId('modified').textContent).toBe('false');
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it('keeps secrets read-only and only confirms a revision-backed save', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      ...settings,
      settings: { region: 'west', enabled: false },
      revision: 4,
      success: true,
      saved: true,
    });
    render(<PluginSettingsProvider><Probe /></PluginSettingsProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await waitFor(() => expect(screen.getByTestId('revision').textContent).toBe('3'));

    fireEvent.click(screen.getByRole('button', { name: 'Edit secret' }));
    expect(screen.getByTestId('modified').textContent).toBe('false');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await waitFor(() => expect(screen.getByTestId('modified').textContent).toBe('true'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.getByTestId('revision').textContent).toBe('4'));
    expect(screen.getByTestId('modified').textContent).toBe('false');
    expect(screen.getByTestId('region').textContent).toBe('west');
    expect(apiClient.post).toHaveBeenCalledWith('/api/extensions/settings-test/settings', {
      settings: { region: 'west', enabled: false },
      revision: 3,
    });
    expect(JSON.stringify(vi.mocked(apiClient.post).mock.calls)).not.toContain('must-not-submit');
  });

  it('refuses a successful HTTP response without a database save receipt', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ status: 'ok' });
    render(<PluginSettingsProvider><Probe /></PluginSettingsProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await waitFor(() => expect(screen.getByTestId('revision').textContent).toBe('3'));
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await waitFor(() => expect(screen.getByTestId('modified').textContent).toBe('true'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.getByTestId('error').textContent).toContain('invalid response'));
    expect(screen.getByTestId('modified').textContent).toBe('true');
    expect(screen.getByTestId('revision').textContent).toBe('3');
  });

  it('keeps the local draft on an optimistic-concurrency conflict', async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error('409: settings changed; refresh'));
    render(<PluginSettingsProvider><Probe /></PluginSettingsProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await waitFor(() => expect(screen.getByTestId('revision').textContent).toBe('3'));
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await waitFor(() => expect(screen.getByTestId('region').textContent).toBe('west'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.getByTestId('error').textContent).toContain('409'));
    expect(screen.getByTestId('modified').textContent).toBe('true');
    expect(screen.getByTestId('region').textContent).toBe('west');
  });

  it('uses the observed revision for reset and waits for a durable reset receipt', async () => {
    vi.mocked(apiClient.delete).mockResolvedValue({
      ...settings,
      settings: { region: 'east', enabled: false },
      revision: 4,
      reset: true,
      success: true,
    });
    render(<PluginSettingsProvider><Probe /></PluginSettingsProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await waitFor(() => expect(screen.getByTestId('revision').textContent).toBe('3'));
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    await waitFor(() => expect(screen.getByTestId('revision').textContent).toBe('4'));
    expect(apiClient.delete).toHaveBeenCalledWith(
      '/api/extensions/settings-test/settings?revision=3',
    );
    expect(screen.getByTestId('modified').textContent).toBe('false');
  });
});
