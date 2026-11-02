import { expect, test } from "./fixtures/verified-search-deployment";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import type { Page } from "@playwright/test";

/**
 * The preview route previously owned this CSS, so the dashboard could render
 * an unstyled SDK and still pass preview-only acceptance. Assert the real
 * browser loaded the *nonempty same-origin* pinned vendor stylesheet.
 */
/**
 * Read canonical JSON through the *actual signed-in browser*. Playwright's
 * request context shares cookies, but cannot see Karen's localStorage Bearer
 * access token. Keep that credential inside the browser: never echo it to the
 * runner, attach it to redirects or send it to a different origin.
 */
async function readAuthorizedSameOriginJson(
  page: Page, apiPath: string,
): Promise<{ ok: boolean; body: unknown }> {
  return page.evaluate(async (path) => {
    const url = new URL(path, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) {
      throw new Error("Refusing authenticated read outside the application's API origin");
    }
    const accessToken = window.localStorage.getItem("access_token");
    const response = await window.fetch(url.pathname + url.search, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });
    return { ok: response.ok, body: response.ok ? await response.json() : null };
  }, apiPath);
}

/**
 * Model text alone is insufficient release proof: backend-saved execution
 * provenance must be bound to the precise persisted assistant turn. The
 * thread gateway already verifies this snapshot before the SDK displays it.
 * Do not infer a model from the configured preference or the chat UI.
 */
async function expectVerifiedExecutionReceipt(
  page: Page, conversationId: string, persistedAnswer: string,
): Promise<void> {
  await expect.poll(async () => {
    const { ok, body } = await readAuthorizedSameOriginJson(
      page, `/api/copilotkit/threads/${conversationId}/messages`,
    );
    if (!ok || !body || typeof body !== "object") return false;
    const response = body as Record<string, unknown>;
    if (response.threadId !== conversationId ||
        !Array.isArray(response.messages) || !Array.isArray(response.replayEvents)) return false;
    const matching = response.messages.filter((item): item is Record<string, unknown> =>
      item !== null && typeof item === "object" && !Array.isArray(item) &&
      item.role === "assistant" && item.content === persistedAnswer &&
      typeof item.id === "string" && item.id.length > 0);
    if (matching.length !== 1) return false;

    const receipts = response.replayEvents.filter((item): item is Record<string, unknown> =>
      item !== null && typeof item === "object" && !Array.isArray(item) &&
      item.type === "CUSTOM" && item.name === "karen.execution_receipt.v1" &&
      item.messageId === matching[0].id);
    if (receipts.length !== 1) return false;
    const receipt = receipts[0].value;
    if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) return false;
    const metadata = receipt as Record<string, unknown>;
    // Reject configured-only or unavailable executors. A legitimate runtime
    // fallback may change provider/model, so do not hardcode provider names.
    const required = ["actual_provider", "actual_model", "response_source"] as const;
    if (required.some(key => typeof metadata[key] !== "string" ||
        !(metadata[key] as string).trim() ||
        ["unknown", "none", "unavailable"].includes((metadata[key] as string).trim().toLowerCase()))) {
      return false;
    }
    return metadata.response_source !== "persisted_history";
  }, {
    timeout: 30_000,
    intervals: [500, 1000, 2000],
    message: "The exact saved assistant turn must have backend-verified model execution provenance",
  }).toBe(true);
}

/**
 * A matching Next.js SHA does not establish that the canonical API exists.
 * Do not send approved login credentials to a frontend whose backend is down.
 * The same fail-closed readiness contract is enforced by the workflow's
 * independent verify_deployment_revision.py before Playwright starts.
 */
async function requireLiveCanonicalBackend(page: Page, target: URL): Promise<void> {
  const response = await page.context().request.get(
    new URL("/api/health", target).toString(),
    { failOnStatusCode: false, maxRedirects: 0, timeout: 20_000 },
  );
  expect(response.status(), "Canonical API must be reachable before authenticated browser acceptance").toBe(200);
  expect(response.headers()["content-type"] ?? "").toMatch(/^application\/json(?:;|$)/i);
  expect(response.headers()["cache-control"] ?? "").toContain("no-store");
  const payload: unknown = await response.json();
  expect(payload, "Canonical backend health must contain a verified ready state").toEqual({
    status: "ok",
    backend_ready: true,
  });
}

