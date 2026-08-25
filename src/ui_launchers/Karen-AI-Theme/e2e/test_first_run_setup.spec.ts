import { test, expect } from '@playwright/test';

test.describe('first-run setup', () => {
  test('routes a fresh installation through readiness and owner creation', async ({ page }) => {
    await page.route('**/api/auth/first-run', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          first_run_required: true,
          message: 'First-run setup required',
        }),
      });
    });

    await page.route('**/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'healthy',
          connections: { database: { status: 'healthy' } },
        }),
      });
    });

    await page.route('**/api/auth/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'healthy' }),
      });
    });

    await page.route('**/api/auth/first-run/setup', async (route) => {
      const request = route.request();
      const payload = request.postDataJSON();

      expect(payload.email).toBe('owner@example.com');
      expect(payload.full_name).toBe('Karen Owner');
      expect(payload.password).toBe(payload.confirm_password);

      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'test-access-token',
          refresh_token: 'test-refresh-token',
          token_type: 'bearer',
          expires_in: 3600,
          user: {
            user_id: 'owner-1',
            email: 'owner@example.com',
            full_name: 'Karen Owner',
            roles: ['admin', 'user'],
            tenant_id: 'default',
            preferences: {},
          },
          permissions: ['admin:*'],
          message: 'First admin user created and authenticated successfully',
        }),
      });
    });

    await page.goto('/setup');

    await expect(page.getByRole('heading', { name: 'System check' })).toBeVisible();
    await expect(page.getByText('Karen API')).toBeVisible();
    await expect(page.getByText('Authentication')).toBeVisible();
    await expect(page.getByText('Database')).toBeVisible();

    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { name: 'Create the installation owner' })).toBeVisible();

    await page.getByLabel('Full name').fill('Karen Owner');
    await page.getByLabel('Email').fill('owner@example.com');
    await page.getByLabel('Password', { exact: true }).fill('StrongOwner!2026');
    await page.getByLabel('Confirm password').fill('StrongOwner!2026');

    await page.getByRole('button', { name: 'Create owner' }).click();

    await expect(page.getByRole('heading', { name: 'Karen is ready' })).toBeVisible();
    await expect(page.getByText('Installation owner created')).toBeVisible();

    await expect.poll(async () => page.evaluate(() => localStorage.getItem('access_token'))).toBe('test-access-token');
    await expect.poll(async () => page.evaluate(() => localStorage.getItem('kari_session_expected'))).toBe('true');
  });

  test('redirects configured installations away from setup', async ({ page }) => {
    await page.route('**/api/auth/first-run', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          first_run_required: false,
          message: 'System already configured',
        }),
      });
    });

    await page.goto('/setup');
    await expect(page).toHaveURL(/\/login/);
  });
});
