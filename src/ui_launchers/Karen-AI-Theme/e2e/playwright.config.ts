import { defineConfig, devices } from '@playwright/test';

/**
 * Generic Playwright configuration for KAREN browser-level UI contracts.
 *
 * Provider/runtime truth is owned by dedicated backend and runtime gates.
 * Trusted real-product presentation capture uses playwright.showcase.config.ts.
 */
export default defineConfig({
  testDir: './',
  testMatch: '**/*.spec.ts',

  timeout: 60000,

  expect: {
    timeout: 10000,
  },

  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,

  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['list'],
    ['json', { outputFile: 'test-results.json' }],
  ],

  use: {
    baseURL: process.env.KAREN_BASE_URL || 'http://localhost:8010',
    headless: !!process.env.CI,
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
