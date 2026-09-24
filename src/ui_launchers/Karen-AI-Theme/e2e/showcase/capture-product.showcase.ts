import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  "../../..",
  "docs/assets/screenshots",
);

const GALLERY_FILES = [
  "01-chat-runtime.png",
  "02-agents-overview.png",
  "03-plugin-ecosystem.png",
  "04-comms-center.png",
  "05-settings-and-models.png",
] as const;

const FULL_SHA = /^[0-9a-f]{40}$/i;
const RETIRED_VISIBLE_BRAND = /\bKaren AI\b/i;
const COMMS_DEGRADED_TITLES = [
  "Sign In Required",
  "Observability Access Restricted",
  "Observability Fallback",
] as const;

const requiredEnvironment = () => {
  if (process.env.KAREN_SHOWCASE_ALLOW_CAPTURE !== "true") {
    throw new Error(
      "Showcase capture is disabled. Set KAREN_SHOWCASE_ALLOW_CAPTURE=true only for an approved sanitized demo installation.",
    );
  }

  if (process.env.KAREN_SHOWCASE_ACCOUNT_KIND !== "sanitized-demo") {
    throw new Error(
      "Showcase capture requires KAREN_SHOWCASE_ACCOUNT_KIND=sanitized-demo. Personal or production accounts must not be used.",
    );
  }

  const email = process.env.KAREN_SHOWCASE_EMAIL;
  const password = process.env.KAREN_SHOWCASE_PASSWORD;
  const targetRevision = process.env.KAREN_SHOWCASE_TARGET_REVISION?.trim();

  if (!email || !password) {
    throw new Error(
      "KAREN_SHOWCASE_EMAIL and KAREN_SHOWCASE_PASSWORD are required for real authenticated product capture.",
    );
  }

  if (!targetRevision || !FULL_SHA.test(targetRevision)) {
    throw new Error(
      "KAREN_SHOWCASE_TARGET_REVISION must be the full 40-character git SHA that the capture operator attests is deployed at the target installation.",
    );
  }

  return { email, password, targetRevision: targetRevision.toLowerCase() };
};

function currentGitSha(): string {
  const configuredSha = process.env.GITHUB_SHA?.trim();
  if (configuredSha && FULL_SHA.test(configuredSha)) {
    return configuredSha.toLowerCase();
  }

  const sha = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: path.resolve(process.cwd(), "../../.."),
    encoding: "utf8",
  }).trim();

  if (!FULL_SHA.test(sha)) {
    throw new Error(`Unable to establish exact capture harness git SHA: ${sha}`);
  }

  return sha.toLowerCase();
}

async function visibleBodyText(page: Page): Promise<string> {
  return page.locator("body").innerText();
}

async function assertCanonicalVisibleBrand(page: Page): Promise<void> {
  await expect
    .poll(
      async () => RETIRED_VISIBLE_BRAND.test(await visibleBodyText(page)),
      {
        timeout: 10_000,
        message:
          'Presentation target still renders the retired visible brand "Karen AI". Converge the product copy to canonical KAREN before capture.',
      },
    )
    .toBe(false);
}

async function assertChatReady(page: Page): Promise<void> {
  const log = page.getByRole("log", { name: "Chat messages" });
  await expect(log).toBeVisible({ timeout: 30_000 });
  await expect
    .poll(
      async () => (await log.innerText()).trim().length,
      {
        timeout: 30_000,
        message:
          "The sanitized showcase account must contain a real non-sensitive conversation before the Chat screenshot can be promoted as product evidence.",
      },
    )
    .toBeGreaterThan(24);
  await assertCanonicalVisibleBrand(page);
}

async function assertAgentsReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { name: "Agents Overview", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByRole("heading", { name: "Dashboard", exact: true }),
  ).toBeVisible();
  await expect
    .poll(
      async () => (await visibleBodyText(page)).includes("..."),
      {
        timeout: 30_000,
        message:
          "Agents Overview still contains loading placeholders. Real runtime metrics must finish loading before capture.",
      },
    )
    .toBe(false);
  await assertCanonicalVisibleBrand(page);
}

