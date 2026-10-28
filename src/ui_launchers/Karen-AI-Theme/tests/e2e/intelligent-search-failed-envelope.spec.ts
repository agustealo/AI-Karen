import { expect, test } from '@playwright/test';

test('failed plugin execution with result-shaped diagnostics is not shown as successful evidence', async ({ page }) => {
  await page.route('**/api/plugins/execute', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: false,
        message: 'Search provider is unavailable',
        result: {
          summary: 'This text must not be rendered as a successful search',
          sources: [{
            id: 'invalid-evidence',
            title: 'Unverified result',
            url: 'https://example.org/unverified',
            snippet: 'Not verified',
          }],
        },
      }),
    });
  });

  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('research test');
  await page.getByRole('button', { name: 'Search', exact: true }).click();

  await expect(page.getByText('Search provider is unavailable')).toBeVisible();
  await expect(page.getByText('This text must not be rendered as a successful search')).not.toBeVisible();
  await expect(page.getByText('Unverified result')).not.toBeVisible();
});
