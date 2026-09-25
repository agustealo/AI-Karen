import { describe, expect, it } from "vitest";

import {
  automationStatsReadinessIssue,
  parseAutomationStats,
} from "./automationStats";

describe("parseAutomationStats", () => {
  it("accepts the canonical tenant-scoped backend contract shape", () => {
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

describe("automationStatsReadinessIssue", () => {
  it("accepts semantically complete canonical metrics", () => {
    expect(
      automationStatsReadinessIssue({
        activeAgents: "2 / 3",
        tasksToday: "7",
        activeSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).toBeNull();
  });

  it.each([
    "Unavailable",
    " unavailable ",
    "Unknown",
    "N/A",
  ])("rejects unavailable active-agent truth: %s", (activeAgents) => {
    expect(
      automationStatsReadinessIssue({
        activeAgents,
        tasksToday: "7",
        activeSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();
  });

  it("rejects non-canonical and inconsistent agent counts", () => {
    expect(
      automationStatsReadinessIssue({
        activeAgents: "two agents",
        tasksToday: "7",
        activeSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();

    expect(
      automationStatsReadinessIssue({
        activeAgents: "4 / 3",
        tasksToday: "7",
        activeSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();
  });

  it("rejects non-count task and sequence metrics", () => {
    expect(
      automationStatsReadinessIssue({
        activeAgents: "2 / 3",
        tasksToday: "many",
        activeSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();

    expect(
      automationStatsReadinessIssue({
        activeAgents: "2 / 3",
        tasksToday: "7",
        activeSequences: "several",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();
  });
});
