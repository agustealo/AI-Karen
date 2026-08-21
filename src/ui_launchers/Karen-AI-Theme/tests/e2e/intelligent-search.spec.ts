import { test, expect } from '@playwright/test';

test.describe('Intelligent Search Plugin', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the intelligent search page
    await page.goto('/plugins/intelligent-search');
  });

  test('plugin page renders with all required elements', async ({ page }) => {
    // Verify main components are visible
    await expect(page.getByTestId('intelligent-search-root')).toBeVisible();
    await expect(page.getByTestId('intelligent-search-query-input')).toBeVisible();
    await expect(page.getByTestId('intelligent-search-submit')).toBeVisible();

    // Verify mode selector is present
    await expect(page.getByRole('combobox')).toBeVisible();

    // Verify initial state shows empty state
    await expect(page.getByTestId('intelligent-search-empty')).toBeVisible();
  });

  test('blocks empty query submission', async ({ page }) => {
    // Try to submit with empty query
    await page.getByTestId('intelligent-search-submit').click();

    // Should show error or validation message
    await expect(page.getByTestId('intelligent-search-error')).toBeVisible();
    await expect(page.getByText(/empty|required/i)).toBeVisible();
  });

  test('renders successful search results', async ({ page }) => {
    // Mock the API response
    await page.route('**/api/plugins/execute', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          result: {
            query: 'Karen runtime providers',
            mode: 'general',
            summary: 'Karen uses a backend-governed provider/runtime model with multiple integrations including OpenAI, Anthropic, and local models.',
            results: [
              {
                id: 'result-1',
                rank: 1,
                title: 'Provider Runtime Documentation',
                url: 'https://example.com/provider-runtime',
                source: 'web',
                snippet: 'Runtime provider catalog controls model selection and execution.',
                summary: 'Provider selection should be backend governed with RBAC and tenant isolation.',
                score: 0.91,
                published_at: null,
                metadata: {},
              },
              {
                id: 'result-2',
                rank: 2,
                title: 'Model Integration Guide',
                url: 'https://example.com/model-integration',
                source: 'web',
                snippet: 'How to integrate new models into Karen runtime.',
                summary: 'Models are registered through the provider registry with proper validation.',
                score: 0.87,
                published_at: null,
                metadata: {},
              },
            ],
            sources: [
              {
                id: 'source-1',
                url: 'https://example.com/provider-runtime',
                title: 'Provider Runtime Documentation',
                snippet: 'Runtime provider catalog controls model selection and execution.',
                content: 'Full content about provider runtime...',
              },
              {
                id: 'source-2',
                url: 'https://example.com/model-integration',
                title: 'Model Integration Guide',
                snippet: 'How to integrate new models into Karen runtime.',
                content: 'Full content about model integration...',
              },
            ],
            diagnostics: {
              mode: 'general',
              latencyMs: 123,
              sourceCount: 2,
              urlsFound: 2,
              chunksProduced: 2,
              degraded: false,
            },
            metadata: {
              provider: 'crawl4ai',
              execution_time_ms: 123,
            },
          },
          execution_time: 0.15,
          timestamp: new Date().toISOString(),
        }),
      });
    });

    // Fill in query and submit
    await page.getByTestId('intelligent-search-query-input').fill('Karen runtime providers');
    await page.getByTestId('intelligent-search-submit').click();

    // Verify loading state
    await expect(page.getByText(/searching|loading/i)).toBeVisible();

    // Wait for results
    await expect(page.getByTestId('intelligent-search-results')).toBeVisible();

    // Verify results are rendered
    await expect(page.getByTestId('intelligent-search-result-card')).toHaveCount(2);

    // Verify summary is shown
    await expect(page.getByTestId('intelligent-search-summary')).toContainText('Karen uses');

    // Verify diagnostics are shown
    await expect(page.getByTestId('intelligent-search-diagnostics')).toBeVisible();
  });

  test('renders degraded response honestly', async ({ page }) => {
    // Mock a degraded response
    await page.route('**/api/plugins/execute', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          result: {
            query: 'test',
            mode: 'general',
            summary: '',
            results: [],
            sources: [],
            diagnostics: {
              mode: 'general',
              latencyMs: 25,
              sourceCount: 0,
              urlsFound: 0,
              chunksProduced: 0,
              degraded: true,
              degradationReason: 'search_source_unavailable',
            },
            errors: [
              {
                code: 'search_source_unavailable',
                message: 'Search source unavailable.',
              },
            ],
          },
          execution_time: 0.025,
          timestamp: new Date().toISOString(),
        }),
      });
    });

    // Fill in query and submit
    await page.getByTestId('intelligent-search-query-input').fill('test');
    await page.getByTestId('intelligent-search-submit').click();

    // Wait for results
    await expect(page.getByTestId('intelligent-search-results')).toBeVisible();

    // Verify degraded status is shown
    await expect(page.getByText(/degraded/i)).toBeVisible();

    // Verify no fake results are rendered
    await expect(page.getByTestId('intelligent-search-result-card')).toHaveCount(0);

    // Verify error message is visible
    await expect(page.getByTestId('intelligent-search-error')).toContainText(/unavailable/i);
  });

  test('handles permission denied for unrestricted mode', async ({ page }) => {
    // Mock a 403 response
    await page.route('**/api/plugins/execute', async route => {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'Unrestricted mode requires admin privileges',
        }),
      });
    });

    // Switch to unrestricted mode if available
    const modeSelector = page.getByRole('combobox');
    await modeSelector.selectOption('unrestricted');

    // Fill in query and submit
    await page.getByTestId('intelligent-search-query-input').fill('test query');
    await page.getByTestId('intelligent-search-submit').click();

    // Verify permission error is shown
    await expect(page.getByTestId('intelligent-search-error')).toContainText(/permission|denied|admin/i);
  });

  test('mode selector changes visible controls', async ({ page }) => {
    // Start with general mode
    let crawlToggle = page.getByTestId('intelligent-search-crawl-toggle');
    await expect(crawlToggle).toBeVisible();

    // Switch to news mode
    const modeSelector = page.getByRole('combobox');
    await modeSelector.selectOption('news');

    // Verify crawl options are still visible (added to news mode too)
    crawlToggle = page.getByTestId('intelligent-search-crawl-toggle');
    await expect(crawlToggle).toBeVisible();

    // Switch to weather mode
    await modeSelector.selectOption('weather');

    // Verify crawl options are not visible in weather mode
    crawlToggle = page.getByTestId('intelligent-search-crawl-toggle');
    await expect(crawlToggle).not.toBeVisible();
  });

  test('responsive layout on mobile viewport', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });

    // Verify components are still usable
    await expect(page.getByTestId('intelligent-search-query-input')).toBeVisible();
    await expect(page.getByTestId('intelligent-search-submit')).toBeVisible();

    // Verify layout is stacked (left column on top)
    const controlsPanel = page.getByText(/options/i);
    await expect(controlsPanel).toBeVisible();
  });

  test('keyboard navigation works', async ({ page }) => {
    // Tab through elements
    await page.keyboard.press('Tab');
    const queryInput = page.getByTestId('intelligent-search-query-input');
    await expect(queryInput).toBeFocused();

    await page.keyboard.press('Tab');
    const submitButton = page.getByTestId('intelligent-search-submit');
    await expect(submitButton).toBeFocused();

    // Test Enter key to submit
    await queryInput.focus();
    await queryInput.fill('test query');
    await page.keyboard.press('Enter');

    // Verify submit was triggered (error or request made)
    await expect(page.getByTestId('intelligent-search-error')).toBeVisible();
  });

  test('clear search results resets state', async ({ page }) => {
    // First perform a search
    await page.route('**/api/plugins/execute', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          result: {
            query: 'test',
            mode: 'general',
            summary: 'Test summary',
            results: [
              {
                id: 'result-1',
                rank: 1,
                title: 'Test Result',
                url: 'https://example.com',
                source: 'web',
                snippet: 'Test snippet',
                summary: 'Test summary',
                score: 0.9,
                published_at: null,
                metadata: {},
              },
            ],
            sources: [],
            diagnostics: {
              mode: 'general',
              latencyMs: 100,
              sourceCount: 1,
              urlsFound: 1,
              chunksProduced: 1,
              degraded: false,
            },
          },
          execution_time: 0.1,
          timestamp: new Date().toISOString(),
        }),
      });
    });

    await page.getByTestId('intelligent-search-query-input').fill('test');
    await page.getByTestId('intelligent-search-submit').click();
    await expect(page.getByTestId('intelligent-search-results')).toBeVisible();

    // Clear results
    await page.getByText(/clear search results/i).click();

    // Verify empty state is shown
    await expect(page.getByTestId('intelligent-search-empty')).toBeVisible();
  });
});
