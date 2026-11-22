import { expect, test, type Locator, type Page } from "@playwright/test";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/** Live-source test; no API mocks, credentials or document bytes in reports. */
test.use({ screenshot: "off", video: "off", trace: "off" });

const enabled = process.env.KAREN_DOCUMENT_AUTHOR_ACCEPTANCE === "true";
const mutationEnabled =
  process.env.KAREN_DOCUMENT_AUTHOR_MUTATION_ACCEPTANCE === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const expectedArtifact = process.env.KAREN_DOCUMENT_AUTHOR_ARTIFACT_ID;
const expectedDigest = process.env.KAREN_DOCUMENT_AUTHOR_SOURCE_SHA256;
const expectedName = process.env.KAREN_DOCUMENT_AUTHOR_SOURCE_NAME;
const expectedProfile = process.env.KAREN_DOCUMENT_AUTHOR_PROFILE_ID;
const local = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const digest = /^[a-f0-9]{64}$/;

function approvedOrigin(): URL {
  const raw = process.env.KAREN_BASE_URL;
  if (!raw) throw new Error("Approved KAREN_BASE_URL is required");
  const origin = new URL(raw);
  const canonical =
    !origin.username && !origin.password && origin.pathname === "/" &&
    !origin.search && !origin.hash;
  const loopback = local && origin.protocol === "http:" &&
    ["localhost", "127.0.0.1"].includes(origin.hostname) && !!origin.port;
  const release = origin.protocol === "https:" && !origin.port;
  if (!canonical || !(loopback || release)) {
    throw new Error("Author acceptance requires an approved exact origin");
  }
  return origin;
}

function requireEvidence(mutation: boolean): void {
  if (!email || !password || !expectedArtifact || !uuid.test(expectedArtifact) ||
    !expectedDigest || !digest.test(expectedDigest) ||
    !expectedName || expectedName.length > 160 ||
    (mutation && (!expectedProfile || !uuid.test(expectedProfile)))) {
    throw new Error("Dedicated authenticated author and canonical source fixture required");
  }
}

async function selectSource(page: Page, origin: URL): Promise<Locator> {
  await page.goto(new URL("/approvals/document-consent/new", origin).toString());
  expect(new URL(page.url()).origin).toBe(origin.origin);
  const selector = page.getByRole("region", { name: "Initiate document author consent" });
  await expect(selector).toBeVisible();
  const document = selector.getByRole("combobox", { name: "Your document" });
  await expect(document).toBeVisible();
  // Compare IDs inside the page; do not print sensitive source metadata.
  const found = await document.evaluate((node, id) => (
    Array.from((node as HTMLSelectElement).options).some(option => option.value === id)
  ), expectedArtifact!);
  expect(found, "Expected source must be in the authenticated owner inventory").toBe(true);
  return selector;
}

async function expectExactSource(review: Locator): Promise<void> {
  // Poll the actual asynchronously loaded review values, not the section shell.
  // This avoids logging source identifiers in failing locator selectors.
  await expect.poll(async () => review.evaluate((root, expected) => {
    const values = Array.from(root.querySelectorAll("dd"))
      .map(element => element.textContent?.trim());
    return values.includes(expected.artifact) &&
      values.includes(expected.digest) &&
      values.includes(expected.name);
  }, {
    artifact: expectedArtifact!, digest: expectedDigest!, name: expectedName!,
  }), {
    message: "The real consent preview must match the authenticated source",
    timeout: 20_000,
  }).toBe(true);
}

test("WS-04A9Y: read-only authenticated inventory never initiates approval", async ({ page }) => {
  test.skip(!enabled, "Enable read-only author inventory acceptance explicitly");
  test.setTimeout(120_000);
  requireEvidence(false);
  const origin = approvedOrigin();
  await signInApprovedKaren(page, email!, password!, { allowLocalLoopback: local });
  const selector = await selectSource(page, origin);
  const initiate = selector.getByRole("button", { name: "Continue to author review" });
  await expect(initiate).toBeDisabled();
  await expect(selector.getByText(/Document ingestion remains disabled/)).toBeVisible();
  // Do not click, mutate, initiate, confirm, issue or read document content.
});

