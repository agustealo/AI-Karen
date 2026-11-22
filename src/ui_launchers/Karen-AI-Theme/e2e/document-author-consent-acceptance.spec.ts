import { expect, test } from "@playwright/test";
import { signInApprovedKaren } from "./fixtures/approved-karen-login";

/**
 * WS-04A9T: approved-host, real-account document-author acceptance.
 *
 * No route interception, fabricated source rows, prefilled confirmation,
 * auth bypass, source-byte capture, screenshots, trace, video, or model output
 * accepted as authorship proof. The ordinary opt-in is read-only; the mutation
 * trial requires a second, explicit owner-approved gate and disposable source.
 */
test.use({ screenshot: "off", video: "off", trace: "off" });

const enabled = process.env.KAREN_DOCUMENT_AUTHOR_ACCEPTANCE === "true";
const mutationEnabled =
  process.env.KAREN_DOCUMENT_AUTHOR_MUTATION_ACCEPTANCE === "true";
const email = process.env.KAREN_UX_EMAIL;
const password = process.env.KAREN_UX_PASSWORD;
const approvalId = process.env.KAREN_DOCUMENT_AUTHOR_APPROVAL_ID;
const expectedArtifact = process.env.KAREN_DOCUMENT_AUTHOR_ARTIFACT_ID;
const expectedDigest = process.env.KAREN_DOCUMENT_AUTHOR_SOURCE_SHA256;
const expectedName = process.env.KAREN_DOCUMENT_AUTHOR_SOURCE_NAME;
const local = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const digest = /^[0-9a-f]{64}$/;

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

function requireApprovalEvidence(): void {
  if (!email || !password) {
    throw new Error("Dedicated approved author test credentials required");
  }
  if (
    !approvalId || !uuid.test(approvalId) ||
    !expectedArtifact || !uuid.test(expectedArtifact) ||
    !expectedDigest || !digest.test(expectedDigest) ||
    !expectedName || expectedName.length > 160
  ) {
    throw new Error("A verified dedicated author approval/source fixture is required");
  }
}

test("WS-04A9T: real bearer review does not authorize without deliberate gesture", async ({ page }) => {
  test.skip(!enabled, "Enable real author review acceptance explicitly");
  test.setTimeout(120_000);
  requireApprovalEvidence();
  const approved = approvedOrigin();
  await signInApprovedKaren(page, email!, password!, { allowLocalLoopback: local });
  await page.goto(
    new URL("/approvals/document-consent/" + approvalId, approved).toString(),
  );
  expect(new URL(page.url()).origin).toBe(approved.origin);
  const review = page.getByRole("region", { name: "Document author consent" });
  await expect(review).toBeVisible();
  await expect(review.getByText(expectedArtifact!, { exact: true })).toBeVisible();
  await expect(review.getByText(expectedDigest!, { exact: true })).toBeVisible();
  await expect(review.getByText(expectedName!, { exact: true })).toBeVisible();
  await expect(review.getByText("Document author confirmation")).toBeVisible();
  await expect(review.getByText(/Document approval could not be verified/)).toHaveCount(0);

  const confirm = review.getByRole("button", { name: "Confirm author consent" });
  const checkbox = review.getByRole("checkbox");
  if (await confirm.count()) {
    await expect(confirm).toBeDisabled();
    await expect(checkbox).not.toBeChecked();
    // A read-only trial must never click the consent checkbox or submit.
  } else {
    await expect(checkbox).toHaveCount(0);
    await expect(review.getByText(/already approved|approval was consumed/i))
      .toBeVisible();
  }
});

test("WS-04A9T: dedicated author gesture issues or recovers real durable consent", async ({ page }) => {
  test.skip(
    !enabled || !mutationEnabled,
    "Mutation acceptance requires separate explicit authorization",
  );
  test.setTimeout(120_000);
  requireApprovalEvidence();
  const approved = approvedOrigin();
  await signInApprovedKaren(page, email!, password!, { allowLocalLoopback: local });
  await page.goto(
    new URL("/approvals/document-consent/" + approvalId, approved).toString(),
  );
  expect(new URL(page.url()).origin).toBe(approved.origin);
  const review = page.getByRole("region", { name: "Document author consent" });
  await expect(review.getByText(expectedArtifact!, { exact: true })).toBeVisible();
  await expect(review.getByText(expectedDigest!, { exact: true })).toBeVisible();
  await expect(review.getByText(expectedName!, { exact: true })).toBeVisible();

  const confirm = review.getByRole("button", { name: "Confirm author consent" });
  if (await confirm.count()) {
    await expect(confirm).toBeDisabled();
    await review.getByRole("checkbox").check();
    await expect(confirm).toBeEnabled();
    await confirm.click();
  } else {
    const issue = review.getByRole("button", { name: "Issue approved consent receipt" });
    if (await issue.count()) await issue.click();
  }
  const recovered = review.getByRole("button", {
    name: "Recheck current consent receipt",
  });
  if (await recovered.isVisible().catch(() => false)) {
    await recovered.click();
  }
  await expect(review.getByText(/Verified receipt ID:/).first()).toBeVisible();
  await expect(review.getByText(/Document ingestion is not confirmed/).first())
    .toBeVisible();
  await page.reload();
  const replay = page.getByRole("region", { name: "Document author consent" });
  await expect(replay.getByText(/Verified receipt ID:/).first()).toBeVisible();
  await expect(replay.getByRole("checkbox")).toHaveCount(0);
});
