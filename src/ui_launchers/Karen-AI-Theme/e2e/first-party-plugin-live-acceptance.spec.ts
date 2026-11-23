import { expect, test, type Page } from '@playwright/test';
import { signInApprovedKaren } from './fixtures/approved-karen-login';

/**
 * Protected real-host acceptance for the three first-party plugin UIs.
 * No route mocks, lifecycle changes, content mutations or credential artifacts.
 */
const enabled = process.env.KAREN_PLUGIN_SURFACES_ACCEPTANCE === 'true';
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const plugins = [
  { id: 'file-explorer', label: 'File Explorer' },
  { id: 'intelligent-search', label: 'Intelligent Search' },
  { id: 'time-query', label: 'Time Query' },
] as const;
const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;
const activeStates = new Set(['active', 'registered', 'enabled', 'loaded']);

type CatalogEntry = {
  name: string;
  version: string;
  status: string;
  capabilities?: { provides_ui?: boolean };
};

test.use({ trace: 'off', screenshot: 'off', video: 'off' });

function approvedOrigin(): URL {
  const raw = process.env.KAREN_BASE_URL;
  if (!raw) throw new Error('Approved plugin deployment URL is required');
  const url = new URL(raw);
  if (
    url.protocol !== 'https:' || url.port ||
    url.username || url.password || url.pathname !== '/' ||
    url.search || url.hash
  ) {
    throw new Error('Plugin acceptance requires an exact approved HTTPS origin');
  }
  return url;
}

function catalogEntries(raw: unknown): CatalogEntry[] {
  const wrapper = raw !== null && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown> : null;
  const nested = wrapper?.data !== null && typeof wrapper?.data === 'object'
    ? wrapper?.data as Record<string, unknown> : null;
  const items = Array.isArray(raw)
    ? raw : wrapper?.plugins ?? wrapper?.extensions ?? nested?.plugins;
  if (!Array.isArray(items) || !items.every((entry): entry is CatalogEntry =>
    entry !== null && typeof entry === 'object' &&
    typeof entry.name === 'string' && entry.name.length > 0 &&
    typeof entry.version === 'string' && entry.version.length > 0 &&
    typeof entry.status === 'string' && entry.status.length > 0
  )) {
    throw new Error('Backend plugin catalog violates its response contract');
  }
  return items;
}

async function openOverview(page: Page) {
  const navigation = page.getByRole('button', { name: 'Tools & plugins', exact: true }).last();
  if (!(await navigation.isVisible().catch(() => false))) {
    await page.locator('[data-sidebar="trigger"]').first().click();
  }
  await expect(navigation).toBeVisible();
  await navigation.click();
  await expect(page.getByTestId('plugins-overview')).toBeVisible();
}

async function openAdvanced(page: Page) {
  const control = page.getByRole('button', { name: 'Advanced tools', exact: true }).last();
  if (!(await control.isVisible().catch(() => false))) {
    await page.locator('[data-sidebar="trigger"]').first().click();
  }
  await expect(control).toBeVisible();
  if ((await control.getAttribute('aria-expanded')) !== 'true') {
    await control.click();
  }
}

test('KPLUG-LIVE: authenticated registry, real UI mounts, guest denial and responsive layouts', async ({ page }) => {
  test.skip(!enabled, 'Requires protected plugin-surfaces workflow dispatch');
  test.setTimeout(6 * 60_000);
  if (!email || !password) throw new Error('Dedicated sanitized acceptance credentials required');
  const origin = approvedOrigin();

  await page.setViewportSize(viewports[0]);
  const pendingCatalog = page.waitForResponse((candidate) => {
    const url = new URL(candidate.url());
    return url.origin === origin.origin &&
      url.pathname === '/api/extensions/list' &&
      candidate.request().method() === 'GET';
  }, { timeout: 45_000 });
  await signInApprovedKaren(page, email, password);
  expect(new URL(page.url()).origin).toBe(origin.origin);
  const response = await pendingCatalog;
  expect(response.status(), 'Live backend catalog must return authenticated HTTP 200').toBe(200);
  const registry = catalogEntries(await response.json());

  for (const plugin of plugins) {
    const found = registry.filter((entry) => entry.name === plugin.id);
    expect(found, 'Missing or duplicated canonical plugin: ' + plugin.id).toHaveLength(1);
    expect(found[0].capabilities?.provides_ui).toBe(true);
  }

  // Use a separate cookie-less browser context, never a cleared or forged
  // authenticated session. The static import map cannot grant catalog access.
  const browser = page.context().browser();
  if (!browser) throw new Error('Isolated browser context unavailable');
  const guest = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    const denied = await guest.request.get(
      new URL('/api/extensions/list', origin).toString(),
      { maxRedirects: 0 },
    );
    expect([401, 403], 'Unauthenticated extension discovery must be denied').toContain(denied.status());
  } finally {
    await guest.close();
  }

  // A deployment with every first-party plugin disabled cannot prove real UI
  // mounting. Preserve disabled-state coverage without allowing a vacuous pass.
  const enabledFirstParty = plugins.filter((plugin) => registry.some(
    (entry) => entry.name === plugin.id && activeStates.has(entry.status),
  ));
  expect(enabledFirstParty.length, 'No enabled first-party UI to exercise on this host').toBeGreaterThan(0);

  await openOverview(page);
  const overview = page.getByTestId('plugins-overview');
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    await expect(overview).toBeVisible();
    const geometry = await overview.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      };
    });
    expect(geometry.left).toBeGreaterThanOrEqual(-1);
    expect(geometry.right).toBeLessThanOrEqual(geometry.width + 1);
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
    for (const plugin of plugins) {
      const heading = overview.getByRole('heading', { name: new RegExp('^' + plugin.label + ' v') });
      await expect(heading, 'Missing visible plugin overview: ' + plugin.id).toHaveCount(1);
    }
  }

  await page.setViewportSize(viewports[0]);
  for (const plugin of plugins) {
    await openAdvanced(page);
    const status = registry.find((entry) => entry.name === plugin.id)?.status;
    if (!status) throw new Error('Verified registry state disappeared');
    const item = page.getByRole('button', { name: plugin.label, exact: true }).last();
    if (!activeStates.has(status)) {
      await expect(item, 'Disabled UI may not be offered as executable').toHaveCount(0);
      continue;
    }

    await expect(item, 'Enabled first-party UI must be navigable').toBeVisible();
    if (plugin.id === 'file-explorer') {
      const pendingInventory = page.waitForResponse((candidate) => {
        const url = new URL(candidate.url());
        return url.origin === origin.origin &&
          url.pathname === '/api/plugins/file-explorer/inventory' &&
          candidate.request().method() === 'GET';
      }, { timeout: 45_000 });
      await item.click();
      await expect(page.getByRole('region', { name: 'Shared File Explorer' })).toBeVisible();
      expect((await pendingInventory).status(), 'Owner inventory must authorize HTTP 200').toBe(200);
    } else if (plugin.id === 'intelligent-search') {
      await item.click();
      await expect(page.getByRole('heading', { name: 'Live web results' })).toBeVisible();
      await expect(page.getByLabel('Query', { exact: true })).toBeVisible();
    } else {
      await item.click();
      await expect(page.getByRole('heading', { name: 'System Time Details' })).toBeVisible({ timeout: 45_000 });
      await expect(page.getByRole('heading', { name: 'World Time Lookup' })).toBeVisible();
    }

    await expect(page.getByText('No UI registered for plugin ' + plugin.id)).toHaveCount(0);
    await page.setViewportSize(viewports[3]);
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await page.setViewportSize(viewports[0]);
  }
});
