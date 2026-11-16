import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { PluginRecommendedModels } from '@/components/plugins/PluginRecommendedModels';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  admin: true,
}));

vi.mock('@/lib/api', () => ({
  apiClient: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: (...args: unknown[]) => mocks.post(...args),
  },
}));

vi.mock('@/lib/useAuth', () => ({
  useAuth: () => ({
    isAdmin: () => mocks.admin,
    user: mocks.admin
      ? { user_id: 'admin-1', roles: ['admin'] }
      : { user_id: 'member-1', roles: ['user'] },
  }),
}));

const PINNED = 'db04f0e653473e5c7333c69686ac92b7460b0c1d';
const recommendation = {
  id: 'pocket-tts-english-18m-refl',
  model_id: 'kyutai/pocket-tts',
  label: 'Pocket TTS English 18.2M (REFL)',
  purpose: 'CPU speech synthesis',
  channel_id: 'plugin_audio',
  revision: PINNED,
  resolved_revision: PINNED,
  metadata_verified: true,
  verification_state: 'verified',
  license: 'CC-BY-4.0',
  license_url: 'https://huggingface.co/kyutai/pocket-tts/tree/' + PINNED,
  gated: true,
  include_patterns: [
    'languages/english_18m_refl_2026-10/model.safetensors',
    'languages/english_18m_refl_2026-10/tokenizer.model',
    'languages/english_18m_refl_2026-10/embeddings/**',
  ],
  app_consumers: ['pocket-tts'],
  installed: false,
};

const policy = {
  master_enabled: true,
  block_new_downloads: false,
  require_license_acceptance: true,
};
const channels = { channels: [{ id: 'plugin_audio', admin_only: true, effective_enabled: true }] };

const catalog = (overrides: Record<string, unknown> = {}) => ({
  recommendations: [{ ...recommendation, ...overrides }],
});

const getImpl = (source = catalog(), nextPolicy = policy, jobs: unknown[] = []) =>
  mocks.get.mockImplementation(async (url: string) => {
    if (url === '/api/models/download/recommendations') return source;
    if (url === '/api/models/download/policy') return nextPolicy;
    if (url === '/api/models/download/channels') return channels;
    if (url === '/api/runtime/model-library/my-downloads?limit=200') {
      return { jobs, total: jobs.length, scope: 'authenticated_user' };
    }
    throw new Error('Unexpected model control URL: ' + url);
  });

beforeEach(() => {
  vi.resetAllMocks();
  mocks.admin = true;
  getImpl();
  mocks.post.mockImplementation(async (path: string) => {
    if (path === '/api/models/download/validate') {
      return {
        allowed: true,
        model_id: recommendation.model_id,
        channel_id: recommendation.channel_id,
        metadata: { resolved_revision: PINNED },
        blocking_reasons: [],
      };
    }
    if (path === '/api/models/download') {
      return {
        job_id: 'mdl-a3478177-6f1a-4e99-ab3a-9f94dd73a335',
        status: 'queued',
      };
    }
    throw new Error('Unexpected download route: ' + path);
  });
});
afterEach(cleanup);

