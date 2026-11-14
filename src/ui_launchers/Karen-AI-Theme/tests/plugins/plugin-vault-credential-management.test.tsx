import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import apiClient from '@/lib/api';
import { PluginSettingsForm, PluginSettingsProvider } from '@/plugin_host/plugin-settings';

vi.mock('@/lib/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const settings = {
  plugin_id: 'vault-test',
  settings: { region: 'east' },
  schema: [
    { key: 'region', label: 'Region', type: 'string', readOnly: false },
    { key: 'api_key', label: 'API key', type: 'password', readOnly: true },
  ],
  revision: 1,
  stored: true,
};

const absent = {
  plugin_id: 'vault-test',
  fields: {
    api_key: { configured: false, status: 'missing', revision: 0 },
  },
};

function renderForm() {
  return render(
    <PluginSettingsProvider>
      <PluginSettingsForm pluginId="vault-test" />
    </PluginSettingsProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === '/api/extensions/vault-test/settings') return settings;
    if (path === '/api/extensions/vault-test/credentials') return absent;
    throw new Error('Unknown API route');
  });
});
afterEach(cleanup);

describe('Plugin credential enrollment via canonical Identity Vault', () => {
  it('renders a separate credential field without readback or generic settings writes', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      plugin_id: 'vault-test',
      field_key: 'api_key',
      configured: true,
      status: 'active',
      revision: 1,
    });
    renderForm();
    expect(await screen.findByText('Not configured')).toBeTruthy();
    const field = screen.getByLabelText('API key') as HTMLInputElement;
    expect(field.type).toBe('password');
    expect(field.value).toBe('');
    fireEvent.change(field, { target: { value: 'top-secret-only-in-submit' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save credential' }));
    await waitFor(() => expect(screen.getByText('Configured in Identity Vault')).toBeTruthy());
    expect(field.value).toBe('');
    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/extensions/vault-test/credentials/api_key',
      { value: 'top-secret-only-in-submit', revision: 0 },
    );
    expect(apiClient.post).not.toHaveBeenCalledWith(
      '/api/extensions/vault-test/settings',
      expect.anything(),
    );
    expect(screen.queryByText('top-secret-only-in-submit')).toBeNull();
    expect(screen.getByText('Credential saved in Identity Vault.')).toBeTruthy();
  });

  it('rotates with the confirmed revision and explicitly confirms revocation', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/extensions/vault-test/settings') return settings;
      if (path === '/api/extensions/vault-test/credentials') {
        return {
          plugin_id: 'vault-test',
          fields: {
            api_key: { configured: true, status: 'active', revision: 6 },
          },
        };
      }
      throw new Error('Unknown API route');
    });
    vi.mocked(apiClient.post).mockResolvedValue({
      plugin_id: 'vault-test',
      field_key: 'api_key',
      configured: true, status: 'active', revision: 7,
    });
    vi.mocked(apiClient.delete).mockResolvedValue({
      plugin_id: 'vault-test',
      field_key: 'api_key',
      configured: false, status: 'revoked', revision: 8,
    });
    renderForm();
    expect(await screen.findByText('Configured in Identity Vault')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'replacement-value' } });
    fireEvent.click(screen.getByRole('button', { name: 'Rotate credential' }));
    await waitFor(() => expect(screen.getByText('Credential saved in Identity Vault.')).toBeTruthy());
    expect(apiClient.post).toHaveBeenCalledWith(
      '/api/extensions/vault-test/credentials/api_key',
      { value: 'replacement-value', revision: 6 },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Revoke credential' }));
    expect(apiClient.delete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm revoke' }));
    await waitFor(() => expect(screen.getByText('Revoked')).toBeTruthy());
    expect(apiClient.delete).toHaveBeenCalledWith(
      '/api/extensions/vault-test/credentials/api_key?revision=7',
    );
    expect(screen.getByText('Credential revoked and encrypted value erased.')).toBeTruthy();
  });

  it('does not claim success on malformed 200 or stale revision', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ status: 'ok' });
    renderForm();
    expect(await screen.findByText('Not configured')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save credential' }));
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('did not confirm credential persistence'),
    );
    expect(screen.getByText('Not configured')).toBeTruthy();
    expect((screen.getByLabelText('API key') as HTMLInputElement).value).toBe('');
    expect(screen.queryByText('Credential saved in Identity Vault.')).toBeNull();
  });

  it('fails closed on an unavailable credential inventory', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/extensions/vault-test/settings') return settings;
      throw new Error('Vault unavailable');
    });
    renderForm();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Vault unavailable');
    expect(screen.queryByRole('button', { name: 'Save credential' })).toBeNull();
    expect(screen.queryByLabelText('API key')).toBeNull();
  });

  it('rejects credential status missing revision or revealing a raw secret', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === '/api/extensions/vault-test/settings') return settings;
      if (path === '/api/extensions/vault-test/credentials') {
        return {
          plugin_id: 'vault-test',
          fields: {
            api_key: { configured: true, status: 'active', value: 'leaked-value' },
          },
        };
      }
      throw new Error('Unknown API route');
    });
    renderForm();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('invalid credential receipt');
    expect(screen.queryByText('leaked-value')).toBeNull();
    expect(screen.queryByLabelText('API key')).toBeNull();
  });
});
