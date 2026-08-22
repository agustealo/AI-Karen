import { expect, test, type Page } from '@playwright/test';

const BASE_URL = process.env.KAREN_BASE_URL || 'http://localhost:8010';
const LOGIN_EMAIL = 'admin@kari.ai';
const LOGIN_PASSWORD = 'Admin@123!';

async function login(page: Page) {
  await page.goto(BASE_URL);
  await page.waitForSelector('input[type="email"], input[name="email"]', { timeout: 15000 });
  await page.fill('input[type="email"], input[name="email"]', LOGIN_EMAIL);
  await page.fill('input[type="password"], input[name="password"]', LOGIN_PASSWORD);
  await page.locator('button[type="submit"]:not(:disabled)').first().click();

  try {
    await page.waitForURL(/\/dashboard/, { timeout: 15000 });
  } catch {
    if (!page.url().includes('/dashboard')) {
      throw new Error('Login did not reach dashboard');
    }
  }

  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(2000);
}

test.describe('No active cloud providers', () => {
  test('Model Settings shows an explicit empty cloud state when no cloud providers are active', async ({
    page,
  }) => {
    await login(page);

    await page.reload();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1500);

    const settingsButton = page.locator('button[aria-label="Open model and provider settings"]');
    await expect(settingsButton.first()).toBeVisible();
    await settingsButton.first().click();

    await expect(page.getByText('AI Provider Settings')).toBeVisible();
    await expect(
      page.getByText('No active cloud providers are configured. Built-in runtimes are still available.'),
    ).toBeVisible();

    await page.keyboard.press('Escape');
  });
});
