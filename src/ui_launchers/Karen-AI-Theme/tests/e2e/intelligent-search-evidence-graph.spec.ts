import { expect, test } from '@playwright/test';

test('evidence graph is available only for server-supplied provenance and remains navigable', async ({ page }) => {
  await page.route('**/api/plugins/execute', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          mode: 'general',
          query: 'Jamaican history',
          summary: 'Retrieved historical evidence',
          sources: [{
            id: 'source_0', url: 'https://example.org/history',
            title: 'Historical source', snippet: 'Historical evidence',
            evidence_level: 'fetched_page',
          }],
          results: [],
          evidenceGraph: {
            version: 1, kind: 'retrieval_evidence', status: 'available',
            truncated: false,
            nodes: [{
              id: 'source_123', kind: 'source', label: 'Historical source',
              url: 'https://example.org/history', evidence_level: 'fetched_page',
            }],
            edges: [],
          },
        },
      }),
    });
  });

  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('Jamaican history');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: 'Show Graph search information' }).click();
  await expect(page.getByRole('region', { name: 'Evidence relationship explorer' })).toBeVisible();
  await page.getByRole('button', { name: /source · Fetched Historical source/ }).click();
  await expect(page.getByRole('complementary', { name: 'Selected evidence details' })).toContainText('Fetched-page provenance');
  await expect(page.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', 'https://example.org/history');
});

test('legacy search responses do not fabricate graph view', async ({ page }) => {
  await page.route('**/api/plugins/execute', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          query: 'Jamaican history', mode: 'general',
          summary: 'Source information', sources: [{
            id: 's', url: 'https://example.org/history', title: 'Historical source',
          }], results: [],
        },
      }),
    });
  });
  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('Jamaican history');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByText('Source information').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Show Graph search information' })).toHaveCount(0);
});
