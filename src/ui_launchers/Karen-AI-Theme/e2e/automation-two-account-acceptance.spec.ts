import { expect, test, type Page } from "@playwright/test";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import { openAutomationWorkspace } from "./fixtures/automation-workspace-navigation";

/**
 * Real-host two-account isolation acceptance. Neither data nor credentials are
 * synthetic. Use two dedicated authorized, sanitized test identities with
 * existing distinct, marker-named resources. No mutating setup takes place.
 */
const enabled = process.env.KAREN_AUTOMATION_TWO_ACCOUNT_ACCEPTANCE === "true";
const local = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
const base = process.env.KAREN_BASE_URL;
const accounts = [
  {
    email: process.env.KAREN_UX_EMAIL,
    password: process.env.KAREN_UX_PASSWORD,
    marker: {
      task: process.env.KAREN_UX_ACCOUNT_A_TASK_MARKER,
      job: process.env.KAREN_UX_ACCOUNT_A_JOB_MARKER,
      cron: process.env.KAREN_UX_ACCOUNT_A_CRON_MARKER,
    },
  },
  {
    email: process.env.KAREN_UX_ACCOUNT_B_EMAIL,
    password: process.env.KAREN_UX_ACCOUNT_B_PASSWORD,
    marker: {
      task: process.env.KAREN_UX_ACCOUNT_B_TASK_MARKER,
      job: process.env.KAREN_UX_ACCOUNT_B_JOB_MARKER,
      cron: process.env.KAREN_UX_ACCOUNT_B_CRON_MARKER,
    },
  },
] as const;

type Kind = "task" | "job" | "cron";
const workspaces: Array<{
  kind: Kind; label: string; title: string; endpoint: string; advanced: boolean;
}> = [
  { kind: "task", label: "My tasks", title: "Task Management", endpoint: "/api/tasks/", advanced: false },
  { kind: "job", label: "Jobs", title: "Jobs", endpoint: "/api/automation/jobs/", advanced: true },
  { kind: "cron", label: "Cron Jobs", title: "Cron Job Assignments", endpoint: "/api/automation/cron", advanced: true },
];

test.use({ trace: "off", screenshot: "off", video: "off" });

function requireApprovedOrigin(): string {
  if (!base) throw new Error("KAREN_BASE_URL must be a separately approved host.");
  const url = new URL(base);
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("The approved host must be an origin without embedded credentials.");
  }
  const approvedLoopback = local && process.env.KAREN_CHAT_BOOT_ACCEPTANCE !== "1" &&
    url.protocol === "http:" && !!url.port &&
    ["127.0.0.1", "localhost"].includes(url.hostname);
  const approvedRelease = url.protocol === "https:" && !url.port;
  if (!approvedLoopback && !approvedRelease) {
    throw new Error("Only an approved HTTPS origin or explicitly authorized loopback is allowed.");
  }
  return url.origin;
}

function requireSanitizedAccounts() {
  const values = accounts.flatMap(account => [
    account.email, account.password, account.marker.task,
    account.marker.job, account.marker.cron,
  ]);
  if (values.some(value => !value || !value.trim())) {
    throw new Error("Two dedicated sanitized accounts and six existing resource markers are mandatory.");
  }
  if (accounts[0].email === accounts[1].email) {
    throw new Error("The two authenticated accounts must differ.");
  }
  for (const kind of ["task", "job", "cron"] as const) {
    if (accounts[0].marker[kind] === accounts[1].marker[kind]) {
      throw new Error(`Account-specific ${kind} markers must differ.`);
    }
  }
}

function realResponse(page: Page, endpoint: string, origin: string) {
  return page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.origin === origin && url.pathname === endpoint &&
      response.request().method() === "GET";
  }, { timeout: 30_000 });
}

function markerFromRow(kind: Kind, input: unknown): string {
  if (!input || typeof input !== "object" || Array.isArray(input)) return "";
  const record = input as Record<string, unknown>;
  const chosen = kind === "cron" ? record.taskName ?? record.name : record.name;
  return typeof chosen === "string" ? chosen : "";
}

async function inspectCurrentAccount(
  page: Page, accountIndex: 0 | 1, origin: string,
): Promise<void> {
  const account = accounts[accountIndex];
  const other = accounts[accountIndex === 0 ? 1 : 0];
  for (const workspace of workspaces) {
    const pending = realResponse(page, workspace.endpoint, origin);
    await openAutomationWorkspace(page, workspace.label, workspace.advanced);
    const response = await pending;
    expect(response.status(), `${workspace.label} must be a live authenticated 200`).toBe(200);
    const body: unknown = await response.json();
    expect(Array.isArray(body), "Backend must return a genuine list").toBe(true);
    if (!Array.isArray(body)) throw new Error("Unverified backend list.");
    const values = body.map(row => markerFromRow(workspace.kind, row));
    const ownMarker = account.marker[workspace.kind]!;
    const foreignMarker = other.marker[workspace.kind]!;
    expect(values, `Real ${workspace.kind} data must contain this account's seeded marker`).toContain(ownMarker);
    expect(values, `Real ${workspace.kind} data must exclude the other account's marker`).not.toContain(foreignMarker);

    const root = page.locator(".karen-automation-workflow");
    await expect(root.getByRole("heading", { name: workspace.title, exact: true })).toBeVisible();
    await expect(root.getByText(ownMarker, { exact: true }).first()).toBeVisible();
    await expect(root.getByText(foreignMarker, { exact: true })).toHaveCount(0);
    await expect(root.getByText(/could not be verified|Schedules unavailable/i)).toHaveCount(0);
  }
}

test("KUI-AUTOMATION: signed-out revocation and real A-to-B data isolation", async ({ page }) => {
  test.skip(!enabled, "Opt in explicitly with KAREN_AUTOMATION_TWO_ACCOUNT_ACCEPTANCE=true.");
  test.setTimeout(6 * 60_000);
  requireSanitizedAccounts();
  const origin = requireApprovedOrigin();
  await page.setViewportSize({ width: 1440, height: 900 });

  await signInApprovedKaren(page, accounts[0].email!, accounts[0].password!, {
    allowLocalLoopback: local,
  });
  expect(new URL(page.url()).origin).toBe(origin);
  await inspectCurrentAccount(page, 0, origin);

  await openAutomationWorkspace(page, "My Account", false);
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login(?:[?#]|$)/, { timeout: 30_000 });
  // Revocation is a backend fact; a login redirect alone does not prove it.
  const status = await page.evaluate(async () => {
    const response = await fetch("/api/tasks/", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
    return response.status;
  });
  expect([401, 403], "Signed-out authenticated API must deny reads").toContain(status);

  await signInApprovedKaren(page, accounts[1].email!, accounts[1].password!, {
    allowLocalLoopback: local,
  });
  expect(new URL(page.url()).origin).toBe(origin);
  await inspectCurrentAccount(page, 1, origin);
});
