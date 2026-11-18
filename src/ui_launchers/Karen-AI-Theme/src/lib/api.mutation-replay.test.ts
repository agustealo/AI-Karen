// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import apiClient, { ApiError } from './api';

vi.mock('@/lib/auth', () => ({
  authService: { clearAuth: vi.fn() },
}));
vi.mock('@/lib/auth-events', () => ({
  dispatchAuthInvalidated: vi.fn(),
}));

type MutationMethod = 'post' | 'put' | 'patch' | 'delete';

const invokeMutation = (method: MutationMethod): Promise<unknown> => {
  const path = '/api/plugins/time-query/lifecycle/disable/execute';
  if (method === 'delete') return apiClient.delete(path);
  return apiClient[method](path, { approval_id: '12345678-1234-1234-1234-123456789abc' });
};

describe('single-attempt authenticated mutations', () => {
  beforeEach(() => {
    localStorage.clear();
    // Force a plausible browser backend fallback, so the test fails if a
    // retry is accidentally enabled for a state-changing HTTP method.
    vi.spyOn(apiClient as never, 'getPreferredBaseUrl').mockReturnValue('');
    vi.spyOn(apiClient as never, 'getFallbackBaseUrl').mockReturnValue('http://127.0.0.1:8000');
    vi.spyOn(apiClient as never, 'hasFallbackBaseUrl').mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it.each(['post', 'put', 'patch', 'delete'] as const)(
    '%s does not retry a failed 503 after a possibly committed mutation',
    async (method) => {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Commit status is unknown' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
      vi.stubGlobal('fetch', fetchMock);

      await expect(invokeMutation(method)).rejects.toMatchObject({
        name: 'ApiError',
        status: 503,
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );

  it.each([404, 500, 502] as const)(
    'never tries a second mutation endpoint after HTTP %i',
    async (status) => {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Unverified mutation outcome' }), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
      vi.stubGlobal('fetch', fetchMock);

      await expect(apiClient.post('/api/approvals/test/decision', { decision: 'approved' }))
        .rejects.toBeInstanceOf(ApiError);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );

  it('never resends a mutation after an uncertain network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient.post('/api/approvals/test/decision', {
      decision: 'approved',
    })).rejects.toThrow('Failed to fetch');

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('never refreshes and replays an already-sent mutation after HTTP 401', async () => {
    localStorage.setItem('refresh_token', 'present-only-to-detect-unsafe-replay');
    const refreshSpy = vi.spyOn(apiClient as never, 'refreshAccessToken')
      .mockResolvedValue(undefined);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Session expired' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient.post('/api/plugins/time-query/lifecycle/enable/approval', {}))
      .rejects.toMatchObject({ name: 'ApiError', status: 401 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(refreshSpy).not.toHaveBeenCalled();
  });

  it('retains existing safe-read fallback for a failed GET', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('unavailable', { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient.get('/api/health')).resolves.toEqual({ status: 'ok' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
