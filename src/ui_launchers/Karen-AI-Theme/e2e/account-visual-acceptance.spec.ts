import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * KUI-ACCOUNT real, sanitized local browser acceptance.
 * No intercepted auth/profile endpoints, no synthetic account data.
 * Opt in only with a dedicated sanitized identity. Screenshots and artifacts
 * can reveal account metadata: do not upload artifacts from a private account.
 */
const enabled = process.env.KAREN_ACCOUNT_VISUAL_ACCEPTANCE === 'true';
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
  colorScheme: 'dark',
});

async function authenticate(page: Page): Promise<void> {
  if (!email || !password) {
    throw new Error('Dedicated sanitized acceptance credentials are required.');
  }
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });
}

async function openAccount(page: Page): Promise<void> {
  const button = page.getByRole('button', { name: 'My Account', exact: true });
  if (!await button.first().isVisible()) {
    const toggle = page.locator('[data-sidebar="trigger"]').first();
    await expect(toggle).toBeVisible();
    await toggle.click();
  }
  await button.last().click();
  await expect(page.locator('.karen-account').first()).toBeVisible({ timeout: 30_000 });
}

test('KUI-ACCOUNT: actual profile, accessible controls and responsive surfaces', async ({
  page,
}, testInfo: TestInfo) => {
  test.skip(
    !enabled || !email || !password,
    'Run only against a healthy local service with a sanitized test identity.',
  );
  test.setTimeout(5 * 60_000);
  await page.setViewportSize(viewports[0]);
  await authenticate(page);

  const profileResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === 'GET' && url.pathname === '/api/auth/me';
  }, { timeout: 30_000 });
  await openAccount(page);
  expect((await profileResponse).ok(), 'Account must be verified by backend').toBe(true);

  const account = page.locator('.karen-account').first();
  await expect(account.getByRole('heading', { name: 'My Account' })).toBeVisible();
  await expect(account.getByRole('heading', { name: 'Profile information' })).toBeVisible();
  await expect(account.getByRole('heading', { name: 'Appearance' })).toBeVisible();
  await expect(account.getByRole('heading', { name: 'Account security' })).toBeVisible();
  await expect(account.getByRole('heading', { name: 'Active sessions' })).toBeVisible();

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    const geometry = await account.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
        panelLeft: rect.left,
        panelRight: rect.right,
        panelWidth: rect.width,
        cardCount: element.querySelectorAll('.karen-account-card').length,
      };
    });
    expect(geometry.cardCount).toBeGreaterThanOrEqual(5);
    expect(geometry.panelWidth).toBeGreaterThan(0);
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth + 1);
    expect(geometry.panelRight).toBeLessThanOrEqual(geometry.viewportWidth + 1);
    expect(geometry.panelLeft).toBeGreaterThanOrEqual(-1);

    const name = account.getByLabel('Display name', { exact: true });
    await name.focus();
    await expect(name).toBeFocused();
    await expect(account.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    await expect(account.getByRole('radiogroup', { name: 'Display theme' })).toBeVisible();

    await testInfo.attach(`account-sanitized-${viewport.width}x${viewport.height}`, {
      body: await account.screenshot({ animations: 'disabled' }),
      contentType: 'image/png',
    });
    await testInfo.attach(`account-geometry-${viewport.width}`, {
      body: Buffer.from(JSON.stringify({
        viewport,
        geometry,
        authenticated_backend: true,
        visual_parity_certified: false,
        revision: process.env.KAREN_UX_TARGET_REVISION || null,
      }, null, 2)),
      contentType: 'application/json',
    });
  }
});
