import { expect, test } from '@playwright/test';

test('cancelling search aborts the browser request and ignores late results', async ({ page }) => {
  let requestStarted!: () => void;
  const started = new Promise<void>((resolve) => { requestStarted = resolve; });
  let requestFailed!: () => void;
  const failed = new Promise<void>((resolve) => { requestFailed = resolve; });

  await page.route('**/api/plugins/execute', async (route) => {
    route.request().on('requestfailed', () => requestFailed());
    requestStarted();
    // Keep the mocked transport in flight long enough for the cancel action.
    await new Promise<void>((resolve) => setTimeout(resolve, 1500));
    try {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          result: { summary: 'Cancelled result must not render', sources: [], results: [] },
        }),
      });
    } catch {
      // The browser may have aborted its side of the mocked request.
    }
  });

  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('search cancellation');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await started;
  await page.getByRole('button', { name: 'Cancel search' }).click();
  await expect(page.getByText('Cancelled result must not render')).not.toBeVisible();
  await Promise.race([failed, new Promise<void>(resolve => setTimeout(resolve, 2500))]);
  await expect(page.getByRole('button', { name: 'Cancel search' })).not.toBeVisible();
});