async function assertPluginOverviewReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", {
      name: /Plugins(?:\s*&\s*Tools)? Overview/i,
    }),
  ).toBeVisible({ timeout: 30_000 });

  await expect
    .poll(
      async () => {
        const statuses = page.getByRole("status");
        const count = await statuses.count();
        for (let index = 0; index < count; index += 1) {
          if (await statuses.nth(index).isVisible()) {
            return true;
          }
        }
        return false;
      },
      {
        timeout: 30_000,
        message:
          "Plugin Overview is still loading. Registry/backend lifecycle state must settle before capture.",
      },
    )
    .toBe(false);

  await assertCanonicalVisibleBrand(page);
}

async function assertCommsReady(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", {
      name: "Communications Center",
      exact: true,
    }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Writeback Queue", { exact: true })).toBeVisible();
  await expect(page.getByText("Audit Events", { exact: true })).toBeVisible();
  await expect(page.getByText("Training Signals", { exact: true })).toBeVisible();

  for (const title of COMMS_DEGRADED_TITLES) {
    await expect(page.getByText(title, { exact: true })).toHaveCount(0);
  }

  await assertCanonicalVisibleBrand(page);
}

async function capture(
  page: Page,
  filename: string,
  email: string,
): Promise<void> {
  await assertCanonicalVisibleBrand(page);
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        caret-color: transparent !important;
      }
    `,
  });

  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, filename),
    fullPage: false,
    animations: "disabled",
    caret: "hide",
    mask: [page.getByText(email, { exact: false })],
  });
}

async function openSurface(page: Page, label: string): Promise<void> {
  const control = page.getByRole("button", { name: label, exact: true });
  await expect(control).toBeVisible();
  await control.click();
}

test("capture premium KAREN product surfaces from a real runtime", async ({
  page,
  browser,
}) => {
  const { email, password, targetRevision } = requiredEnvironment();
  await mkdir(SCREENSHOT_DIR, { recursive: true });

  await page.goto("/login", { waitUntil: "domcontentloaded" });

  if (new URL(page.url()).pathname === "/setup") {
    throw new Error(
      "The target installation is still in first-run setup. Complete secure setup before showcase capture.",
    );
  }

  if (!new URL(page.url()).pathname.startsWith("/dashboard")) {
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
  }

  await page.waitForURL(/\/dashboard(?:$|[/?#])/);
  await expect(
    page.getByRole("heading", { name: "KAREN", exact: true }),
  ).toBeVisible({ timeout: 45_000 });
  await expect(
    page.locator('header img[src*="karen-mark.svg"]').first(),
  ).toBeVisible();

  await assertChatReady(page);
  await capture(page, GALLERY_FILES[0], email);

  await openSurface(page, "Agents Overview");
  await assertAgentsReady(page);
  await capture(page, GALLERY_FILES[1], email);

  await openSurface(page, "Plugin Overview");
  await assertPluginOverviewReady(page);
  await capture(page, GALLERY_FILES[2], email);

  await openSurface(page, "Comms Center");
  await assertCommsReady(page);
  await capture(page, GALLERY_FILES[3], email);

  await openSurface(page, "Application Settings");
  const runtimeCategory = page.getByRole("tab", {
    name: "Models & Runtime",
    exact: true,
  });
  await expect(runtimeCategory).toBeVisible();
  await runtimeCategory.click();

  const providersSection = page.getByRole("button", {
    name: "Providers",
    exact: true,
  });
  await expect(providersSection).toBeVisible();
  await providersSection.click();
  await expect(
    page.getByRole("heading", { name: "Providers", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  await assertCanonicalVisibleBrand(page);
  await capture(page, GALLERY_FILES[4], email);

  const manifest = {
    schema_version: 1,
    source: "real-running-application",
    authenticated: true,
    account_kind: "sanitized-demo",
    capture_harness_git_sha: currentGitSha(),
    target_revision: targetRevision,
    target_revision_attestation: "operator-supplied",
    captured_at: new Date().toISOString(),
    browser: `chromium ${browser.version()}`,
    viewport: { width: 1600, height: 1000 },
    color_scheme: "dark",
    policy: {
      mocked_responses: false,
      generated_ui: false,
      fixture_only_state: false,
      production_or_personal_data: false,
      presentation_ready_state_required: true,
      retired_visible_brand_forbidden: true,
    },
    files: [...GALLERY_FILES],
  };

  await writeFile(
    path.join(SCREENSHOT_DIR, "capture-manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
});
