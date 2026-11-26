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
    await expect(root.getByText(ownMarker, { exact: false }).first()).toBeVisible();
    await expect(root.getByText(foreignMarker, { exact: false })).toHaveCount(0);
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

/**
 * ARM-05C.5B: real personal Mission Control readback, using two dedicated
 * non-admin accounts in the same tenant and pre-existing terminal runs.
 * No execution creation, receipt seeding, approval or cancellation.
 */
const participationEnabled = process.env.KAREN_SPECIALIST_PARTICIPATION_ACCEPTANCE === "true";
const participationRunIds = [
  process.env.KAREN_UX_ACCOUNT_A_PARTICIPATION_RUN_ID,
  process.env.KAREN_UX_ACCOUNT_B_PARTICIPATION_RUN_ID,
] as const;
const personalRunsPath = "/api/agent-runtime/my-runs";
const phases = {
  started: "Method entered",
  completed: "Invocation returned",
  failed: "Invocation failed",
  interrupted: "Invocation interrupted",
  skipped: "Invocation skipped",
} as const;
type ParticipationRow = {
  receipt_id: string;
  step_id: string;
  specialist_id: string;
  phase: keyof typeof phases;
  observed_at: string;
};
type ParticipationReadback = {
  run_id: string;
  evidence_status: "recorded";
  receipts: ParticipationRow[];
  truncated: false;
  response_source: "postgres_outcome_records";
};

function participationPath(runId: string): string {
  return personalRunsPath + "/" + encodeURIComponent(runId) + "/participation";
}

function hasExactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
}

// Validate the raw wire payload before casting or comparing. Never include
// unexpected fields or their values in a diagnostic.
function parseParticipation(value: unknown, runId: string): ParticipationReadback {
  if (!hasExactKeys(value, ["run_id", "evidence_status", "receipts", "truncated", "response_source"])
      || value.run_id !== runId || value.response_source !== "postgres_outcome_records"
      || value.evidence_status !== "recorded" || value.truncated !== false
      || !Array.isArray(value.receipts) || value.receipts.length === 0 || value.receipts.length > 100) {
    throw new Error("Invalid or unexpected participation envelope");
  }
  const ids = new Set<string>();
  let terminal = false;
  for (const row of value.receipts) {
    if (!hasExactKeys(row, ["receipt_id", "step_id", "specialist_id", "phase", "observed_at"])
        || typeof row.receipt_id !== "string"
        || !/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(row.receipt_id)
        || ids.has(row.receipt_id)
        || typeof row.specialist_id !== "string" || !row.specialist_id.trim()
        || typeof row.step_id !== "string" || !row.step_id.trim()
        || typeof row.phase !== "string" || !Object.prototype.hasOwnProperty.call(phases, row.phase)
        || typeof row.observed_at !== "string" || !Number.isFinite(Date.parse(row.observed_at))) {
      throw new Error("Invalid or unexpected participation receipt");
    }
    ids.add(row.receipt_id);
    terminal ||= row.phase !== "started";
  }
  if (!terminal) throw new Error("Terminal observation fixture required");
  return value as ParticipationReadback;
}

function sameParticipation(left: ParticipationReadback, right: ParticipationReadback): boolean {
  return left.run_id === right.run_id && left.receipts.length === right.receipts.length
    && left.receipts.every((row, index) => {
      const other = right.receipts[index];
      return row.receipt_id === other.receipt_id && row.step_id === other.step_id
        && row.specialist_id === other.specialist_id && row.phase === other.phase
        && row.observed_at === other.observed_at;
    });
}

async function readParticipation(page: Page, origin: string, runId: string): Promise<ParticipationReadback> {
  const response = await page.request.get(origin + participationPath(runId), { maxRedirects: 0 });
  expect(response.status(), "Owner participation read must return 200").toBe(200);
  return parseParticipation(await response.json(), runId);
}

// Pure negative control: synthetic test-only values, no authenticated host.
test("ARM-05C.5B rejects overbroad receipt projections", () => {
  const row = {
    receipt_id: "00000000-0000-5000-8000-000000000001",
    step_id: "step", specialist_id: "specialist", phase: "completed",
    observed_at: "2026-01-01T00:00:00Z",
  };
  const envelope = {
    run_id: "run", evidence_status: "recorded", receipts: [row],
    truncated: false, response_source: "postgres_outcome_records",
  };
  expect(parseParticipation(envelope, "run").receipts).toHaveLength(1);
  expect(() => parseParticipation({ ...envelope, metadata: "test-only" }, "run"))
    .toThrow("Invalid or unexpected participation envelope");
  expect(() => parseParticipation({ ...envelope, receipts: [{ ...row, payload: "test-only" }] }, "run"))
    .toThrow("Invalid or unexpected participation receipt");
  expect(() => parseParticipation({ ...envelope, receipts: [row, row] }, "run"))
    .toThrow("Invalid or unexpected participation receipt");
});

