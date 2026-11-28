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
// Document-author acceptance uses the existing private, no-retry authenticated
// browser contract; do not introduce a competing capture/retry authority.
const settingsAcceptance = process.env.KAREN_SETTINGS_VISUAL_ACCEPTANCE === 'true' ||
  process.env.KAREN_DOCUMENT_AUTHOR_ACCEPTANCE === 'true';
const navigationAcceptance = process.env.KAREN_NAV_VISUAL_ACCEPTANCE === 'true';
const fileExplorerAcceptance = process.env.KAREN_FILE_EXPLORER_ACCEPTANCE === 'true';
const pinReadbackAcceptance = process.env.KAREN_PIN_READBACK_ACCEPTANCE === '1';
const documentAuthorAcceptance = process.env.KAREN_DOCUMENT_AUTHOR_ACCEPTANCE === 'true';
const cardStudioAcceptance = process.env.KAREN_CARD_STUDIO_VISUAL_ACCEPTANCE === 'true';
// A local benchmark signs in with real credentials. Disable sensitive
// recordings at configuration authority, even if a future spec forgets
// its own test.use privacy override or someone opts into capture video.
const participationAcceptance = process.env.KAREN_SPECIALIST_PARTICIPATION_ACCEPTANCE === 'true';
const inboxAcceptance = process.env.KAREN_COMMS_INBOX_ACCEPTANCE === 'true';
const generatedDocumentAcceptance = process.env.KAREN_GENERATED_DOCUMENT_ACCEPTANCE === 'true';
const kexpAcceptance = process.env.KAREN_KEXP_RETRY_ACCEPTANCE_REQUIRED === 'true' ||
  process.env.KAREN_KEXP_CONTENT_ACCEPTANCE_REQUIRED === 'true';
const privateLifecycleAcceptance = participationAcceptance || inboxAcceptance || generatedDocumentAcceptance || kexpAcceptance;
// Playwright 1.59.1 also captures failure accessibility snapshots independently
// of trace/screenshot settings. Suppress those before workers start; remove
// per-test output (including error-context.md) during normal runner teardown.
if (privateLifecycleAcceptance) process.env.PLAYWRIGHT_NO_COPY_PROMPT = '1';
const privateBrowserRun = localBenchmark ||
  process.env.KAREN_UX_IDENTITY_REPLAY === 'true' ||
  process.env.KAREN_SEARCH_ACCEPTANCE_REQUIRED === 'true' ||
  navigationAcceptance ||
  settingsAcceptance ||
  fileExplorerAcceptance ||
  pinReadbackAcceptance ||
  cardStudioAcceptance || privateLifecycleAcceptance;

export default defineConfig({
  testDir: './',
  testMatch: '**/*.spec.ts',

  timeout: 60000,

  expect: {
    timeout: 10000,
  },

  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: localBenchmark || settingsAcceptance || navigationAcceptance || fileExplorerAcceptance || pinReadbackAcceptance || cardStudioAcceptance || privateLifecycleAcceptance ? 0 : process.env.CI ? 2 : 0,
  preserveOutput: privateLifecycleAcceptance ? 'never' : 'always',
  workers: 1,

  // Authenticated Settings acceptance must not persist response text,
  // failure stacks or browser state into local HTML/JSON result artifacts.
  // The console list reporter supplies the protected job's result.
  reporter: settingsAcceptance || navigationAcceptance || fileExplorerAcceptance || pinReadbackAcceptance || documentAuthorAcceptance || cardStudioAcceptance || privateLifecycleAcceptance
    ? [['list']]
    : [
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
