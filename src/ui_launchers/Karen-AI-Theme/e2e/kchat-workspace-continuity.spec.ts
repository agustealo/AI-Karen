import { expect, test } from "@playwright/test";

/**
 * Authenticated live-browser acceptance of the shared Karen conversation.
 * No intercepted APIs, fake responses, or synthetic persistence assertions.
 * This suite defaults to the legacy chat while assistant-ui stays opt-in.
 */
const hasCredentials = Boolean(process.env.KAREN_UX_EMAIL && process.env.KAREN_UX_PASSWORD);

test("KCHAT-14: a draft survives cross-workspace navigation and panel dismissal", async ({ page }) => {
  test.skip(!hasCredentials, "Requires KAREN_UX_EMAIL and KAREN_UX_PASSWORD on a sanitized deployment.");
  const email = process.env.KAREN_UX_EMAIL;
  const password = process.env.KAREN_UX_PASSWORD;
  if (!email || !password) throw new Error("Missing browser acceptance credentials");

  await page.goto("/login");
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard(?:[/?#]|$)/, { timeout: 30_000 });

  const panel = page.getByTestId("persistent-karen-conversation");
  const input = panel.getByTestId("chat-input");
  await expect(input).toBeVisible({ timeout: 30_000 });
  const draft = `KCHAT-14 unsent draft ${Date.now()}`;
  await input.fill(draft);
  await page.getByRole("button", { name: "Messages & channels", exact: true }).click();

  await expect(panel).toHaveAttribute("aria-hidden", "true");
  await page.getByRole("button", { name: "Ask Karen", exact: true }).click();
  await expect(panel).toHaveAttribute("aria-hidden", "false");
  await expect(panel).toHaveAttribute("role", "dialog");
  await expect(input).toHaveValue(draft);

  await page.keyboard.press("Escape");
  await expect(panel).toHaveAttribute("aria-hidden", "true");
  await expect(page.getByRole("button", { name: "Ask Karen", exact: true })).toBeFocused();

  await page.getByRole("button", { name: "Ask Karen", exact: true }).click();
  await expect(input).toHaveValue(draft);
  // The draft is not submitted; this tests presentation state, not durable persistence.
});
