import { describe, expect, it } from "vitest";

import { parseAutomationStats } from "./automationStats";

describe("parseAutomationStats", () => {
  it("accepts the canonical tenant-scoped backend contract", () => {
    expect(
      parseAutomationStats({
        activeAgents: "2 / 3",
        tasksToday: "0",
        activeSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
        details: { ignoredByPresentation: true },
      }),
    ).toEqual({
      activeAgents: "2 / 3",
      tasksToday: "0",
      activeSequences: "4",
      nextJob: "Nightly Research",
      nextJobTime: "2026-09-25T02:00:00Z",
    });
  });

  it.each([
    null,
    [],
    {},
    {
      activeAgents: "0 / 0",
      tasksToday: "0",
      activeSequences: "0",
      nextJob: "None Scheduled",
    },
    {
      activeAgents: "",
      tasksToday: "0",
      activeSequences: "0",
      nextJob: "None Scheduled",
      nextJobTime: "N/A",
    },
    {
      activeAgents: "1 / 1",
      tasksToday: 2,
      activeSequences: "0",
      nextJob: "None Scheduled",
      nextJobTime: "N/A",
    },
  ])("rejects malformed or incomplete backend truth: %o", (payload) => {
    expect(parseAutomationStats(payload)).toBeNull();
  });
});
