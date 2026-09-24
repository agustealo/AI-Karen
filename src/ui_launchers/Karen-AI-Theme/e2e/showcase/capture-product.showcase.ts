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

  if (!email || !password) {
    throw new Error(
      "KAREN_SHOWCASE_EMAIL and KAREN_SHOWCASE_PASSWORD are required for real authenticated product capture.",
    );
  }

  return { email, password };
};

function currentGitSha(): string {
  const configuredSha = process.env.GITHUB_SHA?.trim();
  if (configuredSha && /^[0-9a-f]{40}$/i.test(configuredSha)) {
    return configuredSha.toLowerCase();
  }

  const sha = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: path.resolve(process.cwd(), "../../.."),
    encoding: "utf8",
  }).trim();

  if (!/^[0-9a-f]{40}$/i.test(sha)) {
    throw new Error(`Unable to establish exact capture git SHA: ${sha}`);
  }

  return sha.toLowerCase();
}

async function capture(
  page: Page,
  filename: string,
  email: string,
): Promise<void> {
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
  await page.waitForTimeout(450);
}

test("capture premium KAREN product surfaces from a real runtime", async ({
  page,
  browser,
}) => {
  const { email, password } = requiredEnvironment();
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
    page.getByRole("heading", { name: "Karen AI", exact: true }),
  ).toBeVisible({ timeout: 45_000 });

  await capture(page, GALLERY_FILES[0], email);

  await openSurface(page, "Agents Overview");
  await capture(page, GALLERY_FILES[1], email);

  await openSurface(page, "Plugin Overview");
  await capture(page, GALLERY_FILES[2], email);

  await openSurface(page, "Comms Center");
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
  ).toBeVisible();
  await page.waitForTimeout(450);
  await capture(page, GALLERY_FILES[4], email);

  const manifest = {
    schema_version: 1,
    source: "real-running-application",
    authenticated: true,
    account_kind: "sanitized-demo",
    git_sha: currentGitSha(),
    captured_at: new Date().toISOString(),
    browser: `chromium ${browser.version()}`,
    viewport: { width: 1600, height: 1000 },
    color_scheme: "dark",
    policy: {
      mocked_responses: false,
      generated_ui: false,
      fixture_only_state: false,
      production_or_personal_data: false,
    },
    files: [...GALLERY_FILES],
  };

  await writeFile(
    path.join(SCREENSHOT_DIR, "capture-manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
});
