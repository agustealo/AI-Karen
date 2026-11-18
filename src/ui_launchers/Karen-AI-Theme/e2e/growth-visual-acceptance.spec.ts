import { expect, test, type Page, type TestInfo } from '@playwright/test';

/**
 * KUI-GROWTH live visual/interaction acceptance.
 *
 * Opt-in only. Uses a dedicated sanitized user and the real /api/progress/
 * endpoint. No route interception, mock receipts, synthetic scores, or
 * authenticated screenshots from private accounts.
 *
 * KAREN_GROWTH_VISUAL_ACCEPTANCE=true
 * KAREN_UX_EMAIL=... KAREN_UX_PASSWORD=...
 * KAREN_BASE_URL=https://approved-sanitized-target
 *
 * Compare captured screenshots with the approved KUI-CHAT-001 reference.
 * This suite checks measurable layout invariants but does NOT certify pixel
 * parity or backend persistence by itself.
 */
const enabled = process.env.KAREN_GROWTH_VISUAL_ACCEPTANCE === 'true';
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

// The suite intentionally suppresses traces/videos: they can contain login
// input, tokens, or private response bodies. Screenshot export is limited to
// the explicit dedicated sanitized visual account.
test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
  colorScheme: 'dark',
});

async function signIn(page: Page): Promise<void> {
  if (!email || !password) {
    throw new Error('Sanitized Growth acceptance credentials are required.');
  }
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });
  await expect(page.getByTestId('workspace-scroll-region')).toBeAttached({
    timeout: 30_000,
  });
}

async function openGrowth(page: Page): Promise<void> {
  const growthNavigation = page.getByRole('button', { name: 'Growth', exact: true });
  if (!await growthNavigation.isVisible()) {
    const sidebarTrigger = page.locator('[data-sidebar="trigger"]').first();
    await expect(sidebarTrigger).toBeVisible();
    await sidebarTrigger.click();
  }
  const navigation = page.getByRole('button', { name: 'Growth', exact: true }).last();
  await expect(navigation).toBeVisible();
  await navigation.click();
  await expect(page.locator('.karen-growth').first()).toBeVisible({
    timeout: 30_000,
  });
}

test('KUI-GROWTH: real evidence, responsive hierarchy, and keyboard controls', async ({
  page,
}, testInfo: TestInfo) => {
  test.skip(
    !enabled || !email || !password,
    'Requires opt-in sanitized authenticated installation and real Growth API.',
  );
  test.setTimeout(5 * 60_000);

  await page.setViewportSize(viewports[0]);
  await signIn(page);

  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === 'GET' &&
      /^\/api\/progress\/?$/.test(url.pathname);
  }, { timeout: 30_000 });

  await openGrowth(page);
  const progressResponse = await responsePromise;
  expect(progressResponse.ok(), 'Growth must load from the real service').toBe(true);
  const record: unknown = await progressResponse.json();
  expect(record).toBeTruthy();
  if (!record || typeof record !== 'object' ||
      !('progress_index' in record) || typeof record.progress_index !== 'number' ||
      !('milestones' in record) || !Array.isArray(record.milestones)) {
    throw new Error('Canonical Growth response does not satisfy the display contract.');
  }

  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    const panel = page.locator('.karen-growth').first();
    const heading = panel.getByRole('heading', { name: 'Growth', exact: true });
    await expect(heading).toBeVisible();
    await expect(panel.getByRole('heading', { name: 'Evidence quality' })).toBeVisible();
    await expect(panel.getByRole('heading', { name: 'Milestones' })).toBeVisible();
    await expect(panel.getByRole('heading', { name: 'Evidence ledger' })).toBeVisible();

    const dimensions = panel.locator('section[aria-labelledby="growth-dimensions"]');
    await expect(dimensions).toBeVisible();
    await expect(dimensions.locator('[role="progressbar"]')).toHaveCount(6);
    await expect(panel.getByRole('progressbar', { name: 'Growth progress index' })).toBeVisible();

    // Any overflow in an individually scrollable dashboard card is a layout
    // defect, as is a horizontally overflowing document viewport.
    const geometry = await page.evaluate(() => {
      const main = document.querySelector('.karen-growth');
      const hero = document.querySelector('.karen-growth-hero');
      if (!main || !hero) return null;
      const rect = main.getBoundingClientRect();
      const heroRect = hero.getBoundingClientRect();
      const viewportWidth = document.documentElement.clientWidth;
      return {
        viewportWidth,
        documentWidth: document.documentElement.scrollWidth,
        mainWidth: rect.width,
        heroWidth: heroRect.width,
        heroLeft: heroRect.left,
        heroRight: heroRect.right,
      };
    });
    expect(geometry).not.toBeNull();
    if (!geometry) throw new Error('Growth geometry is missing');
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth + 1);
    expect(geometry.heroWidth).toBeGreaterThan(0);
    expect(geometry.heroRight).toBeLessThanOrEqual(geometry.viewportWidth + 1);
    expect(geometry.heroLeft).toBeGreaterThanOrEqual(-1);

    const refresh = panel.getByRole('button', { name: 'Refresh Growth evidence' });
    await expect(refresh).toBeVisible();
    await refresh.focus();
    await expect(refresh).toBeFocused();
    await expect(refresh).toBeEnabled();

    await testInfo.attach(`growth-live-${viewport.width}x${viewport.height}`, {
      body: await panel.screenshot({ animations: 'disabled' }),
      contentType: 'image/png',
    });
    await testInfo.attach(`growth-layout-${viewport.width}`, {
      body: Buffer.from(JSON.stringify({
        viewport,
        geometry,
        source: 'authenticated_live_progress',
        policy: 'live API response',
        actual_progress_index: record.progress_index,
        timestamp: new Date().toISOString(),
        revision: process.env.KAREN_UX_TARGET_REVISION || null,
        visual_parity_certified: false,
      }, null, 2)),
      contentType: 'application/json',
    });
  }
});
