import { expect, test } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const VIEWPORT = { width: 1440, height: 900 } as const;
const OUTPUT_FILES = [
  '01-login.png',
  '02-chat-runtime.png',
  '03-comms-center.png',
  '04-agents-overview.png',
  '05-plugin-overview.png',
  '06-settings.png',
] as const;

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required presentation capture environment variable: ${name}`);
  }
  return value;
}

function repositoryRoot(): string {
  return execFileSync('git', ['rev-parse', '--show-toplevel'], {
    encoding: 'utf8',
  }).trim();
}

function currentGitSha(): string {
  return execFileSync('git', ['rev-parse', 'HEAD'], {
    encoding: 'utf8',
  }).trim();
}

async function settle(page: import('@playwright/test').Page): Promise<void> {
  await page.waitForTimeout(1200);
}

async function capture(
  page: import('@playwright/test').Page,
  outputDirectory: string,
  fileName: (typeof OUTPUT_FILES)[number],
): Promise<void> {
  await settle(page);
  await page.screenshot({
    path: join(outputDirectory, fileName),
    fullPage: true,
    animations: 'disabled',
  });
}

test.describe('KAREN premium product photography', () => {
  test('captures only real authenticated application state', async ({ page, browserName }) => {
    const password = requiredEnv('KAREN_CAPTURE_PASSWORD');
    const email = process.env.KAREN_CAPTURE_EMAIL?.trim();
    const username = process.env.KAREN_CAPTURE_USERNAME?.trim();

    if (!email && !username) {
      throw new Error(
        'Set KAREN_CAPTURE_EMAIL or KAREN_CAPTURE_USERNAME for a real KAREN account.',
      );
    }

    if (email && username) {
      throw new Error(
        'Set only one of KAREN_CAPTURE_EMAIL or KAREN_CAPTURE_USERNAME so capture identity is unambiguous.',
      );
    }

    const root = repositoryRoot();
    const outputDirectory = join(root, 'docs', 'assets', 'screenshots');
    mkdirSync(outputDirectory, { recursive: true });

    await page.setViewportSize(VIEWPORT);
    await page.goto('/login');

    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
    await capture(page, outputDirectory, '01-login.png');

    if (email) {
      await page.getByLabel('Email').fill(email);
    } else {
      await page.getByRole('button', { name: 'Username', exact: true }).click();
      await page.getByLabel('Username').fill(username!);
    }

    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();

    await expect(page).toHaveURL(/\/dashboard(?:\?|$)/, { timeout: 30_000 });
    await expect(page.getByRole('heading', { name: 'Karen AI' })).toBeVisible({
      timeout: 60_000,
    });
    await expect(page.getByText('Backend Connection Failed')).toHaveCount(0);

    await capture(page, outputDirectory, '02-chat-runtime.png');

    await page.getByRole('button', { name: 'Comms Center', exact: true }).click();
    await capture(page, outputDirectory, '03-comms-center.png');

    await page.getByRole('button', { name: 'Agents Overview', exact: true }).click();
    await capture(page, outputDirectory, '04-agents-overview.png');

    await page.getByRole('button', { name: 'Plugin Overview', exact: true }).click();
    await capture(page, outputDirectory, '05-plugin-overview.png');

    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
    await capture(page, outputDirectory, '06-settings.png');

    const configuredBaseUrl = process.env.KAREN_BASE_URL ?? 'http://localhost:8010';
    const manifest = {
      schema_version: 1,
      product: 'KAREN',
      source: 'real-running-application',
      git_sha: currentGitSha(),
      captured_at: new Date().toISOString(),
      origin: new URL(configuredBaseUrl).origin,
      browser: browserName,
      viewport: VIEWPORT,
      authenticated: true,
      identity_mode: email ? 'email' : 'username',
      files: OUTPUT_FILES,
      policy: {
        mocked_responses: false,
        generated_ui: false,
        fixture_only_state: false,
      },
    };

    writeFileSync(
      join(outputDirectory, 'capture-manifest.json'),
      `${JSON.stringify(manifest, null, 2)}\n`,
      'utf8',
    );
  });
});
