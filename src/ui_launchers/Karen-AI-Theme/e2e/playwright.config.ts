import { defineConfig, devices } from '@playwright/test';

/**
 * Generic Playwright configuration for KAREN browser-level UI contracts.
 *
 * Provider/runtime truth is owned by dedicated backend and runtime gates.
 * Trusted real-product presentation capture uses playwright.showcase.config.ts.
 */
// This mode runs the existing approved local-only acceptance test repeatedly.
// Never hide intermittent failures with CI retries or require a desktop display.
const localBenchmark = process.env.KAREN_LOCAL_LATENCY_BENCHMARK === '1';
// A local benchmark signs in with real credentials. Disable sensitive
// recordings at configuration authority, even if a future spec forgets
// its own test.use privacy override or someone opts into capture video.
const privateBrowserRun = localBenchmark ||
  process.env.KAREN_UX_IDENTITY_REPLAY === 'true' ||
  process.env.KAREN_SEARCH_ACCEPTANCE_REQUIRED === 'true';

export default defineConfig({
  testDir: './',
  testMatch: '**/*.spec.ts',

  timeout: 60000,

  expect: {
    timeout: 10000,
  },

  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: localBenchmark ? 0 : process.env.CI ? 2 : 0,
  workers: 1,

  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['list'],
    ['json', { outputFile: 'test-results.json' }],
  ],

  use: {
    baseURL: process.env.KAREN_BASE_URL || 'http://localhost:8010',
    headless: localBenchmark || !!process.env.CI,
    viewport: { width: 1280, height: 720 },
    screenshot: privateBrowserRun ? 'off' : 'only-on-failure',
    // Opt in only on an approved sanitized test installation. Full-session
    // recordings may contain sensitive conversation text or browser state.
    video: privateBrowserRun
      ? 'off'
      : process.env.KAREN_E2E_CAPTURE_VIDEO === 'true'
        ? 'on'
        : 'retain-on-failure',
    // This opt-in suite types a real credential during sign-in.
    // Playwright traces retain fill action parameters, including passwords.
    // Never record such traces or include them in uploaded artifacts.
    trace: privateBrowserRun
      ? 'off'
      : 'retain-on-failure',
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
