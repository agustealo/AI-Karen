import { expect, test } from "@playwright/test";

/**
 * Opt-in, live authenticated acceptance against a sanitized deployment.
 * Reads an existing canonical conversation. Never intercepts APIs, fabricates
 * persistence, creates synthetic assistant messages, or records credentials.
 */
const required = process.env.KAREN_HISTORY_ACCEPTANCE_REQUIRED === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const conversationId = process.env.KAREN_HISTORY_CONVERSATION_ID;

test("reopening an owned conversation preserves its saved answer and execution receipt", async ({ page }) => {
  if (required && (!email || !password || !conversationId)) {
    throw new Error("Live history acceptance requires credentials and KAREN_HISTORY_CONVERSATION_ID");
  }
  test.skip(!email || !password || !conversationId, "Requires an approved sanitized conversation fixture");
  if (!email || !password || !conversationId) return;

  await page.goto("/login");
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("/dashboard(?:[/?#]|$)"), { timeout: 30_000 });

  const response = await page.request.get(
    `/api/conversations/${encodeURIComponent(conversationId)}`,
  );
  expect(response.ok(), "The authenticated API must authorize the exact conversation").toBe(true);
  const stored = await response.json() as {
    id: string;
    title?: string;
    messages?: Array<{ role: string; content: string; metadata?: Record<string, unknown> }>;
  };
  expect(stored.id).toBe(conversationId);
  expect(Array.isArray(stored.messages)).toBe(true);
  const assistant = stored.messages?.find(message =>
    message.role === "assistant" &&
    typeof message.metadata?.actual_provider === "string" &&
    typeof message.metadata?.actual_model === "string" &&
    typeof message.metadata?.response_source === "string",
  );
  expect(assistant, "Fixture must include an actual persisted execution receipt").toBeDefined();
  if (!assistant) return;

  const chat = page.getByTestId("karen-assistant-ui-chat");
  await expect(chat).toBeVisible({ timeout: 30_000 });
  await chat.getByRole("button", { name: "Find conversations" }).click();
  await chat.getByPlaceholder("Search conversation titles").fill(stored.title || "");
  const title = stored.title || "Untitled conversation";
  await chat.getByRole("button", { name: title, exact: true }).click();

  await expect(chat.getByText(assistant.content, { exact: true })).toBeVisible();
  const receipt = chat.getByTestId("karen-restored-execution-receipt");
  await expect(receipt.first()).toBeVisible();
  await receipt.first().locator("summary").click();
  await expect(receipt.first()).toContainText(String(assistant.metadata?.actual_model));

  // Reload verifies API-backed restoration, not only in-memory thread state.
  await page.reload();
  await expect(page.getByTestId("karen-assistant-ui-chat")
    .getByText(assistant.content, { exact: true })).toBeVisible({ timeout: 30_000 });
});
