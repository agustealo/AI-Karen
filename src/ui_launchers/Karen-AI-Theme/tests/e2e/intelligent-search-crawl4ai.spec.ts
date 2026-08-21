import { test, expect } from '@playwright/test';

test.describe('Intelligent Search - Crawl4AI Integration', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the intelligent search page
    await page.goto('/plugins/intelligent-search');
  });

  test('crawl options render in general mode', async ({ page }) => {
    // Verify crawl toggle is visible
    await expect(page.getByTestId('intelligent-search-crawl-toggle')).toBeVisible();

    // Click to expand
    await page.getByTestId('intelligent-search-crawl-toggle').click();

    // Verify crawl options panel is visible
    await expect(page.getByTestId('intelligent-search-crawl-options')).toBeVisible();

    // Verify key controls are present
    await expect(page.getByTestId('intelligent-search-max-pages')).toBeVisible();
    await expect(page.getByTestId('intelligent-search-max-depth')).toBeVisible();
    await expect(page.getByTestId('intelligent-search-use-cache')).toBeVisible();
    await expect(page.getByTestId('intelligent-search-capture-screenshot')).toBeVisible();
  });

  test('enabling crawl includes options in API request', async ({ page }) => {
    // Enable API interception
    let requestBody: any = null;
    await page.route('**/api/plugins/execute', async route => {
      const request = route.request();
      requestBody = await request.postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          result: {
            query: 'test',
            mode: 'general',
            summary: 'Test summary',
            results: [],
            sources: [],
            diagnostics: {
              mode: 'general',
              latencyMs: 100,
              sourceCount: 0,
              urlsFound: 0,
              chunksProduced: 0,
              degraded: false,
            },
          },
          execution_time: 0.1,
          timestamp: new Date().toISOString(),
        }),
      });
    });

    // Expand crawl options
    await page.getByTestId('intelligent-search-crawl-toggle').click();

    // Enable crawl
    await page.getByLabel('Enable Deep Crawl').check();

    // Set max pages
    const maxPagesSlider = page.getByTestId('intelligent-search-max-pages');
    await maxPagesSlider.fill('10');

    // Set max depth
    const maxDepthSlider = page.getByTestId('intelligent-search-max-depth');
    await maxDepthSlider.fill('2');

    // Enable screenshot
    await page.getByTestId('intelligent-search-capture-screenshot').check();

    // Fill query and submit
    await page.getByTestId('intelligent-search-query-input').fill('test query');
    await page.getByTestId('intelligent-search-submit').click();

    // Verify request body includes crawl options
    expect(requestBody).toBeDefined();
    expect(requestBody.parameters.crawl).toBeDefined();
    expect(requestBody.parameters.crawl.enabled).toBe(true);
    expect(requestBody.parameters.crawl.maxPages).toBe(10);
    expect(requestBody.parameters.crawl.maxDepth).toBe(2);
    expect(requestBody.parameters.crawl.captureScreenshot).toBe(true);
  });

  test('successful crawl renders crawl diagnostics', async ({ page }) => {
    // Mock successful crawl response
    await page.route('**/api/plugins/execute', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          result: {
            query: 'test',
            mode: 'general',
            summary: 'Crawl4AI extracted usable page content.',
            results: [
              {
                id: 'crawl-result-1',
                rank: 1,
                title: 'Example Page',
                url: 'https://example.com',
                source: 'crawl4ai',
                snippet: 'Extracted page text.',
                summary: 'Extracted page summary.',
                score: 0.91,
                published_at: null,
                metadata: {
                  crawl_success: true,
                },
              },
            ],
            sources: [
              {
                id: 'source-1',
                url: 'https://example.com',
                title: 'Example Page',
                snippet: 'Extracted page text.',
                content: 'Full crawled content...',
                markdown: '# Example Page\n\nCrawled content here...',
              },
            ],
            crawl: {
              enabled: true,
              engine: 'crawl4ai',
              status: 'ok',
              pages_requested: 1,
              pages_succeeded: 1,
              pages_failed: 0,
              latency_ms: 250,
              capabilities: {
                screenshot: true,
                structured_css_extraction: true,
              },
              degraded: false,
              degradation_reason: null,
            },
            diagnostics: {
              mode: 'general',
              latencyMs: 250,
              sourceCount: 1,
              urlsFound: 1,
              chunksProduced: 1,
              degraded: false,
            },
          },
          execution_time: 0.25,
          timestamp: new Date().toISOString(),
        }),
      });
    });

    // Expand crawl options and enable
    await page.getByTestId('intelligent-search-crawl-toggle').click();
    await page.getByLabel('Enable Deep Crawl').check();

    // Fill query and submit
    await page.getByTestId('intelligent-search-query-input').fill('test');
    await page.getByTestId('intelligent-search-submit').click();

    // Wait for results
    await expect(page.getByTestId('intelligent-search-results')).toBeVisible();

    // Verify crawl diagnostics are shown
    await expect(page.getByTestId('intelligent-search-crawl-diagnostics')).toBeVisible();

    // Verify crawl status
    await expect(page.getByText(/crawl4ai|crawl engine/i)).toBeVisible();
    await expect(page.getByText(/pages.*succeeded|1.*succeeded/i)).toBeVisible();
  });

  test('partial crawl renders degraded state honestly', async ({ page }) => {
    // Mock partial crawl response
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
            crawl: {
              enabled: true,
              engine: 'crawl4ai',
              status: 'partial',
              pages_requested: 3,
              pages_succeeded: 1,
              pages_failed: 2,
              latency_ms: 150,
              capabilities: {},
              degraded: true,
              degradation_reason: 'partial_crawl_failure',
            },
            diagnostics: {
              mode: 'general',
              latencyMs: 150,
              sourceCount: 0,
              urlsFound: 0,
              chunksProduced: 0,
              degraded: true,
              degradationReason: 'partial_crawl_failure',
            },
            errors: [
              {
                code: 'partial_crawl_failure',
                message: '2 out of 3 pages failed to crawl',
              },
            ],
          },
          execution_time: 0.15,
          timestamp: new Date().toISOString(),
        }),
      });
    });

    // Expand crawl options and enable
    await page.getByTestId('intelligent-search-crawl-toggle').click();
    await page.getByLabel('Enable Deep Crawl').check();

    // Fill query and submit
    await page.getByTestId('intelligent-search-query-input').fill('test');
    await page.getByTestId('intelligent-search-submit').click();

    // Wait for results
    await expect(page.getByTestId('intelligent-search-results')).toBeVisible();

    // Verify degraded status
    await expect(page.getByText(/degraded|partial/i)).toBeVisible();

    // Verify crawl failure is shown
    await expect(page.getByText(/2.*failed|partial.*crawl/i)).toBeVisible();

    // Verify no fake results
    await expect(page.getByTestId('intelligent-search-result-card')).toHaveCount(0);
  });

  test('max pages and depth limits are enforced in UI', async ({ page }) => {
    // Expand crawl options
    await page.getByTestId('intelligent-search-crawl-toggle').click();

    // Test max pages slider limits
    const maxPagesSlider = page.getByTestId('intelligent-search-max-pages');
    await maxPagesSlider.fill('100'); // Try to exceed max

    // Verify it's clamped to max (50)
    const maxPagesValue = await maxPagesSlider.inputValue();
    expect(parseInt(maxPagesValue)).toBeLessThanOrEqual(50);

    // Test max depth slider limits
    const maxDepthSlider = page.getByTestId('intelligent-search-max-depth');
    await maxDepthSlider.fill('10'); // Try to exceed max

    // Verify it's clamped to max (5)
    const maxDepthValue = await maxDepthSlider.inputValue();
    expect(parseInt(maxDepthValue)).toBeLessThanOrEqual(5);
  });

  test('structured schema validation blocks malformed JSON', async ({ page }) => {
    // Expand crawl options
    await page.getByTestId('intelligent-search-crawl-toggle').click();

    // Find structured schema textarea
    const schemaTextarea = page.getByTestId('intelligent-search-structured-schema');

    // Enter invalid JSON
    await schemaTextarea.fill('{ invalid json }');

    // Try to submit
    await page.getByTestId('intelligent-search-query-input').fill('test');
    await page.getByTestId('intelligent-search-submit').click();

    // Should show validation error (the API should reject it)
    await expect(page.getByTestId('intelligent-search-error')).toBeVisible();
  });

  test('include/exclude domains work correctly', async ({ page }) => {
    // Expand crawl options
    await page.getByTestId('intelligent-search-crawl-toggle').click();

    // Add include domain
    const includeInput = page.getByPlaceholder('example.com').first();
    await includeInput.fill('example.com');
    await includeInput.press('Enter');

    // Verify domain tag appears
    await expect(page.getByText('example.com')).toBeVisible();

    // Add exclude domain
    const excludeInput = page.getByPlaceholder('ads.example.com');
    await excludeInput.fill('ads.example.com');
    await excludeInput.press('Enter');

    // Verify exclude domain tag appears
    await expect(page.getByText('ads.example.com')).toBeVisible();

    // Click remove button on include domain
    await page.locator('.bg-primary\\/10').getByText('×').first().click();

    // Verify domain tag is removed
    await expect(page.getByText('example.com')).not.toBeVisible();
  });

  test('crawl options respect capabilities', async ({ page }) => {
    // Mock capabilities endpoint to disable screenshot support
    await page.route('**/api/plugins/intelligent-search/capabilities', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          plugin_id: 'intelligent_search',
          plugin_version: '0.1.0',
          enabled: true,
          permissions: ['search:web'],
          available_modes: ['basic', 'advanced', 'unrestricted'],
          available_sources: ['web', 'memory', 'documents'],
          rbac: {
            required_roles: ['user'],
            unrestricted_required_roles: ['admin'],
          },
          crawl_capabilities: {
            enabled: true,
            engine: 'crawl4ai',
            max_pages: 50,
            max_depth: 5,
            supports_screenshot: false,
            supports_structured_extraction: true,
          },
        }),
      });
    });

    // Refresh page to load capabilities
    await page.reload();

    // Expand crawl options
    await page.getByTestId('intelligent-search-crawl-toggle').click();

    // Screenshot checkbox should not be visible or should be disabled
    const screenshotCheckbox = page.getByTestId('intelligent-search-capture-screenshot');
    await expect(screenshotCheckbox).not.toBeVisible();
  });

  test('wait for selector input works', async ({ page }) => {
    // Expand crawl options
    await page.getByTestId('intelligent-search-crawl-toggle').click();

    // Fill wait for selector
    const waitSelector = page.getByTestId('intelligent-search-wait-selector');
    await waitSelector.fill('.main-content');

    // Verify value is set
    const value = await waitSelector.inputValue();
    expect(value).toBe('.main-content');

    // Clear and set another selector
    await waitSelector.fill('');
    await waitSelector.fill('#article');

    // Verify new value
    const newValue = await waitSelector.inputValue();
    expect(newValue).toBe('#article');
  });
});
