import { expect, type Page } from "@playwright/test";

/**
 * One approved-origin sign-in for real protected CopilotKit browser suites.
 * Credentials are supplied only by sanitized, reviewed-main acceptance jobs.
 * Never log credentials, follow arbitrary redirects or persist browser state.
 */
export async function signInApprovedKaren(
  page: Page, email: string, password: string,
) {
  const configured = process.env.KAREN_BASE_URL;
  if (!configured || !email || !password) {
    throw new Error("Approved live authentication is not configured");
  }
  let approved: URL;
  try {
    approved = new URL(configured);
  } catch {
    throw new Error("Approved deployment origin is malformed");
  }
  if (approved.protocol !== "https:" || approved.username || approved.password ||
      approved.port || approved.pathname !== "/" || approved.search || approved.hash) {
    throw new Error("Only a clean approved HTTPS origin can accept credentials");
  }
  await page.goto("/login");
  expect(new URL(page.url()).origin).toBe(approved.origin);
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("/dashboard(?:[/?#]|$)"), { timeout: 30000 });
  expect(new URL(page.url()).origin).toBe(approved.origin);
}
