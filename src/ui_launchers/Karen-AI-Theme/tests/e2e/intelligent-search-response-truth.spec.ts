import { expect, test } from '@playwright/test';

test('automatic search displays backend-selected mode and marks evidence as unverified', async ({ page }) => {
  await page.route('**/api/plugins/execute', async (route) => {
    const request = route.request().postDataJSON();
    expect(request.parameters.mode).toBeUndefined();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          mode: 'general',
          query: 'sample query',
          summary: 'Retrieved information from the original source',
          sources: [{
            id: 'sample-source',
            title: 'Example evidence',
            url: 'https://example.org/research',
            snippet: 'Original retrieved passage',
          }],
          results: [],
        },
      }),
    });
  });
  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('sample query');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByText('Source summaries and excerpts are not verified AI-generated answers.')).toBeVisible();
  await expect(page.getByText('Retrieved information from the original source').first()).toBeVisible();
});

test('a failed backend observation does not masquerade as a successful empty search', async ({ page }) => {
  await page.route('**/api/plugins/execute', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          mode: 'weather',
          status: 'error',
          provider: 'open_meteo',
          sources: [],
          results: [],
          metadata: { degraded: true },
        },
      }),
    });
  });
  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('weather in Detroit');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('The requested search capability is unavailable');
  await expect(page.getByText('No sources found')).not.toBeVisible();
});
