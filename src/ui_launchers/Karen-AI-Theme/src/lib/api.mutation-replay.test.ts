// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import apiClient, { ApiError, captureApiPrincipalScope } from './api';
import { authService } from '@/lib/auth';

vi.mock('@/lib/auth', () => ({
  authService: { clearAuth: vi.fn(), getCurrentUser: vi.fn(), getAuthenticationRevision: vi.fn() },
}));
vi.mock('@/lib/auth-events', () => ({
  dispatchAuthInvalidated: vi.fn(),
}));

type MutationMethod = 'post' | 'put' | 'patch' | 'delete';

type InternalClientForTests = {
  getPreferredBaseUrl: () => string | null;
  getFallbackBaseUrl: (preferred: string | null) => string | null;
  hasFallbackBaseUrl: (fallback: string | null) => boolean;
  refreshAccessToken: () => Promise<void>;
};

const clientInternals = apiClient as unknown as InternalClientForTests;

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
    vi.spyOn(clientInternals, 'getPreferredBaseUrl').mockReturnValue('');
    vi.spyOn(clientInternals, 'getFallbackBaseUrl').mockReturnValue('http://127.0.0.1:8000');
    vi.spyOn(clientInternals, 'hasFallbackBaseUrl').mockReturnValue(true);
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

  it('coalesces concurrent refresh calls into a single POST', async () => {
    localStorage.setItem('refresh_token', 'one-session-refresh-token');
    let resolveFetch!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { resolveFetch = resolve; });
    const fetchMock = vi.fn().mockReturnValue(pending);
    vi.stubGlobal('fetch', fetchMock);

    const first = clientInternals.refreshAccessToken();
    const second = clientInternals.refreshAccessToken();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveFetch(new Response(JSON.stringify({
      access_token: 'fresh-access-token',
      refresh_token: 'rotated-session-refresh-token',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    await Promise.all([first, second]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('access_token')).toBe('fresh-access-token');
    expect(localStorage.getItem('refresh_token')).toBe('rotated-session-refresh-token');
  });

  it('rejects a late refresh response after the session changed', async () => {
    localStorage.setItem('refresh_token', 'previous-refresh-token');
    localStorage.setItem('access_token', 'previous-access-token');
    let resolveFetch!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { resolveFetch = resolve; });
    const fetchMock = vi.fn().mockReturnValue(pending);
    vi.stubGlobal('fetch', fetchMock);

    const refresh = clientInternals.refreshAccessToken();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    localStorage.setItem('refresh_token', 'different-session-refresh-token');
    resolveFetch(new Response(JSON.stringify({
      access_token: 'stale-refresh-result',
      refresh_token: 'rotated-but-not-authorized',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));

    await expect(refresh).rejects.toThrow('Refresh session changed during request');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('access_token')).toBe('previous-access-token');
    expect(localStorage.getItem('refresh_token')).toBe('different-session-refresh-token');
  });

  it('uses the newly rotated refresh token on the next request', async () => {
    localStorage.setItem('refresh_token', 'original-refresh');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: 'first-access',
        refresh_token: 'second-refresh',
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: 'second-access',
        refresh_token: 'third-refresh',
      }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await clientInternals.refreshAccessToken();
    await clientInternals.refreshAccessToken();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).refresh_token)
      .toBe('original-refresh');
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).refresh_token)
      .toBe('second-refresh');
    expect(localStorage.getItem('refresh_token')).toBe('third-refresh');
    expect(localStorage.getItem('access_token')).toBe('second-access');
  });

  it.each([
    { access_token: 'new-access' },
    { access_token: 'new-access', refresh_token: 'original-refresh' },
  ])('rejects invalid refresh pairs without overwriting credentials', async (payload) => {
    localStorage.setItem('refresh_token', 'original-refresh');
    localStorage.setItem('access_token', 'original-access');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 200,
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(clientInternals.refreshAccessToken()).rejects.toThrow(
      'Invalid refresh response: missing or unrotated token pair',
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('access_token')).toBe('original-access');
    expect(localStorage.getItem('refresh_token')).toBe('original-refresh');
  });

  it('never retries a credential-rotating refresh after a lost response', async () => {
    localStorage.setItem('refresh_token', 'refresh-credential-for-single-attempt-proof');
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(clientInternals.refreshAccessToken())
      .rejects.toThrow('Failed to fetch');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' });
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/auth/refresh');
  });

  it('does not fall back when a refresh response is 503', async () => {
    localStorage.setItem('refresh_token', 'refresh-credential-for-status-proof');
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('Unverified refresh outcome', { status: 503 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(clientInternals.refreshAccessToken())
      .rejects.toThrow('Token refresh failed: 503');

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('never refreshes and replays an already-sent mutation after HTTP 401', async () => {
    localStorage.setItem('refresh_token', 'present-only-to-detect-unsafe-replay');
    const refreshSpy = vi.spyOn(clientInternals, 'refreshAccessToken')
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

describe("principal-fenced API requests", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });
  it.each(["post", "patch", "delete"] as const)("does not dispatch a %s mutation after authentication changes during asynchronous header resolution", async (method) => {
    const identity = { tenant_id: "tenant", user_id: "owner" } as ReturnType<typeof authService.getCurrentUser>;
    vi.mocked(authService.getCurrentUser).mockReturnValue(identity);
    vi.mocked(authService.getAuthenticationRevision).mockReturnValue(1);
    const scope = captureApiPrincipalScope("tenant", "owner");
    expect(scope).not.toBeNull();
    let release!: (headers: Record<string, string>) => void;
    const pending = new Promise<Record<string, string>>(resolve => { release = resolve; });
    const internals = apiClient as unknown as { getAuthHeaders: () => Promise<Record<string, string>> };
    vi.spyOn(internals, "getAuthHeaders").mockReturnValue(pending);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const request = apiClient[method]("/api/plugins/file-explorer/folders/example", { expected_revision: "7" }, {}, scope!);
    vi.mocked(authService.getAuthenticationRevision).mockReturnValue(2);
    release({ Authorization: "Bearer test-token" });
    await expect(request).rejects.toThrow("Authenticated request scope changed");
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("discards a delayed response after the current account changes", async () => {
    vi.mocked(authService.getCurrentUser).mockReturnValue({ tenant_id: "tenant", user_id: "owner" } as ReturnType<typeof authService.getCurrentUser>);
    vi.mocked(authService.getAuthenticationRevision).mockReturnValue(1);
    const scope = captureApiPrincipalScope("tenant", "owner")!;
    let release!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { release = resolve; })));
    const request = apiClient.get("/api/communications-center/inbox", scope);
    await vi.waitFor(() => expect(release).toBeTypeOf("function"));
    vi.mocked(authService.getCurrentUser).mockReturnValue({ tenant_id: "other", user_id: "other" } as ReturnType<typeof authService.getCurrentUser>);
    release(new Response(JSON.stringify({ entries: [] }), { status: 200 }));
    await expect(request).rejects.toThrow("Authenticated request scope changed");
  });
});


describe('request diagnostic privacy', () => {
  const marker = 'private-acquisition';
  const endpoint = `/api/plugins/file-explorer/inventory?search=${marker}%20plan&cursor=private-cursor`;

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.spyOn(clientInternals, 'getPreferredBaseUrl').mockReturnValue('http://api:8000');
    vi.spyOn(clientInternals, 'getFallbackBaseUrl').mockReturnValue(null);
    vi.spyOn(clientInternals, 'hasFallbackBaseUrl').mockReturnValue(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  function observeDiagnostics() {
    const log = vi.spyOn(console, 'log').mockImplementation(() => {});
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    return () => {
      const calls = [...log.mock.calls, ...warn.mock.calls, ...error.mock.calls];
      expect(calls.length).toBeGreaterThan(0);
      for (const args of calls) {
        expect(args.every((arg) => typeof arg === 'string')).toBe(true);
        expect(args.join(' ')).not.toContain(marker);
        expect(args.join(' ')).not.toContain('private-cursor');
        expect(args.join(' ')).not.toContain('search=');
      }
    };
  }

  it('preserves the query on the wire but never logs it on success', async () => {
    const assertPrivate = observeDiagnostics();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] })));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient.get(endpoint)).resolves.toEqual({ items: [] });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(endpoint);
    assertPrivate();
  });

  it('does not log a transport exception that embeds the private target', async () => {
    const assertPrivate = observeDiagnostics();
    const failure = new TypeError(`Failed to fetch ${endpoint}`);
    const fetchMock = vi.fn().mockRejectedValue(failure);
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient.get(endpoint)).rejects.toBe(failure);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(endpoint);
    assertPrivate();
  });

  it('does not log the target when an unauthenticated request receives 401', async () => {
    const assertPrivate = observeDiagnostics();
    const fetchMock = vi.fn().mockResolvedValue(new Response('Unauthorized', { status: 401 }));
    vi.stubGlobal('fetch', fetchMock);

    // Preserve the existing safe-read 401 contract: session invalidation,
    // not an ApiError or a replay of the unauthorized request.
    await expect(apiClient.getUnauthenticated(endpoint)).resolves.toBeUndefined();
    const { authService } = await import('@/lib/auth');
    const { dispatchAuthInvalidated } = await import('@/lib/auth-events');
    expect(authService.clearAuth).toHaveBeenCalledTimes(1);
    expect(dispatchAuthInvalidated).toHaveBeenCalledWith('terminal_401');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(endpoint);
    assertPrivate();
  });

  it('keeps safe-read fallback requests private without changing their targets', async () => {
    const assertPrivate = observeDiagnostics();
    vi.mocked(clientInternals.getFallbackBaseUrl).mockReturnValue('http://127.0.0.1:8000');
    vi.mocked(clientInternals.hasFallbackBaseUrl).mockReturnValue(true);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('unavailable', { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [] })));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiClient.get(endpoint)).resolves.toEqual({ items: [] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const call of fetchMock.mock.calls) expect(call[0]).toBe(endpoint);
    assertPrivate();
  });
});


