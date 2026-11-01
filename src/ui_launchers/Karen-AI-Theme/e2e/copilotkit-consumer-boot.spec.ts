import { expect, test } from "@playwright/test";

/**
 * Release-only, real-browser boot proof for the canonical CopilotKit chat.
 * It runs on any approved local/Docker or remote deployment. No route mocks,
 * source-generated messages, Vercel credentials, or external team membership.
 *
 * Required when KAREN_CHAT_BOOT_ACCEPTANCE=1:
 *   KAREN_BASE_URL=http://localhost:8010
 *   KAREN_E2E_AUTH_STATE=/secure/path/authorized-storage-state.json
 *   KAREN_CHAT_BOOT_REVISION=<exact expected full commit SHA>
 *
 * The served application must expose its canonical deployed revision at
 * /api/deployment-revision. This test fails closed if that is unavailable.
 * Never attach authenticated traces, screenshots or videos to public CI.
 */
const enabled = process.env.KAREN_CHAT_BOOT_ACCEPTANCE === "1";
const authState = process.env.KAREN_E2E_AUTH_STATE;
const expectedRevision = process.env.KAREN_CHAT_BOOT_REVISION;
const approvedUrl = process.env.KAREN_BASE_URL;

if (enabled && (!authState || !approvedUrl || !expectedRevision ||
  !/^[0-9a-f]{40}$/i.test(expectedRevision))) {
  throw new Error(
    "Chat boot acceptance requires KAREN_BASE_URL, KAREN_E2E_AUTH_STATE and an exact 40-character KAREN_CHAT_BOOT_REVISION",
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

  test("persists a real user message and a real assistant reply", async ({ page, request }) => {
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
    const revisionResponse = await request.get(new URL("/api/deployment-revision", target).toString());
    expect(revisionResponse.ok(), "The deployed revision must be available").toBe(true);
    const revision: unknown = await revisionResponse.json();
    expect((revision as Record<string, unknown>).revision).toBe(expectedRevision);

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

    const id = await shell.getAttribute("data-conversation-id");
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    const prompt = `Karen live acceptance ${crypto.randomUUID()}: Please respond with a brief greeting.`;
    const composer = shell.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
    await expect(composer, "CopilotKit must present a usable composer").toBeVisible();
    await composer.fill(prompt);
    // The persisted draft gate must finish before the user can send.
    await expect(shell.getByText("Saving draft to your conversation…")).toHaveCount(0, {
      timeout: 30_000,
    });
    await composer.press("Enter");

    const endpoint = new URL(`/api/conversations/${id}`, target).toString();
    let persistedAnswer = "";
    await expect.poll(async () => {
      const response = await request.get(endpoint, { failOnStatusCode: false });
      if (!response.ok()) return false;
      const body: unknown = await response.json();
      if (!body || typeof body !== "object" || !Array.isArray((body as Record<string, unknown>).messages)) {
        return false;
      }
      const messages = (body as { messages: Array<{ role?: string; content?: string }> }).messages;
      const submitted = messages.some(message => message.role === "user" && message.content === prompt);
      const promptIndex = messages.findIndex(message => message.role === "user" && message.content === prompt);
      const assistant = promptIndex >= 0
        ? messages.slice(promptIndex + 1).find(message => message.role === "assistant" &&
            typeof message.content === "string" && message.content.trim().length > 0)
        : undefined;
      persistedAnswer = assistant?.content ?? "";
      return submitted && Boolean(assistant);
    }, {
      timeout: 120_000,
      intervals: [1000, 2000, 3000],
      message: "A real user turn and subsequent assistant response must be persisted by the canonical backend",
    }).toBe(true);
    expect(persistedAnswer.trim().length).toBeGreaterThan(0);

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
    await expect(restored.getByText(prompt, { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(
      restored.getByText(persistedAnswer, { exact: false }).first(),
      "The actual persisted assistant reply must be rendered after reload",
    ).toBeVisible({ timeout: 30_000 });
    expect(browserErrors, "Chat submit and restore must not cause browser or chunk errors").toEqual([]);
  });

  test("boots, restores and loads assets without an inspector chunk failure", async ({ page, request }) => {
    test.setTimeout(120_000);
    const target = new URL(approvedUrl!);
    const revisionResponse = await request.get(new URL("/api/deployment-revision", target).toString());
    expect(revisionResponse.ok(), "Exact deployed revision endpoint must be available").toBe(true);
    const revisionPayload: unknown = await revisionResponse.json();
    expect(revisionPayload, "Revision endpoint must return an object").toBeTruthy();
    const revision = revisionPayload as Record<string, unknown>;
    const servedSha = revision.revision ?? revision.sha ?? revision.commit_sha ?? revision.git_sha;
    expect(servedSha, "The deployed revision must equal the reviewed Git commit").toBe(expectedRevision);

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
