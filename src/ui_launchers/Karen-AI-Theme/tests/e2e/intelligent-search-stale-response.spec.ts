import { test, expect } from '@playwright/test';

test('cancelled Intelligent Search does not display late response', async ({ page }) => {
  let releaseResponse: (() => void) | undefined;
  const pending = new Promise<void>(resolve => { releaseResponse = resolve; });
  let capturedRequest: (() => void) | undefined;
  const requested = new Promise<void>(resolve => { capturedRequest = resolve; });

  await page.route('**/api/plugins/execute', async route => {
    capturedRequest?.();
    await pending;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          query: 'Jamaican History',
          summary: 'Stale response must not appear',
          sources: [{
            id: 'source-1',
            title: 'Stale article',
            url: 'https://example.org/history',
            snippet: 'Old search result',
          }],
          results: [],
        },
      }),
    });
  });

  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('Jamaican History');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await requested;
  await page.getByRole('button', { name: 'Cancel search' }).click();
  releaseResponse?.();
  await expect(page.getByText('Stale response must not appear')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Cancel search' })).not.toBeVisible();
});
