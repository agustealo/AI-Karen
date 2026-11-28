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

/**
 * Canonical read through the actual signed-in browser. The access token
 * stays in its origin; never return it to the runner or follow redirects.
 * The only mutation supported here is an explicit disposable draft seed.
 */
type ApprovedApiResult = { ok: boolean; status: number; body: unknown };
type DraftSeed = { text: ""; expected_revision: number; attachment_references: Array<{ source_id: string; revision: string }> };

async function authorizedSameOriginJson(
  page: Page, apiPath: string, draftSeed?: DraftSeed,
): Promise<ApprovedApiResult> {
  const configured = process.env.KAREN_BASE_URL;
  if (!configured || new URL(page.url()).origin !== new URL(configured).origin) {
    throw new Error("Refusing authenticated request outside approved origin");
  }
  return page.evaluate(async ({ path, approved, seed }) => {
    const url = new URL(path, window.location.origin);
    if (window.location.origin !== approved || url.origin !== approved ||
        !url.pathname.startsWith("/api/") ||
        (seed !== undefined && (!/^\/api\/conversations\/[a-f0-9-]{36}\/draft$/.test(url.pathname) || url.search))) {
      throw new Error("Refusing unapproved authenticated API request");
    }
    const accessToken = window.localStorage.getItem("access_token");
    const response = await window.fetch(url.pathname + url.search, {
      method: seed === undefined ? "GET" : "PUT",
      credentials: "same-origin", cache: "no-store", redirect: "error",
      headers: {
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...(seed === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(seed === undefined ? {} : { body: JSON.stringify(seed) }),
    });
    return { ok: response.ok, status: response.status, body: response.ok ? await response.json() : null };
  }, { path: apiPath, approved: new URL(configured).origin, seed: draftSeed });
}

export async function readAuthorizedSameOriginJson(page: Page, apiPath: string): Promise<ApprovedApiResult> {
  return authorizedSameOriginJson(page, apiPath);
}

export async function seedApprovedAcceptanceDraft(
  page: Page, apiPath: string, seed: DraftSeed,
): Promise<ApprovedApiResult> {
  if (process.env.KAREN_KEXP_RETRY_ATTACHMENT_REQUIRED !== "true" ||
      process.env.KAREN_SANITIZED_ACCOUNT !== "true" ||
      process.env.KAREN_SEARCH_ACCEPTANCE_PLATFORM !== "docker" ||
      !Number.isSafeInteger(seed.expected_revision) || seed.expected_revision < 0 ||
      seed.text !== "" || seed.attachment_references.length !== 1 ||
      seed.attachment_references[0].source_id !== process.env.KAREN_KEXP_RETRY_SOURCE_ID ||
      seed.attachment_references[0].revision !== process.env.KAREN_KEXP_RETRY_SOURCE_REVISION) {
    throw new Error("Draft seed must use the explicitly approved disposable attachment");
  }
  return authorizedSameOriginJson(page, apiPath, seed);
}