async function expectRealCopilotKitStyles(page: Page): Promise<void> {
  const selector = 'link[rel="stylesheet"][href="/vendor/copilotkit-v2.css"]';
  await expect(page.locator(selector)).toHaveCount(1);
  await expect.poll(async () => page.evaluate((linkSelector) => {
    const link = document.querySelector<HTMLLinkElement>(linkSelector);
    if (!link?.sheet) return false;
    try {
      return link.sheet.cssRules.length > 0;
    } catch {
      return false;
    }
  }, selector), {
    timeout: 30_000,
    message: "The actual dashboard must load nonempty CopilotKit vendor CSS",
  }).toBe(true);
}


/**
 * Release-only, real-browser boot proof for the canonical CopilotKit chat.
 * Runs against an approved HTTPS deployment with a matching source revision
 * and a genuinely reachable canonical API. No route mocks or synthetic replies.
 *
 * Required when KAREN_CHAT_BOOT_ACCEPTANCE=1:
 *   KAREN_BASE_URL=<approved clean HTTPS origin>
 *   KAREN_CHAT_BOOT_REVISION=<exact expected full commit SHA>
 *   KAREN_E2E_AUTH_STATE=<preapproved storage state>, or the workflow's
 *   KAREN_UX_EMAIL and KAREN_UX_PASSWORD for approved sign-in.
 *
 * The served application must expose its canonical deployed revision at
 * /api/deployment-revision. This test fails closed if that is unavailable.
 * Never attach authenticated traces, screenshots or videos to public CI.
 */
const enabled = process.env.KAREN_CHAT_BOOT_ACCEPTANCE === "1";
const authState = process.env.KAREN_E2E_AUTH_STATE;
const expectedRevision = process.env.KAREN_CHAT_BOOT_REVISION;
const approvedUrl = process.env.KAREN_BASE_URL;
const approvedEmail = process.env.KAREN_UX_EMAIL;
const approvedPassword = process.env.KAREN_UX_PASSWORD;

if (enabled && (!(authState || (approvedEmail && approvedPassword)) || !approvedUrl || !expectedRevision ||
  !/^[0-9a-f]{40}$/i.test(expectedRevision))) {
  throw new Error(
    "Chat boot acceptance requires KAREN_BASE_URL, exact KAREN_CHAT_BOOT_REVISION and either KAREN_E2E_AUTH_STATE or approved login credentials",
  );
}

