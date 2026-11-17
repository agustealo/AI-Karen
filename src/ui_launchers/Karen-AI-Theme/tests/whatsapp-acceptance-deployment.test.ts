import { afterEach, describe, expect, it, vi } from 'vitest';
import type { APIRequestContext } from '@playwright/test';

import {
  requireWhatsAppAcceptanceTarget,
  verifyWhatsAppAcceptanceRevision,
} from '../e2e/fixtures/whatsapp-acceptance-deployment';

const REVISION = 'a'.repeat(40);
const ORIGIN = 'https://reviewed-karen.example';

afterEach(() => {
  vi.unstubAllEnvs();
});

function approvedEnvironment() {
  vi.stubEnv('KAREN_BASE_URL', ORIGIN);
  vi.stubEnv('KAREN_WHATSAPP_DEPLOYMENT_REVISION', REVISION);
}

function observer(status: number, payload: unknown) {
  const get = vi.fn().mockResolvedValue({
    status: () => status,
    json: async () => payload,
  });
  return { request: { get } as unknown as APIRequestContext, get };
}

describe('WhatsApp acceptance deployment authority', () => {
  it('requires explicit reviewed origin and exact SHA', () => {
    vi.stubEnv('KAREN_BASE_URL', '');
    vi.stubEnv('KAREN_WHATSAPP_DEPLOYMENT_REVISION', '');
    expect(() => requireWhatsAppAcceptanceTarget()).toThrow(
      'requires an approved HTTPS origin',
    );
    approvedEnvironment();
    expect(requireWhatsAppAcceptanceTarget()).toEqual({
      origin: ORIGIN, revision: REVISION,
    });
  });

  it.each([
    'http://reviewed-karen.example',
    'http://localhost:8010',
    'https://127.0.0.1',
    'https://10.1.1.1',
    'https://192.168.1.4',
    'https://karen.local',
    'https://localhost.example.internal',
    'https://reviewed-karen.example:8010',
    'https://reviewed-karen.example/path',
    'https://reviewed-karen.example/?debug=true',
    'https://name:password@reviewed-karen.example',
  ])('rejects an unapproved or secret-bearing URL form', (url) => {
    approvedEnvironment();
    vi.stubEnv('KAREN_BASE_URL', url);
    expect(() => requireWhatsAppAcceptanceTarget()).toThrow(
      'clean approved HTTPS origin',
    );
  });

  it('rejects an invalid requested SHA', () => {
    approvedEnvironment();
    vi.stubEnv('KAREN_WHATSAPP_DEPLOYMENT_REVISION', 'main');
    expect(() => requireWhatsAppAcceptanceTarget()).toThrow(
      'exact deployment revision',
    );
  });

  it('reads actual deployment revision before allowing the provider probe', async () => {
    approvedEnvironment();
    const { request, get } = observer(200, { revision: REVISION });
    await expect(verifyWhatsAppAcceptanceRevision(request)).resolves.toEqual({
      origin: ORIGIN, revision: REVISION,
    });
    expect(get).toHaveBeenCalledWith(
      ORIGIN + '/api/deployment-revision',
      { timeout: 20_000, maxRedirects: 0, failOnStatusCode: false },
    );
  });

  it.each([
    [200, { sha: 'b'.repeat(40) }],
    [200, { revision: REVISION, git_sha: 'b'.repeat(40) }],
    [200, { ok: true }],
    [200, 'unknown'],
    [302, { revision: REVISION }],
    [503, null],
  ])('fails closed for missing, contradictory or unavailable deployment evidence',
    async (status, payload) => {
      approvedEnvironment();
      const { request } = observer(status, payload);
      await expect(verifyWhatsAppAcceptanceRevision(request)).rejects.toThrow(
        'deployment revision',
      );
    });

  it('redacts transport exceptions instead of leaking an arbitrary URL', async () => {
    approvedEnvironment();
    const request = {
      get: vi.fn().mockRejectedValue(new Error('secret-bearing upstream URL')),
    } as unknown as APIRequestContext;
    await expect(verifyWhatsAppAcceptanceRevision(request)).rejects.toThrow(
      'deployment revision could not be verified',
    );
  });
});