describe('Governed plugin model setup', () => {
  it('shows Pocket model requirement using canonical curated backend recommendations', async () => {
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    expect(await screen.findByText('Pocket TTS English 18.2M (REFL)')).toBeTruthy();
    expect(screen.getByText('Model missing')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Review CC-BY-4.0 terms/ })).toBeTruthy();
    expect(mocks.get).toHaveBeenCalledWith('/api/models/download/recommendations');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('requires explicit license acceptance and validates immutable revision before queueing', async () => {
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    const section = await screen.findByTestId('plugin-recommended-models');
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    const download = within(section).getByRole('button', { name: 'Download recommended model' });
    expect(download.hasAttribute('disabled')).toBe(true);

    fireEvent.click(within(section).getByRole('checkbox'));
    expect(download.hasAttribute('disabled')).toBe(false);
    fireEvent.click(download);

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post).toHaveBeenNthCalledWith(1, '/api/models/download/validate', {
      model_id: 'kyutai/pocket-tts',
      revision: PINNED,
      channel_id: 'plugin_audio',
      include_patterns: recommendation.include_patterns,
      exclude_patterns: [],
      trust_remote_code: false,
      accept_license: true,
    });
    expect(mocks.post).toHaveBeenNthCalledWith(2, '/api/models/download', {
      model_id: 'kyutai/pocket-tts',
      revision: null,
      validated_revision: PINNED,
      channel_id: 'plugin_audio',
      include_patterns: recommendation.include_patterns,
      exclude_patterns: [],
      trust_remote_code: false,
      accept_license: true,
      pin: true,
    });
    expect(await screen.findByText(/download job is queued/)).toBeTruthy();
  });

  it('rejects inconsistent backend validation without queueing any model', async () => {
    mocks.post.mockResolvedValueOnce({
      allowed: true,
      model_id: 'another/model',
      channel_id: 'plugin_audio',
      metadata: { resolved_revision: PINNED },
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Download recommended model' }));
    await screen.findByText(/could not verify or queue the selected model/i);
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it('fails closed when source verification is unavailable or pinned revision is mutable', async () => {
    getImpl(catalog({ metadata_verified: false, verification_state: 'unavailable', resolved_revision: 'main' }));
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    expect(screen.getByRole('button', { name: 'Download recommended model' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('alert').textContent).toContain('could not be verified');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('rejects a download-history response without authenticated owner scope', async () => {
    mocks.get.mockImplementation(async (url: string) => {
      if (url === '/api/models/download/recommendations') return catalog();
      if (url === '/api/models/download/policy') return policy;
      if (url === '/api/models/download/channels') return channels;
      if (url === '/api/runtime/model-library/my-downloads?limit=200') {
        return { jobs: [], scope: 'admin_global' };
      }
      throw new Error('Unexpected URL');
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    expect(await screen.findByText(/could not verify recommended models/)).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('blocks a second queue if a matching model is already running', async () => {
    getImpl(catalog(), policy, [{
      model_id: recommendation.model_id,
      revision: PINNED,
      channel_id: 'plugin_audio',
      status: 'running',
      progress: 38,
      job_id: 'mdl-a3478177-6f1a-4e99-ab3a-9f94dd73a335',
    }]);
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    expect(screen.getByText(/Download job: running/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Download recommended model' })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each(['failed', 'cancelled'] as const)(
    'restores the download action after an owned queued job becomes %s',
    async (terminalStatus) => {
      const jobId = 'mdl-a3478177-6f1a-4e99-ab3a-9f94dd73a335';
      const initialGet = mocks.get.getMockImplementation();
      mocks.get.mockImplementation(async (url: string) => {
        if (url === `/api/runtime/model-library/my-downloads/${jobId}`) {
          return {
            job_id: jobId,
            model_id: recommendation.model_id,
            revision: PINNED,
            channel_id: recommendation.channel_id,
            status: terminalStatus,
            progress: 0.25,
          };
        }
        return initialGet?.(url);
      });
      // Capture only the component's 4-second polling callback without
      // changing the timers used by Testing Library's async assertions.
      const nativeTimeout = window.setTimeout.bind(window);
      const pollRef: { current: (() => void) | null } = { current: null };
      const timeoutSpy = vi.spyOn(window, 'setTimeout').mockImplementation(
        (handler, delay, ...args) => {
          if (delay === 4000 && typeof handler === 'function') {
            pollRef.current = () => handler(...args);
            return 123 as unknown as ReturnType<typeof setTimeout>;
          }
          return nativeTimeout(handler, delay, ...args) as unknown as ReturnType<typeof setTimeout>;
        },
      );
      try {
        render(<PluginRecommendedModels pluginId="pocket-tts" />);
        await screen.findByText('Pocket TTS English 18.2M (REFL)');
        fireEvent.click(screen.getByRole('checkbox'));
        fireEvent.click(screen.getByRole('button', { name: 'Download recommended model' }));
        await screen.findByText(/download job is queued/);
        expect(screen.getByText(/Download job: queued/)).toBeTruthy();
        await waitFor(() => expect(pollRef.current).not.toBeNull());

        await act(async () => { pollRef.current?.(); await Promise.resolve(); });
        expect(mocks.get).toHaveBeenCalledWith(
          `/api/runtime/model-library/my-downloads/${jobId}`,
        );
        const retry = screen.getByRole('button', { name: 'Download recommended model' });
        expect(retry.hasAttribute('disabled')).toBe(false);
        expect(screen.getByText(/Model download did not complete/)).toBeTruthy();

        fireEvent.click(retry);
        await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(4));
      } finally {
        timeoutSpy.mockRestore();
      }
    },
  );

  it('fails closed without admin role or when the canonical download API is unavailable', async () => {
    mocks.admin = false;
    const { unmount } = render(<PluginRecommendedModels pluginId="pocket-tts" />);
    expect(screen.getByText(/Model downloads require an administrator/)).toBeTruthy();
    expect(mocks.get).not.toHaveBeenCalled();
    unmount();

    mocks.admin = true;
    mocks.get.mockRejectedValue(new Error('secret token / private traceback'));
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    const alert = await screen.findByText(/could not verify recommended models/);
    expect(alert.textContent).not.toContain('secret');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('does not guess an available model for a plugin with no curated requirement', async () => {
    render(<PluginRecommendedModels pluginId="another-plugin" />);
    await screen.findByText(/no curated downloadable model for this plugin/);
    expect(screen.queryByRole('button', { name: 'Download recommended model' })).toBeNull();
  });
});
