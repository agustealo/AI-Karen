import type { APIRequestContext } from '@playwright/test';

/**
 * KWA-01C6C2A: shared deployment gate for real WhatsApp acceptance tests.
 *
 * The operator explicitly chooses a reviewed HTTPS origin and exact source
 * revision. The running backend must independently report the same revision.
 * This is a deployment identity check, not Meta or provider delivery evidence.
 */
const SHA = /^[0-9a-f]{40}$/i;

type Target = Readonly<{ origin: string; revision: string }>;

function isNonPublicHost(host: string): boolean {
  const name = host.toLowerCase().replace(/\.$/, '');
  if (name === 'localhost' || name.endsWith('.localhost') ||
      name.endsWith('.local') || name.endsWith('.internal') ||
      name === '[::1]' || name === '[::]') {
    return true;
  }

  // The HTTP probe must never leak a Vault verify token to loopback, link-local
  // or RFC1918 infrastructure even if its URL happens to use TLS.
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(name);
  if (!ipv4) return false;
  const octets = ipv4.slice(1).map(Number);
  const [first, second] = octets;
  return octets.some((part) => part > 255) ||
    first === 0 || first === 10 || first === 127 ||
    (first === 100 && second >= 64 && second <= 127) ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168);
}

export function requireWhatsAppAcceptanceTarget(): Target {
  const configured = process.env.KAREN_BASE_URL;
  const revision = process.env.KAREN_WHATSAPP_DEPLOYMENT_REVISION;

  if (!configured || !revision || !SHA.test(revision)) {
    throw new Error('WhatsApp acceptance requires an approved HTTPS origin and exact deployment revision');
  }

  let url: URL;
  try {
    url = new URL(configured);
  } catch {
    throw new Error('WhatsApp acceptance origin is invalid');
  }

  if (
    url.protocol !== 'https:' || url.port !== '' ||
    !url.hostname || isNonPublicHost(url.hostname) ||
    url.username !== '' || url.password !== '' ||
    url.pathname !== '/' || url.search !== '' || url.hash !== ''
  ) {
    throw new Error('WhatsApp acceptance requires a clean approved HTTPS origin');
  }

  return { origin: url.origin, revision };
}

export async function verifyWhatsAppAcceptanceRevision(
  request: APIRequestContext,
): Promise<Target> {
  const target = requireWhatsAppAcceptanceTarget();
  let body: unknown;
  try {
    const response = await request.get(
      new URL('/api/deployment-revision', target.origin).toString(),
      { timeout: 20_000, maxRedirects: 0, failOnStatusCode: false },
    );
    if (response.status() !== 200) {
      throw new Error('Deployment revision was unavailable');
    }
    body = await response.json() as unknown;
  } catch {
    throw new Error('WhatsApp acceptance deployment revision could not be verified');
  }

  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new Error('WhatsApp acceptance deployment revision was malformed');
  }
  const record = body as Record<string, unknown>;
  const values = ['revision', 'sha', 'commit_sha', 'git_sha']
    .filter((key) => record[key] !== undefined)
    .map((key) => record[key]);
  if (values.length === 0 || !values.every((value) => value === target.revision)) {
    throw new Error('WhatsApp acceptance deployment revision does not match reviewed source');
  }
  return target;
}
