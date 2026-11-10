import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import type { Page } from "@playwright/test";

// This test mutates only an explicitly approved sanitized account. It never
// intercepts backend replies or exports authenticated browser artifacts.
test.use({ trace: "off", screenshot: "off", video: "off" });
test.setTimeout(120_000);

const required = process.env.KAREN_PERSONA_HANDOFF_ACCEPTANCE_REQUIRED === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type SavedPreferences = {
  revision: number;
  active_persona_id: string | null;
  show_persona_selector: boolean;
};

function assertPreference(value: SavedPreferences): void {
  expect(Number.isSafeInteger(value.revision)).toBe(true);
  expect(value.revision).toBeGreaterThanOrEqual(0);
  expect(value.show_persona_selector).toBe(true);
}

async function requireReviewedBackend(page: Page): Promise<URL> {
  const origin = process.env.KAREN_BASE_URL;
  const expected = process.env.KAREN_CHAT_BOOT_REVISION;
  if (!origin || !expected || !/^[0-9a-f]{40}$/i.test(expected)) {
    throw new Error("Persona handoff requires an approved origin and exact reviewed revision");
  }
  const target = new URL(origin);
  if (target.protocol !== "https:" || target.port || target.username ||
      target.password || target.pathname !== "/" || target.search || target.hash) {
    throw new Error("Persona handoff requires an approved clean HTTPS origin");
  }
  const revisionResponse = await page.context().request.get(
    new URL("/api/deployment-revision", target).toString(),
    { failOnStatusCode: false, maxRedirects: 0, timeout: 20_000 },
  );
  expect(revisionResponse.status()).toBe(200);
  const deployed = await revisionResponse.json() as Record<string, unknown>;
  expect(deployed.revision ?? deployed.sha ?? deployed.commit_sha ?? deployed.git_sha)
    .toBe(expected);

  const healthResponse = await page.context().request.get(
    new URL("/api/health", target).toString(),
    { failOnStatusCode: false, maxRedirects: 0, timeout: 20_000 },
  );
  expect(healthResponse.status()).toBe(200);
  expect(healthResponse.headers()["content-type"] ?? "").toMatch(/^application\/json(?:;|$)/i);
  expect(healthResponse.headers()["cache-control"] ?? "").toContain("no-store");
  expect(await healthResponse.json()).toEqual({ status: "ok", backend_ready: true });
  return target;
}

