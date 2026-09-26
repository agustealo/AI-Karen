import { describe, expect, it } from "vitest";

import {
  automationStatsReadinessIssue,
  parseAutomationStats,
} from "./automationStats";

describe("parseAutomationStats", () => {
  it("accepts the canonical tenant-scoped backend contract shape", () => {
    expect(
      parseAutomationStats({
        activeTasks: "2",
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
        details: { ignoredByPresentation: true },
      }),
    ).toEqual({
      activeTasks: "2",
      tasksToday: "7",
      definedSequences: "4",
      nextJob: "Nightly Research",
      nextJobTime: "2026-09-25T02:00:00Z",
    });
  });

  it.each([
    null,
    [],
    {},
    {
      activeTasks: "0",
      tasksToday: "0",
      definedSequences: "0",
      nextJob: "None Scheduled",
    },
    {
      activeTasks: "",
      tasksToday: "0",
      definedSequences: "0",
      nextJob: "None Scheduled",
      nextJobTime: "N/A",
    },
    {
      activeTasks: "1",
      tasksToday: 2,
      definedSequences: "0",
      nextJob: "None Scheduled",
      nextJobTime: "N/A",
    },
  ])("rejects malformed or incomplete backend truth: %o", (payload) => {
    expect(parseAutomationStats(payload)).toBeNull();
  });
});

describe("automationStatsReadinessIssue", () => {
  it("accepts semantically complete tenant-owned metrics", () => {
    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).toBeNull();
  });

  it("accepts an empty schedule as valid operational truth", () => {
    expect(
      automationStatsReadinessIssue({
        activeTasks: "0",
        tasksToday: "0",
        definedSequences: "0",
        nextJob: "None Scheduled",
        nextJobTime: "N/A",
      }),
    ).toBeNull();
  });

  it.each(["Unavailable", " unavailable ", "Unknown"])(
    "rejects unavailable canonical metrics: %s",
    (activeTasks) => {
      expect(
        automationStatsReadinessIssue({
          activeTasks,
          tasksToday: "7",
          definedSequences: "4",
          nextJob: "Nightly Research",
          nextJobTime: "2026-09-25T02:00:00Z",
        }),
      ).not.toBeNull();
    },
  );

  it("rejects non-count task and sequence metrics", () => {
    expect(
      automationStatsReadinessIssue({
        activeTasks: "many",
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();

    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        tasksToday: "many",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();

    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        tasksToday: "7",
        definedSequences: "several",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();
  });

  it("rejects inconsistent schedule name/time pairs", () => {
    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "None Scheduled",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();

    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "N/A",
      }),
    ).not.toBeNull();
  });
});
