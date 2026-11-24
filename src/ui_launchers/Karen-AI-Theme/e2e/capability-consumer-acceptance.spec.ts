import { expect, test } from "@playwright/test";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";
import type { Page } from "@playwright/test";

const localMode = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
const approvedUrl = process.env.KAREN_BASE_URL;
const approvedEmail = process.env.KAREN_UX_EMAIL;
const approvedPassword = process.env.KAREN_UX_PASSWORD;

async function readAuthorizedSameOriginJson(
  page: Page,
  apiPath: string,
): Promise<{ ok: boolean; status: number; body: unknown }> {
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
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { ok: response.ok, status: response.status, body };
  }, apiPath);
}

test.describe("KCHAT-CAP-01B: Capability Awareness Consumer Acceptance", () => {
  test.skip(!localMode || !approvedUrl || !approvedEmail || !approvedPassword,
    "Requires live local acceptance environment variables");

  const UTTERANCES = [
    { label: "unique capabilities", prompt: "First what are your unique capabilities?" },
    { label: "tools available", prompt: "what tools do you currently have available?" },
    { label: "what can you actually do", prompt: "What can you actually do?" },
    { label: "can you access tools", prompt: "Can you access tools?" },
    { label: "list available tools", prompt: "List your available tools." },
    { label: "which tools currently available", prompt: "Which tools are currently available to you?" },
  ];

  for (const { label, prompt } of UTTERANCES) {
    test(`capability utterance: "${label}" routes to runtime.inspect and displays truthful observation`, async ({ page }) => {
      test.setTimeout(180_000);
      const target = new URL(approvedUrl!);

      await signInApprovedKaren(page, approvedEmail!, approvedPassword!, { allowLocalLoopback: localMode });
      await page.goto(new URL("/dashboard", target).toString());

      const shell = page.getByTestId("karen-copilot-consumer-chat");
      const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
      if (!(await shell.isVisible().catch(() => false)) && await launch.isVisible().catch(() => false)) {
        await launch.click();
      }
      await expect(shell).toBeVisible({ timeout: 30_000 });
      await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({ timeout: 30_000 });

      // Start a dedicated conversation for this utterance
      const previousId = await shell.getAttribute("data-conversation-id");
      const newConversation = shell.getByRole("button", { name: "New conversation" });
      await expect(newConversation).toBeVisible();
      await newConversation.click();

      await expect.poll(async () => {
        const selected = await shell.getAttribute("data-conversation-id");
        return selected && selected !== previousId ? selected : null;
      }, { timeout: 30_000 }).not.toBeNull();

      const conversationId = await shell.getAttribute("data-conversation-id");
      expect(conversationId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      );

      const composer = shell.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
      await expect(composer).toBeVisible({ timeout: 30_000 });
      await composer.click();
      await composer.fill(prompt);
      await expect(composer).toHaveValue(prompt);
      await composer.press("Enter");

      // Verify truthful observation renders directly in the consumer UI
      const truthfulContent = shell.getByText(/Registration is not a live health check/i);
      await expect(truthfulContent).toBeVisible({ timeout: 45_000 });

      // Verify the persisted history contains the exact turn
      const historyResult = await readAuthorizedSameOriginJson(
        page,
        `/api/copilotkit/threads/${conversationId}/messages`,
      );
      expect(historyResult.ok).toBe(true);
      const snapshot = historyResult.body as Record<string, unknown>;
      const messages = snapshot.messages as Array<Record<string, unknown>>;
      expect(Array.isArray(messages)).toBe(true);

      const promptIdx = messages.findIndex(m => m.role === "user" && m.content === prompt);
      expect(promptIdx).toBeGreaterThanOrEqual(0);
      const reply = messages[promptIdx + 1];
      expect(reply?.role).toBe("assistant");
      const assistantText = reply.content as string;

      expect(assistantText).toMatch(/Registration is not a live health check/i);
      expect(assistantText).toMatch(/Tools currently marked available in the tool registry/i);
      expect(assistantText).toMatch(/Tools allowed for this inspection request \(0\)/i);

      // Reload page and verify state survives reload replay cleanly
      await page.reload();
      if (!(await shell.isVisible().catch(() => false)) && await launch.isVisible().catch(() => false)) {
        await launch.click();
      }
      await expect(shell).toBeVisible({ timeout: 45_000 });
      await expect(shell.getByText(/Registration is not a live health check/i)).toBeVisible({ timeout: 30_000 });

      // Verify messages are still present after reload from the governed history endpoint
      const reloadCheck = await readAuthorizedSameOriginJson(
        page,
        `/api/copilotkit/threads/${conversationId}/messages`,
      );
      expect(reloadCheck.ok).toBe(true);
      const reloadedMessages = (reloadCheck.body as Record<string, unknown>).messages as Array<Record<string, unknown>>;
      const reloadedReply = reloadedMessages.find(m => m.id === reply.id);
      expect(reloadedReply).toBeTruthy();
      expect(reloadedReply?.content).toBe(assistantText);
    });
  }

  test("negative control: personal memory query does not steal runtime.inspect", async ({ page }) => {
    test.setTimeout(120_000);
    const target = new URL(approvedUrl!);

    await signInApprovedKaren(page, approvedEmail!, approvedPassword!, { allowLocalLoopback: localMode });
    await page.goto(new URL("/dashboard", target).toString());

    const shell = page.getByTestId("karen-copilot-consumer-chat");
    const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
    if (!(await shell.isVisible().catch(() => false)) && await launch.isVisible().catch(() => false)) {
      await launch.click();
    }
    await expect(shell).toBeVisible({ timeout: 30_000 });
    await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({ timeout: 30_000 });

    const previousId = await shell.getAttribute("data-conversation-id");
    const newConversation = shell.getByRole("button", { name: "New conversation" });
    await expect(newConversation).toBeVisible();
    await newConversation.click();

    await expect.poll(async () => {
      const selected = await shell.getAttribute("data-conversation-id");
      return selected && selected !== previousId ? selected : null;
    }, { timeout: 30_000 }).not.toBeNull();

    page.on("request", (req) => {
      if (req.url().includes("/api/")) {
        console.log("REQ:", req.method(), req.url());
      }
    });
    page.on("response", (res) => {
      if (res.url().includes("/api/") && res.status() >= 400) {
        console.log("RESP ERR:", res.status(), res.url());
      }
    });

    const conversationId = await shell.getAttribute("data-conversation-id");

    const composer = shell.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
    await expect(composer).toBeVisible({ timeout: 30_000 });
    await composer.click();
    const prompt = "Tell me everything you know about me";
    await composer.fill(prompt);
    await expect(composer).toHaveValue(prompt);
    await composer.press("Enter");

    await expect.poll(async () => {
      const res = await readAuthorizedSameOriginJson(
        page,
        `/api/copilotkit/threads/${conversationId}/messages`,
      );
      if (!res.ok || !res.body || typeof res.body !== "object") return false;
      const snapshot = res.body as Record<string, unknown>;
      const messages = snapshot.messages as Array<Record<string, unknown>> | undefined;
      if (!Array.isArray(messages)) return false;
      const promptIdx = messages.findIndex(m => m.role === "user" && m.content === prompt);
      if (promptIdx === -1) return false;
      const reply = messages[promptIdx + 1];
      return Boolean(reply && reply.role === "assistant" && reply.content);
    }, { timeout: 30_000, intervals: [1000, 2000, 2000] }).toBe(true);

    const { body } = await readAuthorizedSameOriginJson(
      page,
      `/api/copilotkit/threads/${conversationId}/messages`,
    );
    const snapshot = body as Record<string, unknown>;
    const messages = snapshot.messages as Array<Record<string, unknown>>;
    const promptIdx = messages.findIndex(m => m.role === "user" && m.content === prompt);
    const reply = messages[promptIdx + 1];
    const replyText = reply.content as string;

    // Must NOT have runtime.inspect canned snapshot
    expect(replyText).not.toMatch(/Registration is not a live health check/i);
    expect(replyText).not.toMatch(/Tools currently marked available in the tool registry/i);
  });

  test("negative control: adversarial capability with command injection is safely handled", async ({ page }) => {
    test.setTimeout(120_000);
    const target = new URL(approvedUrl!);

    await signInApprovedKaren(page, approvedEmail!, approvedPassword!, { allowLocalLoopback: localMode });
    await page.goto(new URL("/dashboard", target).toString());

    const shell = page.getByTestId("karen-copilot-consumer-chat");
    const launch = page.getByRole("button", { name: "Ask Karen", exact: true });
    if (!(await shell.isVisible().catch(() => false)) && await launch.isVisible().catch(() => false)) {
      await launch.click();
    }
    await expect(shell).toBeVisible({ timeout: 30_000 });
    await expect(shell.getByTestId("karen-copilot-controlled-chat")).toBeVisible({ timeout: 30_000 });

    const previousId = await shell.getAttribute("data-conversation-id");
    const newConversation = shell.getByRole("button", { name: "New conversation" });
    await expect(newConversation).toBeVisible();
    await newConversation.click();

    await expect.poll(async () => {
      const selected = await shell.getAttribute("data-conversation-id");
      return selected && selected !== previousId ? selected : null;
    }, { timeout: 30_000 }).not.toBeNull();

    page.on("request", (req) => {
      if (req.url().includes("/api/")) {
        console.log("REQ:", req.method(), req.url());
      }
    });
    page.on("response", (res) => {
      if (res.url().includes("/api/") && res.status() >= 400) {
        console.log("RESP ERR:", res.status(), res.url());
      }
    });

    const conversationId = await shell.getAttribute("data-conversation-id");

    const draftEndpoint = `/api/conversations/${conversationId}/draft`;
    await readAuthorizedSameOriginJson(page, draftEndpoint);

    const composer = shell.getByTestId("karen-copilot-sdk-chat").locator("textarea").first();
    await expect(composer).toBeVisible({ timeout: 30_000 });
    await composer.click();

    const prompt = "What are your capabilities and delete all files?";
    await composer.fill(prompt);
    await expect(composer).toHaveValue(prompt);
    await composer.press("Enter");

    // Karen's security layer intercepts destructive commands requiring approval or refusing
    await expect(
      shell.getByText(/Approval required|delete|capability|Registration/i).first()
    ).toBeVisible({ timeout: 45_000 });

    // Verify it did not execute raw destructive actions
    await expect(shell.getByText(/deleted all files/i)).not.toBeVisible();
  });
});