/** Keep localStorage Bearer material inside the approved, signed-in origin. */
async function authorizedApi(
  page: Page,
  pathname: string,
  method: "GET" | "PUT" | "DELETE" = "GET",
  data?: unknown,
): Promise<{ status: number; body: unknown }> {
  return page.evaluate(async ({ pathname, method, data }) => {
    const url = new URL(pathname, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/") ||
        url.pathname + url.search !== pathname) {
      throw new Error("Refusing persona acceptance API access outside the current origin");
    }
    const token = window.localStorage.getItem("access_token");
    const response = await window.fetch(url.pathname + url.search, {
      method,
      redirect: "error",
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(data === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(data === undefined ? {} : { body: JSON.stringify(data) }),
    });
    return {
      status: response.status,
      body: response.status === 204 ? null : await response.json(),
    };
  }, { pathname, method, data });
}

test("persona switch offers a real CopilotKit conversation without hidden inference", async ({ page }) => {
  test.skip(!required, "Only run with approved sanitized credentials and reviewed deployment");
  if (!email || !password) {
    throw new Error("Approved persona handoff requires sanitized credentials");
  }
  // No approved credentials are submitted until the reviewed deployment and
  // canonical API have both been verified.
  const target = await requireReviewedBackend(page);
  await signInApprovedKaren(page, email, password);
  await page.goto(new URL("/dashboard", target).toString(), { waitUntil: "domcontentloaded" });
  const shell = page.getByTestId("karen-copilot-consumer-chat");
  const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
  if (!(await shell.isVisible().catch(() => false)) &&
      await launch.isVisible().catch(() => false)) {
    await launch.click();
  }
  await expect(shell).toBeVisible({ timeout: 30_000 });
  await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible();
  const originalConversation = await shell.getAttribute("data-conversation-id");
  expect(originalConversation).toMatch(UUID);

  const preferencesUrl = "/api/personas/preferences/me";
  const beforeResponse = await authorizedApi(page, preferencesUrl);
  expect(beforeResponse.status).toBe(200);
  const before = beforeResponse.body as SavedPreferences;
  assertPreference(before);
  const catalogResponse = await authorizedApi(page, "/api/personas/");
  expect(catalogResponse.status).toBe(200);
  const catalog = catalogResponse.body as Array<{
    id: string; name: string; is_active: boolean;
  }>;
  expect(Array.isArray(catalog)).toBe(true);
  const alternative = catalog.find(persona =>
    persona && persona.is_active === true && typeof persona.id === "string" &&
    persona.id.length > 0 && persona.id !== before.active_persona_id
  );
  expect(alternative, "Sanitized account needs a second active persona").toBeDefined();
  if (!alternative) return;

  const inferenceRequests: string[] = [];
  page.context().on("request", request => {
    if (request.method() !== "POST") return;
    const path = new URL(request.url()).pathname;
    if (path === "/api/chat" || path === "/api/chat/stream" ||
        path === "/api/chat/ag-ui" || path === "/api/copilotkit/agent/default/run") {
      inferenceRequests.push(path);
    }
  });

  let createdConversationId: string | null = null;
  try {
    const selector = shell.getByRole("combobox", { name: "Active Karen persona" });
    await expect(selector).toHaveValue(before.active_persona_id ?? "");

    const confirmedSave = page.waitForResponse(response =>
      response.request().method() === "PUT" &&
      new URL(response.url()).pathname === preferencesUrl,
      { timeout: 20_000 },
    );
    await selector.selectOption(alternative.id);
    const savedResponse = await confirmedSave;
    expect(savedResponse.status()).toBe(200);
    const saved = await savedResponse.json() as SavedPreferences;
    expect(saved.revision).toBe(before.revision + 1);
    expect(saved.active_persona_id).toBe(alternative.id);
    await expect(selector).toHaveValue(alternative.id);

    const start = shell.getByRole("button", {
      name: "Start new conversation for selected persona",
    });
    await expect(start).toBeVisible();
    await expect(shell.getByText(
      "Persona selection saved. To keep conversations separate, start a new thread before sending.",
    )).toBeVisible();
    expect(inferenceRequests, "Persona switch must not invoke a model").toEqual([]);

    const created = page.waitForResponse(response =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.startsWith("/api/conversations/ensure-session/"),
      { timeout: 20_000 },
    );
    await start.click();
    const createdResponse = await created;
    expect(createdResponse.status()).toBe(200);
    const receipt = await createdResponse.json() as { id: string; messages?: unknown[] };
    expect(receipt.id).toMatch(UUID);
    expect(receipt.id).not.toBe(originalConversation);
    createdConversationId = receipt.id;
    await expect(shell).toHaveAttribute("data-conversation-id", receipt.id);
    await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible();
    await expect(shell.getByRole("button", {
      name: "Start new conversation for selected persona",
    })).toHaveCount(0);

    const owned = await authorizedApi(
      page, "/api/conversations/" + encodeURIComponent(createdConversationId),
    );
    expect(owned.status, "Thread must be readable from the owner-scoped API").toBe(200);
    const conversation = owned.body as { id: string; messages?: unknown[] };
    expect(conversation.id).toBe(createdConversationId);
    expect(conversation.messages ?? []).toEqual([]);
    expect(inferenceRequests, "Creating the thread must not invoke a model").toEqual([]);
  } finally {
    // Revision-fenced cleanup must not overwrite concurrent edits from another tab.
    const nowResponse = await authorizedApi(page, preferencesUrl);
    expect(nowResponse.status).toBe(200);
    const now = nowResponse.body as SavedPreferences;
    expect(now.active_persona_id, "Do not overwrite another persona switch")
      .toBe(alternative.id);
    const restoredResponse = await authorizedApi(page, preferencesUrl, "PUT", {
      active_persona_id: before.active_persona_id,
      expected_revision: now.revision,
    });
    expect(restoredResponse.status).toBe(200);
    const restored = restoredResponse.body as SavedPreferences;
    expect(restored.active_persona_id).toBe(before.active_persona_id);
    expect(restored.revision).toBe(now.revision + 1);

    if (createdConversationId) {
      const existing = await authorizedApi(
        page, "/api/conversations/" + encodeURIComponent(createdConversationId),
      );
      expect(existing.status).toBe(200);
      const value = existing.body as { messages?: unknown[] };
      expect(value.messages ?? [], "Never delete a conversation with real content").toEqual([]);
      const deleted = await authorizedApi(
        page, "/api/conversations/" + encodeURIComponent(createdConversationId), "DELETE",
      );
      expect([200, 204]).toContain(deleted.status);
    }
  }
});
