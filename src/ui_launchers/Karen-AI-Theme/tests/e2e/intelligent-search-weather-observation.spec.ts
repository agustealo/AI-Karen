import { expect, test } from '@playwright/test';

test('structured weather results show sourced measurement and timestamp', async ({ page }) => {
  await page.route('**/api/plugins/execute', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        result: {
          query: 'weather in Detroit',
          mode: 'weather',
          status: 'ok',
          summary: '',
          extractedData: {
            location: 'Detroit, Michigan, US',
            temperature_f: 55,
            observed_at: '2026-10-25T09:00',
            timezone: 'America/Detroit',
          },
          sources: [{ id: 'forecast', title: 'Open-Meteo', url: 'https://api.open-meteo.com/v1/forecast' }],
          results: [],
        },
      }),
    });
  });
  await page.goto('/plugins/intelligent-search');
  await page.getByRole('textbox', { name: 'Query' }).fill('weather in Detroit');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Weather observation' })).toContainText('Detroit, Michigan, US');
  await expect(page.getByRole('region', { name: 'Weather observation' })).toContainText('55 °F');
  await expect(page.getByRole('region', { name: 'Weather observation' })).toContainText('2026-10-25T09:00');
  await expect(page.getByRole('region', { name: 'Weather observation' })).toContainText('not an AI-generated forecast explanation');
});
