import { expect, test } from "@playwright/test";

/**
 * Real, authenticated browser proof. Requires a seeded, authorized account and
 * already-persisted planner presentation. No route interception, fake tasks,
 * injected cookies, or production state mutation.
 *
 * KAREN_E2E_PLANNER_REPLAY=1
 * KAREN_E2E_AUTH_STATE=/secure/path/authorized-storage-state.json
 * KAREN_E2E_PLANNER_CONVERSATION_TITLE=<existing unique title>
 * KAREN_E2E_PLANNER_TASK_TITLE=<persisted task title>
 */
const enabled = process.env.KAREN_E2E_PLANNER_REPLAY === "1";
const authState = process.env.KAREN_E2E_AUTH_STATE;
const conversationTitle = process.env.KAREN_E2E_PLANNER_CONVERSATION_TITLE;
const taskTitle = process.env.KAREN_E2E_PLANNER_TASK_TITLE;

test.describe("authenticated planner presentation replay", () => {
  test.skip(
    !enabled || !authState || !conversationTitle || !taskTitle,
    "Requires approved authenticated storage state and a real seeded planner conversation",
  );
  test.use({ storageState: authState || { cookies: [], origins: [] } });

  test("reopens a real planner card across page reload without duplication", async ({ page }) => {
    await page.goto("/dashboard");
    const shell = page.getByTestId("karen-assistant-ui-chat");
    await expect(shell).toBeVisible();
    await shell.getByRole("button", { name: "Find conversations" }).click();
    const match = page.getByRole("group", { name: "Matching conversations" })
      .getByRole("button", { name: conversationTitle!, exact: true });
    await expect(match).toHaveCount(1);
    await match.click();

    const plannerCards = shell.getByTestId("karen-planner-task-list");
    const task = plannerCards.getByText(taskTitle!, { exact: true });
    await expect(task).toHaveCount(1);

    // Reopen the *same* persisted conversation after reload. A reload may
    // restore a different active thread, so do not mistake that for success.
    await page.reload();
    await expect(shell).toBeVisible();
    await shell.getByRole("button", { name: "Find conversations" }).click();
    const reopened = page.getByRole("group", { name: "Matching conversations" })
      .getByRole("button", { name: conversationTitle!, exact: true });
    await expect(reopened).toHaveCount(1);
    await reopened.click();
    await expect(plannerCards.getByText(taskTitle!, { exact: true })).toHaveCount(1);
    await expect(shell.getByRole("alert")).toHaveCount(0);
  });
});