test("WS-04A9Y: author issues and recovers, then revokes from a fresh login", async ({ page, browser }) => {
  test.skip(
    !enabled || !mutationEnabled,
    "Mutation trial requires explicit disposable fixture authorization",
  );
  test.setTimeout(120_000);
  requireEvidence(true);
  const origin = approvedOrigin();
  await signInApprovedKaren(page, email!, password!, { allowLocalLoopback: local });
  const selector = await selectSource(page, origin);
  await selector.getByRole("combobox", { name: "Your document" })
    .selectOption(expectedArtifact!);
  const profileChoice = selector.getByRole("combobox", {
    name: "Your draft writing-style profile",
  });
  await expect.poll(async () => profileChoice.evaluate((node, id) => (
    Array.from((node as HTMLSelectElement).options).some(option => option.value === id)
  ), expectedProfile!), {
    message: "Expected draft profile must be in the authenticated inventory",
  }).toBe(true);
  await profileChoice.selectOption(expectedProfile!);
  const initiate = selector.getByRole("button", { name: "Continue to author review" });
  await expect(initiate).toBeEnabled();
  await initiate.click();
  await expect(page).toHaveURL(/\/approvals\/document-consent\/[0-9a-f-]{36}$/);

  const review = page.getByRole("region", { name: "Document author consent" });
  await expectExactSource(review);
  const confirm = review.getByRole("button", { name: "Confirm author consent" });
  await expect(confirm).toBeDisabled();
  await expect(review.getByRole("checkbox")).not.toBeChecked();
  await expect(review.getByText(/Verified receipt ID:/)).toHaveCount(0);
  await review.getByRole("checkbox").check();
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(review.getByText(/Verified receipt ID:/).first()).toBeVisible();
  await expect(review.getByText(/Document ingestion is not confirmed/).first()).toBeVisible();

  await page.reload();
  const recovered = page.getByRole("region", { name: "Document author consent" });
  await expectExactSource(recovered);
  await expect(recovered.getByText(/Verified receipt ID:/).first()).toBeVisible();
  await expect(recovered.getByRole("button", { name: "Confirm author consent" })).toHaveCount(0);
  // A separate browser context creates a genuinely new bearer token. The
  // original session remains mandatory for issuance, but not revocation.
  const rotated = await browser.newContext();
  try {
    const fresh = await rotated.newPage();
    await signInApprovedKaren(fresh, email!, password!, {
      allowLocalLoopback: local,
    });
    await fresh.goto(page.url());
    expect(new URL(fresh.url()).origin).toBe(origin.origin);
    const revocation = fresh.getByRole("region", { name: "Document author consent" });
    await expect(revocation.getByText(/Your current session can request/))
      .toBeVisible();
    await expect(revocation.getByRole("button", {
      name: "Confirm author consent",
    })).toHaveCount(0);
    const revokeCheckbox = revocation.getByRole("checkbox", {
      name: "Confirm revoke document consent",
    });
    const revoke = revocation.getByRole("button", { name: "Revoke document consent" });
    await expect(revoke).toBeDisabled();
    await revokeCheckbox.check();
    await expect(revoke).toBeEnabled();
    await revoke.click();
    await expect(revocation.getByText(/Document consent revocation recorded/)).toBeVisible();
    await fresh.reload();
    const afterRevoke = fresh.getByRole("region", { name: "Document author consent" });
    await expect(afterRevoke.getByText(/Verified receipt ID:/)).toHaveCount(0);
    await expect(afterRevoke.getByRole("button", {
      name: "Confirm author consent",
    })).toHaveCount(0);
  } finally {
    await rotated.close();
  }
});