describe("bounded authenticated inbox waits", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("access_token", "existing-token");
    localStorage.setItem("refresh_token", "existing-refresh");
    vi.mocked(authService.getCurrentUser).mockReturnValue({ tenant_id: "tenant", user_id: "owner" } as ReturnType<typeof authService.getCurrentUser>);
    vi.mocked(authService.getAuthenticationRevision).mockReturnValue(1);
    vi.mocked(authService.clearAuth).mockClear();
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

  it.each([401, 403, 502, 503])("never refreshes, logs out or replays on %s", async (status) => {
    const scope = captureApiPrincipalScope("tenant", "owner")!;
    const refresh = vi.spyOn(clientInternals, "refreshAccessToken");
    const fetchMock = vi.fn().mockResolvedValue(new Response("private error", { status }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await expect(apiClient.waitForInboxInvalidation(scope, controller.signal)).rejects.toMatchObject({ status });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/communications-center/inbox/wait");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "GET", cache: "no-store", redirect: "error", signal: controller.signal });
    expect(refresh).not.toHaveBeenCalled();
    expect(authService.clearAuth).not.toHaveBeenCalled();
    expect(localStorage.getItem("access_token")).toBe("existing-token");
    expect(localStorage.getItem("refresh_token")).toBe("existing-refresh");
  });

  it("does not dispatch an aborted or obsolete request and discards late results", async () => {
    const scope = captureApiPrincipalScope("tenant", "owner")!;
    const controller = new AbortController();
    controller.abort();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiClient.waitForInboxInvalidation(scope, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled();
    let release!: (response: Response) => void;
    fetchMock.mockReturnValue(new Promise<Response>(resolve => { release = resolve; }));
    const live = new AbortController();
    const pending = apiClient.waitForInboxInvalidation(scope, live.signal);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    vi.mocked(authService.getAuthenticationRevision).mockReturnValue(2);
    release(new Response('{"changed":true}', { status: 200 }));
    await expect(pending).rejects.toThrow("Authenticated request scope changed");
    await expect(apiClient.waitForInboxInvalidation(scope, live.signal)).rejects.toThrow("Authenticated request scope changed");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
