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

const PINNED = 'a7056f505a4a8ca72d8b5fb1440071d6f1a35739';
const recommendation = {
  id: 'pocket-tts-english-18m-refl',
  model_id: 'kyutai/pocket-tts-without-voice-cloning',
  label: 'Pocket TTS English 18.2M (REFL)',
  purpose: 'CPU speech synthesis',
  channel_id: 'plugin_audio',
  revision: PINNED,
  resolved_revision: PINNED,
  metadata_verified: true,
  verification_state: 'verified',
  license: 'CC-BY-4.0',
  license_url: 'https://huggingface.co/kyutai/pocket-tts-without-voice-cloning/tree/' + PINNED,
  gated: false,
  include_patterns: [
    'languages/english_18m_refl_2026-10/model.safetensors',
    'languages/english_18m_refl_2026-10/tokenizer.model',
    'languages/english_18m_refl_2026-10/embeddings/**',
  ],
  app_consumers: ['pocket-tts'],
  download_methods: ['hf_hub', 'direct_https'],
  installed: false,
};

const policy = {
  master_enabled: true,
  block_new_downloads: false,
  require_license_acceptance: true,
};
// Match ModelDownloadControlService: plugin_audio is enabled but not admin_only.
const channels = { channels: [{ id: 'plugin_audio', admin_only: false, effective_enabled: true }] };

const catalog = (overrides: Record<string, unknown> = {}) => ({
  recommendations: [{ ...recommendation, ...overrides }],
});

const getImpl = (source = catalog(), nextPolicy = policy, jobs: unknown[] = [], nextChannels = channels) =>
  mocks.get.mockImplementation(async (url: string) => {
    if (url === '/api/models/download/recommendations') return source;
    if (url === '/api/models/download/policy') return nextPolicy;
    if (url === '/api/models/download/channels') return nextChannels;
    if (url === '/api/runtime/model-library/my-downloads?limit=200') {
      return { jobs, total: jobs.length, scope: 'authenticated_user' };
    }
    throw new Error('Unexpected model control URL: ' + url);
  });

