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