test.describe("canonical consumer chat cold-load acceptance", () => {
  test.skip(!enabled, "Set KAREN_CHAT_BOOT_ACCEPTANCE=1 for real-release proof");
  test.use({
    storageState: authState || { cookies: [], origins: [] },
    trace: "off",
    screenshot: "off",
    video: "off",
  });

  test("persists a real user message and a real assistant reply", async ({ page }) => {
    test.setTimeout(180_000);
    const target = new URL(approvedUrl!);
    const browserErrors: string[] = [];
    page.on("pageerror", error => {
      browserErrors.push(`Uncaught page error: ${error.message}`);
    });
    page.on("console", message => {
      if (message.type() === "error" &&
          /ChunkLoadError|Loading chunk|web-inspector|Failed to fetch dynamically imported module/i.test(message.text())) {
        browserErrors.push(`Console chunk error: ${message.text()}`);
      }
    });
    page.on("response", response => {
      if (response.status() >= 400 && /\/_next\/static\/chunks\//.test(response.url())) {
        browserErrors.push(`Chunk HTTP ${response.status()}: ${response.url()}`);
      }
    });
    page.on("requestfailed", failedRequest => {
      if (/\/_next\/static\/chunks\//.test(failedRequest.url())) {
        browserErrors.push(`Chunk request failed: ${failedRequest.url()}`);
      }
    });
    page.on("request", assetRequest => {
      if (/\/_next\/static\/chunks\/.*(?:copilotkit[_/-])?web-inspector/i.test(assetRequest.url())) {
        browserErrors.push("Disabled CopilotKit inspector requested a browser chunk");
      }
    });
    const revisionResponse = await page.context().request.get(new URL("/api/deployment-revision", target).toString());
    expect(revisionResponse.ok(), "The deployed revision must be available").toBe(true);
    const revision: unknown = await revisionResponse.json();
    expect((revision as Record<string, unknown>).revision).toBe(expectedRevision);
    await requireLiveCanonicalBackend(page, target);

    if (!authState) {
      await signInApprovedKaren(page, approvedEmail!, approvedPassword!);
    }
    await page.goto(new URL("/dashboard", target).toString());
    const shell = page.getByTestId("karen-copilot-consumer-chat");
    const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
    if (!(await shell.isVisible().catch(() => false)) &&
        await launch.isVisible().catch(() => false)) {
      await launch.click();
    }
    await expect(shell).toBeVisible({ timeout: 30_000 });
    await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({
      timeout: 30_000,
    });
    await expectRealCopilotKitStyles(page);

    // Never inject acceptance prompts into an arbitrary existing user thread.
    // Create a separate durable conversation through the actual user UI.
    const previousId = await shell.getAttribute("data-conversation-id");
    const newConversation = shell.getByRole("button", { name: "New conversation" });
    await expect(newConversation, "Acceptance must be able to start a dedicated conversation").toBeVisible();
    await newConversation.click();
    await expect.poll(async () => {
      const nextId = await shell.getAttribute("data-conversation-id");
      return nextId !== null && nextId !== previousId ? nextId : null;
    }, { timeout: 30_000 }).not.toBeNull();
    await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({
      timeout: 30_000,
    });
    await expectRealCopilotKitStyles(page);

    const id = await shell.getAttribute("data-conversation-id");
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    const prompt = `Karen live acceptance ${crypto.randomUUID()}: Please respond with a brief greeting.`;
    const composer = shell.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
    await expect(composer, "CopilotKit must present a usable composer").toBeVisible();
    await composer.fill(prompt);
    // Absence of "Saving draft…" alone is insufficient: it can be absent
    // before the delayed CAS save starts. Require the backend's authorized
    // draft endpoint to confirm this exact prompt before submitting.
    const draftEndpoint = `/api/conversations/${id}/draft`;
    await expect.poll(async () => {
      const { ok, body: draft } = await readAuthorizedSameOriginJson(page, draftEndpoint);
      return Boolean(ok && draft && typeof draft === "object" &&
        (draft as { text?: unknown }).text === prompt);
    }, {
      timeout: 30_000,
      intervals: [250, 500, 1000],
      message: "The canonical backend must confirm this exact saved draft before sending",
    }).toBe(true);
    await expect(shell.getByText("Saving draft to your conversation…")).toHaveCount(0, {
      timeout: 30_000,
    });
    await composer.press("Enter");

    const endpoint = `/api/conversations/${id}`;
    let persistedAnswer = "";
    await expect.poll(async () => {
      const { ok, body } = await readAuthorizedSameOriginJson(page, endpoint);
      if (!ok || !body || typeof body !== "object" ||
          !Array.isArray((body as Record<string, unknown>).messages)) {
        return false;
      }
      const messages = (body as { messages: Array<{ role?: string; content?: string }> }).messages;
      const matchingPromptIndices = messages.flatMap((message, index) =>
        message.role === "user" && message.content === prompt ? [index] : []);
      // A unique submitted turn must occur exactly once, and its immediate
      // successor must be the model reply. A reply to an unrelated later turn
      // cannot satisfy the acceptance contract.
      const promptIndex = matchingPromptIndices[0];
      const assistant = matchingPromptIndices.length === 1
        ? messages[promptIndex + 1]
        : undefined;
      const accepted = assistant?.role === "assistant" &&
        typeof assistant.content === "string" && assistant.content.trim().length > 0;
      persistedAnswer = accepted ? assistant.content! : "";
      return accepted;
    }, {
      timeout: 120_000,
      intervals: [1000, 2000, 3000],
      message: "A real user turn and subsequent assistant response must be persisted by the canonical backend",
    }).toBe(true);
    expect(persistedAnswer.trim().length).toBeGreaterThan(0);
    await expectVerifiedExecutionReceipt(page, id!, persistedAnswer);
    // A saved backend answer alone is not a functioning consumer chat.
    // The active CopilotKit view must render the real assistant response
    // before any reload, not only during a later history replay.
    await expect(
      shell.getByTestId("karen-copilot-assistant-message").filter({ hasText: persistedAnswer }).last(),
      "The live chat must render the persisted assistant reply before reload",
    ).toBeVisible({ timeout: 30_000 });

    await page.reload();
    const restored = page.getByTestId("karen-copilot-consumer-chat");
    if (!(await restored.isVisible().catch(() => false)) &&
        await launch.isVisible().catch(() => false)) {
      await launch.click();
    }
    await expect(restored).toHaveAttribute("data-conversation-id", id!);
    await expect(restored.getByTestId("karen-copilot-controlled-chat")).toBeVisible({
      timeout: 30_000,
    });
    await expectRealCopilotKitStyles(page);
    await expectVerifiedExecutionReceipt(page, id!, persistedAnswer);
    await expect(restored.getByTestId("karen-copilot-rail-unverified")).toHaveCount(0, {
      timeout: 30_000,
    });
    await expect(restored.getByText(prompt, { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(
      restored.getByTestId("karen-copilot-assistant-message").filter({ hasText: persistedAnswer }).last(),
      "The actual persisted assistant reply must be rendered after reload",
    ).toBeVisible({ timeout: 30_000 });
    expect(browserErrors, "Chat submit and restore must not cause browser or chunk errors").toEqual([]);
  });

  test("boots, restores and loads assets without an inspector chunk failure", async ({ page }) => {
    test.setTimeout(120_000);
    const target = new URL(approvedUrl!);
    const revisionResponse = await page.context().request.get(new URL("/api/deployment-revision", target).toString());
    expect(revisionResponse.ok(), "Exact deployed revision endpoint must be available").toBe(true);
    const revisionPayload: unknown = await revisionResponse.json();
    expect(revisionPayload, "Revision endpoint must return an object").toBeTruthy();
    const revision = revisionPayload as Record<string, unknown>;
    const servedSha = revision.revision ?? revision.sha ?? revision.commit_sha ?? revision.git_sha;
    expect(servedSha, "The deployed revision must equal the reviewed Git commit").toBe(expectedRevision);
    await requireLiveCanonicalBackend(page, target);

    const failures: string[] = [];
    const capturePageFailure = (error: Error) => {
      failures.push(`Page exception: ${error.message}`);
    };
    page.on("pageerror", capturePageFailure);
    page.on("console", message => {
      if (message.type() === "error" &&
          /ChunkLoadError|Loading chunk|web-inspector|Failed to fetch dynamically imported module/i.test(message.text())) {
        failures.push(`Console chunk error: ${message.text()}`);
      }
    });
    page.on("response", response => {
      if (response.status() >= 400 &&
          /\/_next\/static\/chunks\//.test(response.url())) {
        failures.push(`Chunk HTTP ${response.status()}: ${response.url()}`);
      }
    });
    page.on("requestfailed", request => {
      if (/\/_next\/static\/chunks\//.test(request.url())) {
        failures.push(`Chunk request failed: ${request.url()} ${request.failure()?.errorText ?? ""}`);
      }
    });
    page.on("request", assetRequest => {
      if (/\/_next\/static\/chunks\/.*(?:copilotkit[_/-])?web-inspector/i.test(assetRequest.url())) {
        failures.push("Disabled CopilotKit inspector requested a browser chunk");
      }
    });

    if (!authState) {
      await signInApprovedKaren(page, approvedEmail!, approvedPassword!);
    }

    let initialConversationId: string | null = null;
    for (const coldLoad of [true, false]) {
      if (coldLoad) {
        await page.goto(new URL("/dashboard", target).toString(), { waitUntil: "domcontentloaded" });
      } else {
        await page.reload({ waitUntil: "domcontentloaded" });
      }
      expect(new URL(page.url()).origin).toBe(target.origin);
      const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
      const shell = page.getByTestId("karen-copilot-consumer-chat");
      if (!(await shell.isVisible().catch(() => false)) && await launch.isVisible().catch(() => false)) {
        await launch.click();
      }
      await expect(shell, "Authenticated canonical CopilotKit chat must mount").toBeVisible({ timeout: 30_000 });
      await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({ timeout: 30_000 });
      await expectRealCopilotKitStyles(page);
      await expect(shell.getByRole("button", { name: "Find conversations" })).toBeVisible();
      await expect(shell.getByRole("button", { name: "Conversation options" })).toBeVisible();
      const conversationId = await shell.getAttribute("data-conversation-id");
      expect(conversationId, "Chat identity must be a canonical UUID").toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      );
      if (initialConversationId === null) {
        initialConversationId = conversationId;
      } else {
        expect(conversationId, "Reload must restore the same conversation identity").toBe(initialConversationId);
      }
      await page.waitForTimeout(750);
      expect(failures, "No chunk fetch errors or uncaught page exceptions are permitted").toEqual([]);
    }
  });
});
