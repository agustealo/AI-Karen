import { expect, test } from '@playwright/test';

test('editing query and mode keeps prior evidence visibly marked as previous until rerun', async ({ page }) => {
  let requestCount = 0;

  await page.route('**/api/plugins/execute', async (route) => {
    requestCount += 1;
    const isFirst = requestCount === 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          query: isFirst ? 'Jamaican history' : 'Caribbean trade',
          mode: isFirst ? 'general' : 'news',
          summary: isFirst ? 'Earlier history evidence' : 'Updated trade evidence',
          sources: [{
            id: isFirst ? 'history-source' : 'trade-source',
            title: isFirst ? 'Historical source' : 'Trade source',
            url: isFirst ? 'https://example.org/history' : 'https://example.org/trade',
            snippet: isFirst ? 'Older source excerpt' : 'New source excerpt',
          }],
          results: [],
        },
      }),
    });
  });

  await page.goto('/plugins/intelligent-search');
  const query = page.getByRole('textbox', { name: 'Query' });
  await query.fill('Jamaican history');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByText('Earlier history evidence').first()).toBeVisible();

  await query.fill('Caribbean trade');
  await page.getByRole('combobox', { name: 'Search mode' }).selectOption('news');

  await expect(page.getByText('Earlier history evidence').first()).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Previous search evidence' })).toContainText('Jamaican history');
  await expect(page.getByText('Previous results · update needed')).toBeVisible();
  expect(requestCount).toBe(1);

  await page.getByRole('button', { name: 'Update results' }).click();
  await expect.poll(() => requestCount).toBe(2);
  await expect(page.getByText('Updated trade evidence').first()).toBeVisible();
  await expect(page.getByText('Earlier history evidence')).not.toBeVisible();
  await expect(page.getByText('Previous search evidence')).not.toBeVisible();
});

test('clearing a refined search removes previous evidence and the previous-results banner', async ({ page }) => {
  await page.route('**/api/plugins/execute', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          query: 'Jamaican history',
          mode: 'general',
          summary: 'Previous query source evidence',
          sources: [{ id: 'source', title: 'Historical source', url: 'https://example.org/history' }],
          results: [],
        },
      }),
    });
  });

  await page.goto('/plugins/intelligent-search');
  const query = page.getByRole('textbox', { name: 'Query' });
  await query.fill('Jamaican history');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByText('Previous query source evidence').first()).toBeVisible();

  await query.fill('Different question');
  await expect(page.getByText('Previous search evidence')).toBeVisible();
  await page.getByRole('button', { name: 'Clear' }).click();
  await expect(page.getByText('Previous query source evidence')).not.toBeVisible();
  await expect(page.getByText('Previous search evidence')).not.toBeVisible();
  await expect(query).toHaveValue('');
});


test('retained Deep Research insights remain accessible after draft mode changes', async ({ page }) => {
  await page.route('**/api/plugins/execute', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          query: 'Graph retrieval evaluation',
          mode: 'deep_research',
          summary: 'Completed multi-source investigation',
          insights: ['Evidence shows the important dependency'],
          sources: [{
            id: 'research-source',
            title: 'Research reference',
            url: 'https://example.org/research',
            snippet: 'Documented research evidence',
          }],
          results: [],
        },
      }),
    });
  });

  await page.goto('/plugins/intelligent-search');
  await page.getByRole('combobox', { name: 'Search mode' }).selectOption('deep_research');
  await page.getByRole('textbox', { name: 'Query' }).fill('Graph retrieval evaluation');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Show Insights search information' })).toBeVisible();

  await page.getByRole('combobox', { name: 'Search mode' }).selectOption('weather');
  await expect(page.getByText('Previous search evidence')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Show Insights search information' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Show Sources search information' })).toBeVisible();

  await page.getByRole('button', { name: 'Show Insights search information' }).click();
  await expect(page.getByText('Evidence shows the important dependency')).toBeVisible();
});
