import { randomInt } from 'node:crypto';

import { expect, test, type APIRequestContext, type APIResponse } from '@playwright/test';
import {
  verifyWhatsAppAcceptanceRevision,
} from './fixtures/whatsapp-acceptance-deployment';

/**
 * KWA-01C6C2A: live, public-HTTPS host challenge acceptance.
 *
 * No simulated adapter, test route, browser secret persistence, screenshot,
 * video or trace. These are operator-originated GETs against the *real host*.
 * Passing does NOT prove Meta itself subscribed or sent a signed callback.
 */
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
test.setTimeout(90_000);

const enabled = process.env.KAREN_WHATSAPP_WEBHOOK_HANDSHAKE_REQUIRED === 'true';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type CallbackTarget = Readonly<{ path: string; verifyToken: string }>;

function requireCallbackTarget(): CallbackTarget {
  const tenantId = process.env.KAREN_WHATSAPP_ACCEPTANCE_TENANT_ID;
  const connectionId = process.env.KAREN_WHATSAPP_ACCEPTANCE_CONNECTION_ID;
  const token = process.env.KAREN_WHATSAPP_ACCEPTANCE_VERIFY_TOKEN;

  if (!tenantId || !connectionId || !UUID.test(tenantId) ||
      !UUID.test(connectionId) || !token || token.length < 8 ||
      token.length > 256 || [...token].some((char) =>
        char.charCodeAt(0) < 33 || char.charCodeAt(0) > 126)) {
    throw new Error('WhatsApp callback acceptance requires a scoped UUID pair and approved Vault verify token');
  }
  return {
    path: `/api/channels/webhooks/${tenantId}/${connectionId}`,
    verifyToken: token,
  };
}

async function probeCallback(
  request: APIRequestContext,
  origin: string,
  path: string,
  challenge: string,
  token: string | null,
  mode: string,
): Promise<APIResponse> {
  const url = new URL(path, origin);
  url.searchParams.set('hub.mode', mode);
  url.searchParams.set('hub.challenge', challenge);
  if (token !== null) {
    url.searchParams.set('hub.verify_token', token);
  }
  try {
    // Avoid Playwright's default HTTP failure exception because a rejected
    // token is expected. Never include a secret-bearing URL in any error.
    return await request.get(url.toString(), {
      maxRedirects: 0,
      failOnStatusCode: false,
      timeout: 20_000,
    });
  } catch {
    throw new Error('WhatsApp host challenge probe failed without an observed HTTP response');
  }
}

test('KWA-01C6C2A: exact deployed host accepts only Vault-bound callback challenge', async ({
  request,
}) => {
  test.skip(!enabled, 'Requires explicitly approved live HTTPS WhatsApp callback trial');

  const target = await verifyWhatsAppAcceptanceRevision(request);
  const callback = requireCallbackTarget();
  const challenge = String(randomInt(1_000_000_000, 2_147_483_647));

  const valid = await probeCallback(
    request, target.origin, callback.path, challenge, callback.verifyToken, 'subscribe',
  );
  expect(valid.status(), 'The actual installed and enabled host must approve this token')
    .toBe(200);
  expect(await valid.text(), 'The host must echo the exact numeric challenge')
    .toBe(challenge);
  expect(valid.headers()['cache-control'], 'Provider verification challenge must not be cached')
    .toContain('no-store');

  // A distinct well-formed token is required to exercise HMAC denial rather
  // than only input-shape rejection. No token value enters test artifacts.
  const last = callback.verifyToken.slice(-1);
  const rejectedToken = callback.verifyToken.slice(0, -1) + (last === 'z' ? 'y' : 'z');
  const invalid = await probeCallback(
    request, target.origin, callback.path, challenge, rejectedToken, 'subscribe',
  );
  expect(invalid.status(), 'An invalid token must not authorize a challenge').toBe(403);

  const missing = await probeCallback(
    request, target.origin, callback.path, challenge, null, 'subscribe',
  );
  expect(missing.status(), 'Missing verify-token is denied').toBe(403);

  const wrongMode = await probeCallback(
    request, target.origin, callback.path, challenge, callback.verifyToken, 'unsubscribe',
  );
  expect(wrongMode.status(), 'Only subscribe mode may receive a challenge').toBe(403);

  // This only proves the live host's unauthenticated GET challenge behavior.
  // A separate real Meta-side subscription and signed POST/receipt transcript
  // remains mandatory for provider-observed, consumer-ready certification.
});
