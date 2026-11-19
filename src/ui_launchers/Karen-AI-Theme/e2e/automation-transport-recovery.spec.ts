import { expect, test, type Page, type Route } from "@playwright/test";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import { openAutomationWorkspace } from "./fixtures/automation-workspace-navigation";

/**
 * Opt-in authenticated consumer proof.
 *
 * A real Jobs GET succeeds, one subsequent GET is deliberately disconnected
 * at the browser transport boundary, and a new genuine GET must recover.
 * Only request transport is fault-injected: no JSON, auth state, or success
 * response is fabricated. Traces and credential-bearing media stay disabled.
 */
const enabled = process.env.KAREN_AUTOMATION_TRANSPORT_ACCEPTANCE === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const expectedJob = process.env.KAREN_UX_ACCOUNT_A_JOB_MARKER;
const localLoopback = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
const jobsPath = "/api/automation/jobs/";

test.use({ trace: "off", screenshot: "off", video: "off" });

function isJobsGet(request: { url(): string; method(): string }, origin: string): boolean {
  const target = new URL(request.url());
  return target.origin === origin &&
    target.pathname === jobsPath &&
    request.method() === "GET";
}

function waitForRealJobs(page: Page, origin: string) {
  return page.waitForResponse(
    response => isJobsGet(response.request(), origin),
    { timeout: 30_000 },
  );
}

async function verifyRealJobs(page: Page, origin: string): Promise<void> {
  const pending = waitForRealJobs(page, origin);
  await openAutomationWorkspace(page, "Jobs", true);
  const response = await pending;
  expect(response.status(), "A real Jobs read must succeed").toBe(200);
  const rows: unknown = await response.json();
  expect(Array.isArray(rows), "The real Jobs API must return a list").toBe(true);
  if (!Array.isArray(rows)) throw new Error("Unverified Jobs response");
  expect(
    rows.some(row => row !== null && typeof row === "object" &&
      !Array.isArray(row) && (row as Record<string, unknown>).name === expectedJob),
    "The existing sanitized job must belong to the logged-in identity",
  ).toBe(true);
  const root = page.locator(".karen-automation-workflow");
  await expect(root.getByText(expectedJob!, { exact: false }).first()).toBeVisible();
  await expect(root.getByText("Job definitions could not be verified with the backend.")).toHaveCount(0);
}

test("KUI-AUTOMATION: authenticated network failure, recovery and same-user re-login", async ({ page }) => {
  test.skip(!enabled, "Requires explicit KAREN_AUTOMATION_TRANSPORT_ACCEPTANCE=true");
  test.setTimeout(5 * 60_000);
  if (!email || !password || !expectedJob) {
    throw new Error("Dedicated sanitized identity and pre-existing job marker required");
  }

  await signInApprovedKaren(page, email, password, { allowLocalLoopback: localLoopback });
  const origin = new URL(page.url()).origin;
  await verifyRealJobs(page, origin);

  // One deliberately failed browser transport request. Authentication remains
  // real; this does not stub an HTTP status, JSON payload, or application state.
  let intercepted = 0;
  const routeHandler = async (route: Route): Promise<void> => {
    if (isJobsGet(route.request(), origin) && intercepted === 0) {
      intercepted += 1;
      await route.abort("failed");
      return;
    }
    await route.continue();
  };
  await page.route("**/api/automation/jobs/**", routeHandler);
  const root = page.locator(".karen-automation-workflow");
  const refresh = root.getByRole("button", { name: "Refresh", exact: true });

  try {
    const failedRequest = page.waitForEvent("requestfailed", {
      predicate: request => isJobsGet(request, origin),
      timeout: 30_000,
    });
    await refresh.click();
    await failedRequest;
    expect(intercepted).toBe(1);
    await expect(root.getByText("Job definitions could not be verified with the backend.")).toBeVisible();
    await expect(root.getByText("No jobs defined yet.")).toHaveCount(0);
    await expect(root.getByText(expectedJob, { exact: false })).toHaveCount(0);
  } finally {
    await page.unroute("**/api/automation/jobs/**", routeHandler);
  }

  const recovered = waitForRealJobs(page, origin);
  await refresh.click();
  const response = await recovered;
  expect(response.status(), "Recovery must use a genuine server response").toBe(200);
  const body: unknown = await response.json();
  expect(Array.isArray(body)).toBe(true);
  await expect(root.getByText(expectedJob, { exact: false }).first()).toBeVisible();
  await expect(root.getByText("Job definitions could not be verified with the backend.")).toHaveCount(0);

  await openAutomationWorkspace(page, "My Account", false);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login(?:[?#]|$)/, { timeout: 30_000 });
  const denied = await page.evaluate(async () => {
    const response = await fetch("/api/tasks/", {
      credentials: "same-origin",
      method: "GET",
      cache: "no-store",
    });
    return response.status;
  });
  expect([401, 403], "Logout must revoke backend read authorization").toContain(denied);

  // The same principal receives a fresh session, rather than reusing
  // memory or cached lists to produce an apparent successful recovery.
  await signInApprovedKaren(page, email, password, { allowLocalLoopback: localLoopback });
  expect(new URL(page.url()).origin).toBe(origin);
  await verifyRealJobs(page, origin);
});
