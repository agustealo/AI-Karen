import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const SCREENSHOT_DIR = path.resolve(
  process.cwd(),
  "../../..",
  "docs/assets/screenshots",
);

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

  await capture(page, "01-chat-runtime.png", email);

  await openSurface(page, "Agents Overview");
  await capture(page, "02-agents-overview.png", email);

  await openSurface(page, "Plugin Overview");
  await capture(page, "03-plugin-ecosystem.png", email);

  await openSurface(page, "Comms Center");
  await capture(page, "04-comms-center.png", email);

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
  await capture(page, "05-settings-and-models.png", email);
});
