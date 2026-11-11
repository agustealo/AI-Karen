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


/**
 * Source-only until explicitly run on a reviewed deployment. Compare two
 * real model turns carrying identical user-supplied evidence, not mock output
 * or a replay-only UI. A model may paraphrase, but must preserve both facts.
 * No screenshots, private answers, tokens or credentials are attached to CI.
 */
test("two authenticated personas preserve the same user evidence and verified model receipts", async ({ page }) => {
  test.skip(
    process.env.KAREN_KCON771_INVARIANCE_ACCEPTANCE !== "1",
    "Requires a reviewed deployment, dedicated sanitized account and two active personas",
  );
  if (!email || !password) {
    throw new Error("Two-persona acceptance requires approved sanitized credentials");
  }
  test.setTimeout(9 * 60_000);
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

  const preferencesUrl = "/api/personas/preferences/me";
  const beforeResult = await authorizedApi(page, preferencesUrl);
  expect(beforeResult.status).toBe(200);
  const before = beforeResult.body as SavedPreferences;
  assertPreference(before);
  const catalogResult = await authorizedApi(page, "/api/personas/");
  expect(catalogResult.status).toBe(200);
  const catalog = catalogResult.body as Array<{ id: string; is_active: boolean }>;
  expect(Array.isArray(catalog)).toBe(true);
  // Default Karen is not a second named persona. This source acceptance
  // requires two genuinely different active persona identities, rather than
  // silently comparing one named persona against a missing selection.
  const originalPersona = catalog.find(item => item && item.is_active &&
    typeof item.id === "string" && item.id === before.active_persona_id);
  expect(originalPersona, "Two-persona proof requires a named active starting persona")
    .toBeDefined();
  const alternative = catalog.find(item => item && item.is_active &&
    typeof item.id === "string" && item.id.length > 0 &&
    item.id !== before.active_persona_id);
  expect(alternative, "Two-persona proof requires a second named active persona")
    .toBeDefined();
  if (!originalPersona || !alternative) {
    throw new Error("A sanitized account with two active named personas is required");
  }

  const sampleId = "KCON771-" + Date.now().toString(36).toUpperCase();
  const evidencePrompt =
    `Use only the two facts in this user message. The verified sample ID is ${sampleId}; ` +
    "the verified measurement is 42.5 units. State the ID and measurement exactly, " +
    "without adding any other measurements.";
  const actualReceipts: Array<{ provider: string; model: string; source: string }> = [];
  let selectionChanged = false;

  try {
    for (const desiredPersona of [before.active_persona_id, alternative.id]) {
      const selector = shell.getByRole("combobox", { name: "Active Karen persona" });
      await expect(selector).toHaveValue(
        desiredPersona === alternative.id ? before.active_persona_id ?? "" : desiredPersona ?? "",
      );

      let conversationId: string | null = null;
      if (desiredPersona !== before.active_persona_id) {
        const savedResponse = page.waitForResponse(response =>
          response.request().method() === "PUT" &&
          new URL(response.url()).pathname === preferencesUrl,
          { timeout: 20_000 },
        );
        await selector.selectOption(desiredPersona ?? "");
        const receiptResponse = await savedResponse;
        expect(receiptResponse.status()).toBe(200);
        const persisted = await receiptResponse.json() as SavedPreferences;
        expect(persisted.active_persona_id).toBe(desiredPersona);
        expect(persisted.revision).toBe(before.revision + 1);
        selectionChanged = true;
        const start = shell.getByRole("button", {
          name: "Start new conversation for selected persona",
        });
        await expect(start).toBeVisible();
        const initialId = await shell.getAttribute("data-conversation-id");
        await start.click();
        await expect.poll(async () => {
          const next = await shell.getAttribute("data-conversation-id");
          return next && next !== initialId ? next : null;
        }, { timeout: 30_000 }).not.toBeNull();
        conversationId = await shell.getAttribute("data-conversation-id");
      } else {
        const initialId = await shell.getAttribute("data-conversation-id");
        await shell.getByRole("button", { name: "New conversation" }).click();
        await expect.poll(async () => {
          const next = await shell.getAttribute("data-conversation-id");
          return next && next !== initialId ? next : null;
        }, { timeout: 30_000 }).not.toBeNull();
        conversationId = await shell.getAttribute("data-conversation-id");
      }
      expect(conversationId).toMatch(UUID);
      await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible();
      // Re-read the backend immediately before each inference. A selector
      // value or a successful PUT response alone cannot prove current persona.
      const confirmedSelection = await authorizedApi(page, preferencesUrl);
      expect(confirmedSelection.status).toBe(200);
      const effectivePreferences = confirmedSelection.body as SavedPreferences;
      expect(effectivePreferences.active_persona_id).toBe(desiredPersona);
      expect(effectivePreferences.revision).toBe(
        desiredPersona === before.active_persona_id ? before.revision : before.revision + 1,
      );

      const composer = shell.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
      await expect(composer).toBeVisible();
      const outbound: string[] = [];
      let persistedAnswer = "";
      let persistedAssistantId = "";
      const onRequest = (request: { method(): string; url(): string }): void => {
        if (request.method() !== "POST") return;
        const path = new URL(request.url()).pathname;
        if (path === "/api/copilotkit/agent/default/run" ||
            path === "/api/chat/ag-ui" || path === "/api/chat/stream") {
          outbound.push(path);
        }
      };
      page.on("request", onRequest);
      try {
        await composer.fill(evidencePrompt);
        await composer.press("Enter");
        await expect.poll(async () => {
          const result = await authorizedApi(
            page, `/api/copilotkit/threads/${conversationId}/messages`,
          );
          if (result.status !== 200 || !result.body ||
              typeof result.body !== "object") return false;
          const transcript = result.body as Record<string, unknown>;
          if (transcript.threadId !== conversationId ||
              !Array.isArray(transcript.messages) ||
              !Array.isArray(transcript.replayEvents)) return false;
          const messages = transcript.messages as Array<Record<string, unknown>>;
          const positions = messages.flatMap((item, index) =>
            item.role === "user" && item.content === evidencePrompt ? [index] : []);
          if (positions.length !== 1) return false;
          const answer = messages[positions[0] + 1];
          if (!answer || answer.role !== "assistant" ||
              typeof answer.id !== "string" ||
              typeof answer.content !== "string" || !answer.content.trim()) return false;
          const receipts = (transcript.replayEvents as Array<Record<string, unknown>>)
            .filter(event => event.type === "CUSTOM" &&
              event.name === "karen.execution_receipt.v1" &&
              event.messageId === answer.id);
          if (receipts.length !== 1 || !receipts[0].value ||
              typeof receipts[0].value !== "object") return false;
          const receipt = receipts[0].value as Record<string, unknown>;
          if (!["actual_provider", "actual_model", "response_source"].every(key =>
            typeof receipt[key] === "string" &&
            (receipt[key] as string).trim().length > 0 &&
            !["none", "unknown", "unavailable"].includes(
              (receipt[key] as string).trim().toLowerCase(),
            ))) return false;
          if (!/(?:^|[_-])(?:model|inference|generation)(?:[_-]|$)/i.test(
            receipt.response_source as string,
          )) return false;
          // A saved preference does not establish what persona the runtime
          // actually admitted. Require the authenticated frozen snapshot in
          // the receipt tied to this exact persisted assistant turn.
          if (receipt.persona_id !== desiredPersona ||
              receipt.persona_selection_revision !== effectivePreferences.revision) {
            return false;
          }
          // A nonempty reply is not enough. Both supplied facts must survive.
          if (!answer.content.includes(sampleId) ||
              !answer.content.includes("42.5")) return false;
          persistedAnswer = answer.content;
          persistedAssistantId = answer.id;
          actualReceipts.push({
            provider: receipt.actual_provider as string,
            model: receipt.actual_model as string,
            source: receipt.response_source as string,
          });
          return true;
        }, {
          timeout: 120_000, intervals: [1000, 2000, 3000],
          message: "One real backend-saved answer must preserve both facts and carry a model receipt",
        }).toBe(true);
        expect(persistedAnswer).toContain(sampleId);
        expect(persistedAnswer).toContain("42.5");
        await expect(
          shell.getByTestId("karen-copilot-assistant-message")
            .filter({ hasText: persistedAnswer }).last(),
          "The actual model answer must render live before consulting replay",
        ).toBeVisible({ timeout: 30_000 });

        // Reload must not rerun the prompt or fabricate a replacement answer.
        // Both the browser surface and the backend receipt must still refer
        // to the exact original persisted assistant turn after cold reload.
        await page.reload();
        const restoredShell = page.getByTestId("karen-copilot-consumer-chat");
        const reopen = page.getByRole("button", { name: "Ask Karen", exact: true });
        if (!(await restoredShell.isVisible().catch(() => false)) &&
            await reopen.isVisible().catch(() => false)) {
          await reopen.click();
        }
        await expect(restoredShell).toHaveAttribute(
          "data-conversation-id", conversationId!, { timeout: 30_000 },
        );
        await expect(
          restoredShell.getByTestId("karen-copilot-assistant-message")
            .filter({ hasText: persistedAnswer }).last(),
          "Reload must display the same persisted model answer",
        ).toBeVisible({ timeout: 30_000 });
        const restoredResult = await authorizedApi(
          page, `/api/copilotkit/threads/${conversationId}/messages`,
        );
        expect(restoredResult.status).toBe(200);
        const restoredTranscript = restoredResult.body as {
          threadId: string;
          messages: Array<{ id: string; role: string; content: string }>;
          replayEvents: Array<{ type: string; name: string; messageId: string; value: unknown }>;
        };
        expect(restoredTranscript.threadId).toBe(conversationId);
        const savedTurns = restoredTranscript.messages.filter(message =>
          message.id === persistedAssistantId && message.role === "assistant" &&
          message.content === persistedAnswer);
        expect(savedTurns, "Cold reload must preserve exactly the same saved assistant turn")
          .toHaveLength(1);
        expect(restoredTranscript.replayEvents.filter(event =>
          event.type === "CUSTOM" &&
          event.name === "karen.execution_receipt.v1" &&
          event.messageId === persistedAssistantId),
        "Cold reload must preserve exactly one receipt for the original assistant turn")
          .toHaveLength(1);
      } finally {
        page.off("request", onRequest);
      }
      expect(outbound, "Send and reload must not invoke more than one model execution")
        .toHaveLength(1);
    }
    expect(actualReceipts).toHaveLength(2);
    // Fallback routing may legitimately differ. Never claim identical models
    // merely because the styles differ; each receipt must attest its executor.
    expect(actualReceipts.every(r => Boolean(r.provider && r.model && r.source))).toBe(true);
  } finally {
    if (selectionChanged) {
      const latestResult = await authorizedApi(page, preferencesUrl);
      expect(latestResult.status).toBe(200);
      const latest = latestResult.body as SavedPreferences;
      expect(latest.active_persona_id, "Never overwrite a concurrent persona update")
        .toBe(alternative.id);
      const restore = await authorizedApi(page, preferencesUrl, "PUT", {
        active_persona_id: before.active_persona_id,
        expected_revision: latest.revision,
      });
      expect(restore.status).toBe(200);
      const restored = restore.body as SavedPreferences;
      expect(restored.active_persona_id).toBe(before.active_persona_id);
      expect(restored.revision).toBe(latest.revision + 1);
    }
    // These conversations contain real evidence and model output. Do not
    // silently delete them, even from an approved sanitized account.
  }
});
