import { expect, type Page } from "@playwright/test";

/**
 * Shared origin-locked sign-in for real CopilotKit browser acceptance.
 *
 * Default: an approved HTTPS release origin. Only the explicitly opted-in
 * local consumer acceptance suite can request loopback HTTP. This function
 * never intercepts responses, skips authentication, or persists credentials.
 */
export async function signInApprovedKaren(
  page: Page,
  email: string,
  password: string,
  options: Readonly<{ allowLocalLoopback?: boolean }> = {},
): Promise<void> {
  const configured = process.env.KAREN_BASE_URL;
  if (!configured || !email || !password) {
    throw new Error("Approved live authentication is not configured");
  }

  let approved: URL;
  try {
    approved = new URL(configured);
  } catch {
    throw new Error("Approved authentication origin is malformed");
  }

  const localAllowed = options.allowLocalLoopback === true &&
    process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1" &&
    process.env.KAREN_CHAT_BOOT_ACCEPTANCE !== "1";
  const cleanOrigin = !approved.username && !approved.password &&
    approved.pathname === "/" && !approved.search && !approved.hash;
  const approvedLocal = localAllowed &&
    approved.protocol === "http:" &&
    ["127.0.0.1", "localhost"].includes(approved.hostname) &&
    approved.port !== "";
  const approvedRelease = approved.protocol === "https:" &&
    approved.port === "";
  if (!cleanOrigin || !(approvedLocal || approvedRelease)) {
    throw new Error("Only an approved HTTPS origin or explicit local loopback may accept credentials");
  }

  // Bind navigation to the approved origin rather than an independently
  // configured Playwright base URL, then prove the browser stayed on-origin
  // before filling either credential.
  await page.goto(new URL("/login", approved).toString());
  expect(new URL(page.url()).origin).toBe(approved.origin);
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("/dashboard(?:[/?#]|$)"), { timeout: 30000 });
  expect(new URL(page.url()).origin).toBe(approved.origin);
}
