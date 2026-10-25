import { expect, test } from '@playwright/test';

test('editing advanced search settings preserves completed source evidence until another search runs', async ({ page }) => {
  let requestCount = 0;
  await page.route('**/api/plugins/execute', async (route) => {
    requestCount += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          query: 'Jamaican history',
          summary: 'Source evidence for Jamaican history',
          sources: [
            {
              id: 'history-source',
              title: 'History source',
              url: 'https://example.org/history',
              snippet: 'Evidence about Jamaican history',
            },
          ],
          results: [],
        },
      }),
    });
  });

  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('Jamaican history');
  await page.getByRole('button', { name: 'Search', exact: true }).click();

  await expect(page.getByText('Source evidence for Jamaican history')).toBeVisible();
  await page.getByRole('button', { name: 'Search settings' }).click();
  await page.getByRole('textbox', { name: 'Max URLs' }).fill('6');

  await expect(page.getByText('Source evidence for Jamaican history')).toBeVisible();
  expect(requestCount).toBe(1);

  await page.getByRole('button', { name: 'Update results' }).click();
  await expect.poll(() => requestCount).toBe(2);
  await expect(page.getByText('Source evidence for Jamaican history')).toBeVisible();
});
