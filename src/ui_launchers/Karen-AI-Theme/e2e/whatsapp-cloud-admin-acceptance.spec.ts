import { expect, test } from '@playwright/test';
import { signInApprovedKaren } from './fixtures/approved-karen-login';
import { verifyWhatsAppAcceptanceRevision } from './fixtures/whatsapp-acceptance-deployment';

/**
 * KWA-01C6C1: real signed-in operator browser acceptance.
 *
 * Uses an approved, sanitized deployment and Karen's actual tenant-scoped API.
 * This is intentionally read-only: it must not provision, activate or send
 * messages, and it cannot certify Meta webhook or delivery behavior.
 * Never record credentials, tenant inventory, screenshots or browser storage.
 */
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

const required = process.env.KAREN_WHATSAPP_ADMIN_ACCEPTANCE_REQUIRED === 'true';
const endpoint = '/api/channels/operator/whatsapp/connections';
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Connection = {
  connection_id: string;
  connection_revision: number;
  enabled: boolean;
};

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/** Validate actual API shape without exposing any returned data in assertion logs. */
function readInventory(value: unknown): Connection[] | null {
  if (!isObject(value) || Object.keys(value).length !== 1 ||
      !Array.isArray(value.connections) || value.connections.length > 50) {
    return null;
  }
  const seen = new Set<string>();
  const verified: Connection[] = [];
  for (const raw of value.connections) {
    if (!isObject(raw) ||
        Object.keys(raw).length !== 3 ||
        typeof raw.connection_id !== 'string' ||
        !uuidPattern.test(raw.connection_id) ||
        seen.has(raw.connection_id) ||
        typeof raw.connection_revision !== 'number' ||
        !Number.isSafeInteger(raw.connection_revision) ||
        raw.connection_revision < 1 ||
        typeof raw.enabled !== 'boolean') {
      return null;
    }
    seen.add(raw.connection_id);
    verified.push({
      connection_id: raw.connection_id,
      connection_revision: raw.connection_revision,
      enabled: raw.enabled,
    });
  }
  return verified;
}

for (const width of [390, 768, 1440]) {
  test(`KWA-01C6C1 admin operator inventory at ${width}px is reachable and honest`, async ({ page }) => {
    test.skip(!required, 'Requires explicit real-deployment WhatsApp admin acceptance opt-in');

    const email = process.env.KAREN_UX_EMAIL;
    const password = process.env.KAREN_UX_PASSWORD;
    if (!email || !password) {
      throw new Error('Approved sanitized operator credentials are required');
    }

    await page.setViewportSize({ width, height: 900 });
    const unauthorizedWrites: string[] = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith('/api/channels/operator/whatsapp/') &&
          request.method() !== 'GET' && request.method() !== 'HEAD') {
        unauthorizedWrites.push(request.method());
      }
    });

    // The local UI check must be bound to the same exact reviewed deploy
    // as the separately observed provider-facing callback trial.
    await verifyWhatsAppAcceptanceRevision(page.request);
    await signInApprovedKaren(page, email, password);
    const adminLink = page.getByRole('link', { name: 'Admin settings', exact: true });
    if (!(await adminLink.isVisible())) {
      await page.locator('[data-sidebar="trigger"]').first().click();
    }
    await expect(adminLink).toBeVisible();
    await adminLink.click();
    await expect(page).toHaveURL(/\/admin(?:[/?#]|$)/);
    const tab = page.getByRole('tab', { name: 'WhatsApp Cloud', exact: true });
    await expect(tab).toBeVisible();

    // Bind observation to the real response triggered by opening this tab.
    const responsePromise = page.waitForResponse((response) =>
      new URL(response.url()).pathname === endpoint &&
      response.request().method() === 'GET', { timeout: 30_000 });
    await tab.click();
    const response = await responsePromise;
    expect(response.status(), 'Authenticated channel.inspect must succeed').toBe(200);
    const inventory = readInventory(await response.json() as unknown);
    expect(inventory !== null, 'Only redacted canonical inventory is acceptable').toBe(true);
    if (!inventory) return;

    const panel = page.getByRole('heading', { name: 'WhatsApp Cloud operator setup' });
    await expect(panel).toBeVisible();
    await panel.scrollIntoViewIfNeeded();
    await expect(panel).toBeInViewport();
    await expect(page.getByText(
      'Persisted Karen state only, not a live Meta webhook or delivery health check.',
      { exact: true },
    )).toBeVisible();
    const phoneInput = page.getByLabel('Meta phone-number ID');
    const handleInput = page.getByLabel('Existing Vault credential handle');
    await phoneInput.scrollIntoViewIfNeeded();
    await expect(phoneInput).toBeInViewport();
    await handleInput.scrollIntoViewIfNeeded();
    await expect(handleInput).toBeInViewport();
    await expect(page.getByRole('button', { name: 'Provision disabled account' }))
      .toBeDisabled();

    if (inventory.length === 0) {
      await expect(page.getByText(
        'No WhatsApp Cloud connections found for this tenant.',
        { exact: true },
      )).toBeVisible();
    } else {
      // DOM matching is scoped to the actual bounded backend IDs. No phone
      // numbers, credential handles, or IDs are emitted into artifacts.
      for (const connection of inventory) {
        await expect(page.getByText(connection.connection_id, { exact: true }))
          .toBeVisible();
      }
      expect(await page.getByRole('button', { name: 'Activate connection' }).count())
        .toBe(inventory.filter((item) => !item.enabled).length);
      expect(await page.getByRole('button', { name: 'Deactivate connection' }).count())
        .toBe(inventory.filter((item) => item.enabled).length);
    }

    expect(unauthorizedWrites, 'Read-only observation must not change a channel')
      .toEqual([]);
  });
}
