import { defineConfig, devices } from '@playwright/test';

const presentationCapture = process.env.KAREN_PRESENTATION_CAPTURE === '1';

/**
 * Playwright Configuration for KAREN E2E tests.
 *
 * Presentation capture is intentionally opt-in because it requires credentials
 * for a real running installation. Normal E2E runs must remain independent of
 * marketing/product-photography credentials.
 */
export default defineConfig({
  testDir: './',
  testMatch: presentationCapture
    ? '**/presentation.capture.spec.ts'
    : '**/*.spec.ts',
  testIgnore: presentationCapture
    ? []
    : ['**/presentation.capture.spec.ts'],

  timeout: 60000,

  expect: {
    timeout: 10000,
  },

  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: presentationCapture ? 0 : process.env.CI ? 2 : 0,
  workers: 1,

  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['list'],
    ['json', { outputFile: 'test-results.json' }],
  ],

  use: {
    baseURL: process.env.KAREN_BASE_URL || 'http://localhost:8010',
    headless: process.env.CI ? true : false,
    viewport: { width: 1280, height: 720 },
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
    actionTimeout: 15000,
    navigationTimeout: 30000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