async function verifyParticipationProjection(
  page: Page, origin: string, own: string, foreign: string, expected: ParticipationReadback,
): Promise<void> {
  const listResponse = realResponse(page, personalRunsPath, origin);
  await openAutomationWorkspace(page, "Agents", true);
  const response = await listResponse;
  expect(response.status(), "Personal execution history must be authenticated").toBe(200);
  const body = await response.json() as { runs: Array<{ run_id: string; status: string }>; total: number };
  expect(Array.isArray(body.runs) && body.total === body.runs.length).toBe(true);
  expect(body.runs.some(run => run.run_id === own && ["completed", "failed", "cancelled", "canceled", "succeeded"].includes(run.status.toLowerCase()))).toBe(true);
  expect(body.runs.some(run => run.run_id === foreign), "Foreign run must not appear in personal history").toBe(false);
  const root = page.getByTestId("agent-runtime-page");
  await expect(root.getByRole("heading", { name: "Mission Control", exact: true })).toBeVisible();
  await expect(root.getByRole("heading", { name: "Mission history", exact: true })).toBeVisible();
  const list = root.locator('[aria-label="Execution list"]');
  await expect(list.getByText(own, { exact: true })).toBeVisible();
  await expect(list.getByText(foreign, { exact: true })).toHaveCount(0);
  const pending = realResponse(page, participationPath(own), origin);
  await list.getByRole("button").filter({ has: page.getByText(own, { exact: true }) }).click();
  const observed = await pending;
  expect(observed.status()).toBe(200);
  // Compare the actual UI request with a separate authenticated read.
  expect(sameParticipation(parseParticipation(await observed.json(), own), expected),
    "UI request must match independent receipt readback").toBe(true);
  const region = root.getByRole("region", { name: "Recorded specialist participation" });
  await expect(region).toBeVisible();
  await expect(region.getByText(/do not prove inference, external actions, or overall task success/)).toBeVisible();
  const rows = region.getByRole("listitem");
  await expect(rows).toHaveCount(expected.receipts.length);
  for (const [index, row] of expected.receipts.entries()) {
    const item = rows.nth(index);
    await expect(item.getByText(row.specialist_id + " · " + phases[row.phase], { exact: true })).toBeVisible();
    await expect(item.getByText("Step: " + row.step_id, { exact: true })).toBeVisible();
    await expect(item.locator("time")).toHaveAttribute("datetime", row.observed_at);
  }
}

test("ARM-05C.5B real participation receipts survive reload and deny a second account", async ({ page }) => {
  test.skip(!participationEnabled, "Opt in with KAREN_SPECIALIST_PARTICIPATION_ACCEPTANCE=true.");
  test.setTimeout(6 * 60_000);
  const origin = requireApprovedOrigin();
  const [a, b] = participationRunIds;
  if (!a || !b || a === b || !/^[A-Za-z0-9_-]{1,128}$/.test(a) || !/^[A-Za-z0-9_-]{1,128}$/.test(b)
      || accounts.some(account => !account.email?.trim() || !account.password)
      || accounts[0].email?.trim().toLowerCase() === accounts[1].email?.trim().toLowerCase()) {
    throw new Error("Two distinct sanitized accounts and two distinct terminal run IDs are mandatory.");
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  const forbidden: string[] = [];
  page.context().on("request", request => {
    const url = new URL(request.url());
    if (url.origin !== origin || ["GET", "HEAD", "OPTIONS"].includes(request.method())) return;
    if (["/api/copilotkit/agent/default/run", "/api/chat", "/api/chat/ag-ui", "/api/chat/stream"].includes(url.pathname)
        || url.pathname.startsWith("/api/agent-runtime/") || url.pathname.startsWith("/api/admin/agents/")) {
      forbidden.push(request.method());
    }
  });
  let firstIdentity: { user_id: string; tenant_id: string } | undefined;
  for (const [index, own, foreign] of [[0, a, b], [1, b, a]] as const) {
    await signInApprovedKaren(page, accounts[index].email!, accounts[index].password!, { allowLocalLoopback: local });
    const identityResponse = await page.request.get(origin + "/api/auth/me", { maxRedirects: 0 });
    expect(identityResponse.status()).toBe(200);
    const identity = await identityResponse.json() as { user_id: string; tenant_id: string; roles: string[] };
    expect(typeof identity.user_id === "string" && identity.user_id.length > 0).toBe(true);
    expect(typeof identity.tenant_id === "string" && !["", "default", "dev-tenant"].includes(identity.tenant_id.toLowerCase())).toBe(true);
    expect(Array.isArray(identity.roles) && !identity.roles.includes("admin")).toBe(true);
    if (index === 0) firstIdentity = identity;
    else {
      expect(identity.user_id !== firstIdentity?.user_id).toBe(true);
      expect(identity.tenant_id === firstIdentity?.tenant_id, "Prove same-tenant owner isolation").toBe(true);
    }
    const denied = await page.request.get(origin + participationPath(foreign), { maxRedirects: 0 });
    expect(denied.status(), "Authenticated non-owner must receive 404").toBe(404);
    const expected = await readParticipation(page, origin, own);
    await verifyParticipationProjection(page, origin, own, foreign, expected);
    // Reopen after a fresh document load; selection persistence is not claimed.
    await page.goto(origin + "/dashboard");
    expect(sameParticipation(await readParticipation(page, origin, own), expected),
      "Durable receipt readback must survive reload").toBe(true);
    await verifyParticipationProjection(page, origin, own, foreign, expected);
    await openAutomationWorkspace(page, "My Account", false);
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page).toHaveURL(/\/login(?:[?#]|$)/, { timeout: 30_000 });
    const signedOut = await page.request.get(origin + participationPath(own), { maxRedirects: 0 });
    expect([401, 403], "Signed-out principal must not read participation").toContain(signedOut.status());
  }
  expect(forbidden, "Readback must not submit inference or mutate executions").toEqual([]);
});
