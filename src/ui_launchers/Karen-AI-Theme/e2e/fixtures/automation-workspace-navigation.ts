import { expect, type Page } from "@playwright/test";

/**
 * Navigate the actual dashboard owner, including mobile sidebar and advanced
 * automation group. No backend or authentication state is fabricated.
 */
export async function openAutomationWorkspace(
  page: Page,
  label: string,
  advanced: boolean,
): Promise<void> {
  const advancedToggle = page.getByTestId("advanced-tools-toggle");
  const requiredToggle = advanced
    ? advancedToggle
    : page.getByRole("button", { name: label, exact: true });
  if (!await requiredToggle.last().isVisible().catch(() => false)) {
    const sidebarToggle = page.locator('[data-sidebar="trigger"]').first();
    await expect(sidebarToggle).toBeVisible();
    await sidebarToggle.click();
  }
  if (advanced) {
    await expect(advancedToggle).toBeVisible();
    if (await advancedToggle.getAttribute("aria-expanded") !== "true") {
      await advancedToggle.click();
    }
  }
  const navigation = page.getByRole("button", { name: label, exact: true });
  await expect(navigation.last()).toBeVisible();
  await navigation.last().click();
}
