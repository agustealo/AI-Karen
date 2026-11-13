import { describe, expect, it } from "vitest";

import {
  automationStatsReadinessIssue,
  parseAutomationStats,
} from "./automationStats";

const EVIDENCE = {
  tasksTodayTimezone: "America/Detroit",
  tasksTodayLocalDate: "2026-11-13",
  tasksTodaySource: "durable_execution_starts" as const,
  tasksTodayCoverage: "from_task_start_receipt_instrumentation" as const,
};

describe("parseAutomationStats", () => {
  it("accepts the canonical tenant-scoped backend contract shape", () => {
    expect(
      parseAutomationStats({
        activeTasks: "2",
        ...EVIDENCE,
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
        details: { ignoredByPresentation: true },
      }),
    ).toEqual({
      activeTasks: "2",
      ...EVIDENCE,
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
      ...EVIDENCE,
      tasksToday: "0",
      definedSequences: "0",
      nextJob: "None Scheduled",
    },
    {
      activeTasks: "",
      ...EVIDENCE,
      tasksToday: "0",
      definedSequences: "0",
      nextJob: "None Scheduled",
      nextJobTime: "N/A",
    },
    {
      activeTasks: "1",
      ...EVIDENCE,
      tasksToday: 2,
      definedSequences: "0",
      nextJob: "None Scheduled",
      nextJobTime: "N/A",
    },
  ])("rejects malformed or incomplete backend truth: %o", (payload) => {
    expect(parseAutomationStats(payload)).toBeNull();
  });
});


  it("rejects legacy cumulative counts without proof of execution-start provenance", () => {
    expect(parseAutomationStats({
      activeTasks: "2",
      tasksToday: "47",
      definedSequences: "4",
      nextJob: "Daily digest",
      nextJobTime: "2026-11-14T12:00:00Z",
    })).toBeNull();
  });

  it.each([
    { tasksTodaySource: "sum_of_historical_run_count" },
    { tasksTodayCoverage: "complete_legacy_history" },
    { tasksTodayLocalDate: "yesterday" },
    { tasksTodayTimezone: "" },
  ])("rejects unauthoritative task-activity metadata: %o", (override) => {
    expect(parseAutomationStats({
      activeTasks: "2",
      tasksToday: "1",
      definedSequences: "4",
      nextJob: "Daily digest",
      nextJobTime: "2026-11-14T12:00:00Z",
      ...EVIDENCE,
      ...override,
    })).toBeNull();
  });

describe("automationStatsReadinessIssue", () => {
  it("accepts semantically complete tenant-owned metrics", () => {
    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        ...EVIDENCE,
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
        ...EVIDENCE,
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
          ...EVIDENCE,
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
        ...EVIDENCE,
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();

    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        ...EVIDENCE,
        tasksToday: "many",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();

    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        ...EVIDENCE,
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
        ...EVIDENCE,
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "None Scheduled",
        nextJobTime: "2026-09-25T02:00:00Z",
      }),
    ).not.toBeNull();

    expect(
      automationStatsReadinessIssue({
        activeTasks: "2",
        ...EVIDENCE,
        tasksToday: "7",
        definedSequences: "4",
        nextJob: "Nightly Research",
        nextJobTime: "N/A",
      }),
    ).not.toBeNull();
  });
});
