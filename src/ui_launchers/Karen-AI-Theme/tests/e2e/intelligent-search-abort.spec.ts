import { expect, test } from '@playwright/test';

test('cancelling search aborts the browser request and ignores late results', async ({ page }) => {
  let requestStarted!: () => void;
  const started = new Promise<void>((resolve) => { requestStarted = resolve; });
  let requestFailed!: (reason: string) => void;
  const failed = new Promise<string>((resolve) => { requestFailed = resolve; });

  page.on('requestfailed', (request) => {
    if (request.url().includes('/api/plugins/execute')) {
      requestFailed(request.failure()?.errorText ?? 'unknown');
    }
  });

  await page.route('**/api/plugins/execute', async (route) => {
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
  const failureReason = await Promise.race([
    failed,
    new Promise<string>((_, reject) => setTimeout(() => reject(new Error('Search HTTP request was not aborted')), 2500)),
  ]);
  expect(failureReason).toMatch(/abort|cancel|ERR_FAILED/i);
  await expect(page.getByRole('button', { name: 'Cancel search' })).not.toBeVisible();
});