beforeEach(() => {
  vi.resetAllMocks();
  mocks.admin = true;
  getImpl();
  mocks.post.mockImplementation(async (path: string, payload?: { download_method?: string }) => {
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
        download_method: payload?.download_method || 'hf_hub',
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

  it('installs the official public model in one click with pinned verification', async () => {
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    const section = await screen.findByTestId('plugin-recommended-models');
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    const download = within(section).getByRole('button', { name: 'Download recommended model' });
    expect(within(section).queryByRole('checkbox')).toBeNull();
    expect(within(section).getByTestId('public-model-one-click').textContent)
      .toContain('no Hugging Face account or token needed');
    expect(download.hasAttribute('disabled')).toBe(false);
    fireEvent.click(download);

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post).toHaveBeenNthCalledWith(1, '/api/models/download/validate', {
      model_id: 'kyutai/pocket-tts-without-voice-cloning',
      revision: PINNED,
      channel_id: 'plugin_audio',
      include_patterns: recommendation.include_patterns,
      exclude_patterns: [],
      trust_remote_code: false,
      accept_license: true,
    });
    expect(mocks.post).toHaveBeenNthCalledWith(2, '/api/models/download', {
      model_id: 'kyutai/pocket-tts-without-voice-cloning',
      revision: null,
      validated_revision: PINNED,
      channel_id: 'plugin_audio',
      include_patterns: recommendation.include_patterns,
      exclude_patterns: [],
      trust_remote_code: false,
      accept_license: true,
      pin: true,
      download_method: 'direct_https',
    });
    expect(await screen.findByText(/download job is queued/)).toBeTruthy();
  });

  it('continues to require fresh explicit license approval for gated sources', async () => {
    getImpl(catalog({ gated: true }));
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    const button = screen.getByRole('button', { name: 'Download recommended model' });
    expect(button.hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(button.hasAttribute('disabled')).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
  });

  it('fails closed when source gating metadata is unknown', async () => {
    getImpl(catalog({ gated: undefined }));
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    const button = screen.getByRole('button', { name: 'Download recommended model' });
    expect(button.hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(button.hasAttribute('disabled')).toBe(false);
  });

  it('chooses direct HTTPS without changing license, revision, validation or worker endpoint', async () => {
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    expect(screen.getByText('Advanced download options')).toBeTruthy();
    fireEvent.click(screen.getByText('Advanced download options'));
    expect(screen.getByLabelText('Download method')).toBeTruthy();
    expect(screen.getByText('Direct HTTPS (no Hub SDK for transfer)')).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Download method'), {
      target: { value: 'direct_https' },
    });
    expect(screen.getByRole('button', { name: 'Download recommended model' })
      .hasAttribute('disabled')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Download recommended model' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));

    expect(mocks.post).toHaveBeenNthCalledWith(1, '/api/models/download/validate', {
      model_id: recommendation.model_id, revision: PINNED, channel_id: 'plugin_audio',
      include_patterns: recommendation.include_patterns,
      exclude_patterns: [], trust_remote_code: false, accept_license: true,
    });
    expect(mocks.post).toHaveBeenNthCalledWith(2, '/api/models/download', {
      model_id: recommendation.model_id, revision: null, validated_revision: PINNED,
      channel_id: 'plugin_audio', include_patterns: recommendation.include_patterns,
      exclude_patterns: [], trust_remote_code: false, accept_license: true,
      pin: true, download_method: 'direct_https',
    });
    expect(await screen.findByText(/download job is queued/)).toBeTruthy();
  });

  it('does not infer direct transport support without a backend catalog declaration', async () => {
    getImpl(catalog({ download_methods: ['hf_hub'] }));
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    expect(screen.queryByLabelText('Download method')).toBeNull();
  });

  it('keeps the download blocked when the actual audio channel is disabled', async () => {
    getImpl(catalog(), policy, [], {
      channels: [{ id: 'plugin_audio', admin_only: false, effective_enabled: false }],
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    expect(screen.getByText(/disabled channel/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download recommended model' })
      .hasAttribute('disabled')).toBe(true);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('rejects inconsistent backend validation without queueing any model', async () => {
    getImpl(catalog({ gated: true }));
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

  it('explains verified source-access denial without leaking backend text or queueing', async () => {
    getImpl(catalog({ gated: true }));
    mocks.post.mockResolvedValueOnce({
      allowed: false,
      model_id: recommendation.model_id,
      channel_id: recommendation.channel_id,
      metadata: { resolved_revision: PINNED },
      blocking_reasons: [
        'Model access metadata could not be verified; retry when license/gating metadata is available',
        'DO_NOT_EXPOSE_PRIVATE_BACKEND_DETAIL',
      ],
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Download recommended model' }));
    const alert = await screen.findByText(/could not verify the model license or source access/i);
    expect(alert.textContent).toContain('No job was queued');
    expect(screen.queryByText(/DO_NOT_EXPOSE_PRIVATE_BACKEND_DETAIL/)).toBeNull();
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect((screen.getByRole('checkbox') as HTMLButtonElement).getAttribute('data-state')).toBe('unchecked');
    expect(screen.getByRole('button', { name: 'Download recommended model' }).hasAttribute('disabled')).toBe(true);
  });

  it('classifies a tenant or administrator permission denial without leaking worker details', async () => {
    getImpl(catalog({ gated: true }));
    mocks.post.mockResolvedValueOnce({
      allowed: true,
      model_id: recommendation.model_id,
      channel_id: recommendation.channel_id,
      metadata: { resolved_revision: PINNED },
      blocking_reasons: [],
    }).mockRejectedValueOnce({
      status: 403,
      details: { error: 'secret=PRIVATE_TOKEN_VALUE' },
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Download recommended model' }));
    await screen.findByText(/Karen denied permission for this model download/i);
    expect(screen.queryByText(/PRIVATE_TOKEN_VALUE/)).toBeNull();
    expect(mocks.post).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Download recommended model' }).hasAttribute('disabled')).toBe(true);
  });

  it('classifies backend availability failures without displaying exception arguments', async () => {
    getImpl(catalog({ gated: true }));
    mocks.post.mockRejectedValueOnce({
      status: 503,
      message: 'backend unavailable: /private/path?token=SECRET_VALUE',
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Download recommended model' }));
    await screen.findByText(/backend model-download service is unavailable/i);
    expect(screen.queryByText(/SECRET_VALUE/)).toBeNull();
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Download recommended model' }).hasAttribute('disabled')).toBe(true);
  });

  it('fails closed when source verification is unavailable or pinned revision is mutable', async () => {
    getImpl(catalog({ metadata_verified: false, verification_state: 'unavailable', resolved_revision: 'main' }));
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    expect(screen.getByRole('button', { name: 'Download recommended model' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('alert').textContent).toContain('could not be verified');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('degrades without fabricating jobs when history scope is not the authenticated user', async () => {
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
    expect(await screen.findByTestId('download-history-degraded')).toBeTruthy();
    // No tracked or listed jobs may be invented from a non-owner response.
    expect(screen.queryByText(/download job is queued/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Download recommended model' })).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('shows actionable, redacted failure guidance from a scoped model worker receipt', async () => {
    getImpl(catalog({ gated: true }), policy, [{
      model_id: recommendation.model_id,
      revision: PINNED,
      channel_id: 'plugin_audio',
      status: 'failed',
      progress: 0,
      job_id: 'mdl-a3478177-6f1a-4e99-ab3a-9f94dd73a335',
      failure_category: 'source_access',
      // Even malformed responses must never turn raw worker diagnostics into UI.
      error: '403 gated model access denied: /secret/model-token=PRIVATE',
    }]);
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    const guidance = screen.getByTestId('plugin-last-download-failure');
    expect(guidance.textContent).toContain('model source');
    expect(guidance.textContent).toContain('fresh explicit model-license acceptance');
    expect(guidance.textContent).not.toContain('PRIVATE');
    expect(guidance.textContent).not.toContain('/secret/');
    const retry = screen.getByRole('button', { name: 'Download recommended model' });
    expect(retry.hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(retry.hasAttribute('disabled')).toBe(false);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each([
    ['network', /backend network, proxy, TLS/],
    ['storage', /available model storage/],
    ['integrity', /artifact integrity/],
    ['cancelled', /download was cancelled/],
    ['unknown', /authenticated job details/],
  ] as const)('renders only the scoped %s failure category', async (category, expected) => {
    getImpl(catalog(), policy, [{
      model_id: recommendation.model_id,
      revision: PINNED,
      channel_id: 'plugin_audio',
      status: 'failed',
      progress: 0,
      job_id: 'mdl-a3478177-6f1a-4e99-ab3a-9f94dd73a335',
      failure_category: category,
      message: 'token=/secret/a PRIVATE',
      error: 'token=/secret/a PRIVATE',
    }]);
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    const guidance = await screen.findByTestId('plugin-last-download-failure');
    expect(guidance.textContent).toMatch(expected);
    expect(guidance.textContent).not.toContain('PRIVATE');
    expect(guidance.textContent).not.toContain('/secret/');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('uses the canonical redacted source verification message on failed metadata checks', async () => {
    getImpl(catalog({
      metadata_verified: false,
      verification_state: 'unavailable',
      resolved_revision: null,
      verification_error: 'Model source rejected access. Check Hugging Face credentials and repository permissions.',
    }));
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    expect(screen.getByText(/Model source rejected access/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download recommended model' })
      .hasAttribute('disabled')).toBe(true);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('resumes polling an already-running owned Pocket job after navigation', async () => {
    const jobId = 'mdl-a3478177-6f1a-4e99-ab3a-9f94dd73a335';
    getImpl(catalog(), policy, [{
      model_id: recommendation.model_id,
      revision: PINNED,
      channel_id: 'plugin_audio',
      status: 'running',
      progress: 38,
      job_id: jobId,
    }]);

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
    const previousGet = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === `/api/runtime/model-library/my-downloads/${jobId}`) {
        return {
          job_id: jobId, model_id: recommendation.model_id,
          revision: PINNED, channel_id: 'plugin_audio',
          status: 'completed', progress: 1,
        };
      }
      return previousGet?.(url);
    });
    try {
      render(<PluginRecommendedModels pluginId="pocket-tts" />);
      await screen.findByText(/Download job: running/);
      await waitFor(() => expect(pollRef.current).not.toBeNull());
      await act(async () => { pollRef.current?.(); await Promise.resolve(); });
      await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(
        `/api/runtime/model-library/my-downloads/${jobId}`,
      ));
      expect(screen.getByText(/Model download completed/)).toBeTruthy();
      expect(screen.queryByText(/Download job: running/)).toBeNull();
      // This only confirms the worker receipt, never a selectable TTS engine.
      expect(screen.queryByText(/Pocket voice ready/)).toBeNull();
      expect(mocks.post).not.toHaveBeenCalled();
    } finally {
      timeoutSpy.mockRestore();
    }
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
      getImpl(catalog({ gated: true }));
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
        expect(retry.hasAttribute('disabled')).toBe(true);
        expect(screen.getByText(/Model download did not complete/)).toBeTruthy();
        expect(screen.queryByText(/download job is queued/)).toBeNull();

        // A failed/cancelled job cannot reuse the previous license checkbox.
        fireEvent.click(screen.getByRole('checkbox'));
        expect(retry.hasAttribute('disabled')).toBe(false);
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
    const alert = await screen.findByText(/Recommended model catalog could not be loaded/);
    expect(alert.textContent).not.toContain('secret');
    expect(mocks.post).not.toHaveBeenCalled();
  });


  it.each([
    ['/api/models/download/recommendations', 'Recommended model catalog'],
    ['/api/models/download/policy', 'Model download policy'],
    ['/api/models/download/channels', 'Model download channels'],
  ])('identifies a denied critical setup dependency without disclosing its response: %s', async (failedUrl, label) => {
    const previous = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === failedUrl) {
        throw { status: 403, message: 'secret=PRIVATE_TOKEN_VALUE' };
      }
      return previous?.(url);
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    const warning = await screen.findByText(new RegExp(label + ' could not be loaded'));
    expect(warning.textContent).toContain('Access denied');
    expect(warning.textContent).not.toContain('PRIVATE_TOKEN_VALUE');
    expect(screen.queryByRole('button', { name: 'Download recommended model' })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('degrades to an installable panel when only the download history service is unavailable', async () => {
    const previous = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === '/api/runtime/model-library/my-downloads?limit=200') {
        throw { status: 503, message: 'worker unavailable' };
      }
      return previous?.(url);
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);

    // The critical catalog loaded, so the install path stays available with
    // the proven direct-HTTPS method even while history is degraded.
    expect(await screen.findByTestId('download-history-degraded')).toBeTruthy();
    expect(screen.getByTestId('download-history-degraded').textContent)
      .toContain('Installation still runs in the audited worker');
    expect(screen.getByTestId('download-method-note').textContent)
      .toContain('no Hub setup or token needed');

    const download = screen.getByRole('button', { name: 'Download recommended model' });
    expect(download.hasAttribute('disabled')).toBe(false);
    fireEvent.click(download);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post).toHaveBeenNthCalledWith(2, '/api/models/download', {
      model_id: recommendation.model_id, revision: null, validated_revision: PINNED,
      channel_id: 'plugin_audio', include_patterns: recommendation.include_patterns,
      exclude_patterns: [], trust_remote_code: false, accept_license: true,
      pin: true, download_method: 'direct_https',
    });
    expect(await screen.findByText(/download job is queued/)).toBeTruthy();
  });

  it('keeps the Hub SDK default only when the backend does not declare direct transfer', async () => {
    getImpl(catalog({ download_methods: ['hf_hub'] }));
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    await screen.findByText('Pocket TTS English 18.2M (REFL)');
    expect(screen.queryByTestId('download-history-degraded')).toBeNull();
    expect(screen.getByTestId('download-method-note').textContent)
      .toContain('Hugging Face Hub SDK transfer');
    expect(screen.getByTestId('download-method-note').textContent)
      .not.toContain('no Hub setup or token needed');
  });

  it('reports a missing backend route without claiming model availability', async () => {
    const previous = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === '/api/models/download/policy') {
        throw { status: 404, message: '/private/backend/path?token=SECRET' };
      }
      return previous?.(url);
    });
    render(<PluginRecommendedModels pluginId="pocket-tts" />);
    const warning = await screen.findByText(/Model download policy could not be loaded/);
    expect(warning.textContent).toContain('API route was not found');
    expect(warning.textContent).not.toContain('SECRET');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('does not guess an available model for a plugin with no curated requirement', async () => {
    render(<PluginRecommendedModels pluginId="another-plugin" />);
    await screen.findByText(/no curated downloadable model for this plugin/);
    expect(screen.queryByRole('button', { name: 'Download recommended model' })).toBeNull();
  });
});
