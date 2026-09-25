export interface AutomationStats {
  activeTasks: string;
  tasksToday: string;
  definedSequences: string;
  nextJob: string;
  nextJobTime: string;
}

const hasNonEmptyString = (
  value: Record<string, unknown>,
  key: keyof AutomationStats,
): boolean => typeof value[key] === "string" && value[key].trim().length > 0;

const NON_NEGATIVE_INTEGER = /^\d+$/;
const UNAVAILABLE_VALUES = new Set(["unavailable", "unknown", "n/a"]);

const normalized = (value: string): string => value.trim().toLowerCase();

/**
 * Validate the tenant-scoped automation dashboard response shape without
 * inventing missing runtime truth. Semantic readiness is evaluated separately.
 */
export function parseAutomationStats(value: unknown): AutomationStats | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const requiredFields: Array<keyof AutomationStats> = [
    "activeTasks",
    "tasksToday",
    "definedSequences",
    "nextJob",
    "nextJobTime",
  ];

  if (!requiredFields.every((key) => hasNonEmptyString(candidate, key))) {
    return null;
  }

  return {
    activeTasks: candidate.activeTasks as string,
    tasksToday: candidate.tasksToday as string,
    definedSequences: candidate.definedSequences as string,
    nextJob: candidate.nextJob as string,
    nextJobTime: candidate.nextJobTime as string,
  };
}

/**
 * Return a reason when a structurally valid response is not complete enough to
 * be presented as verified tenant-scoped runtime truth.
 */
export function automationStatsReadinessIssue(
  stats: AutomationStats,
): string | null {
  for (const value of Object.values(stats)) {
    if (UNAVAILABLE_VALUES.has(normalized(value))) {
      return "One or more automation metrics are unavailable from canonical tenant-scoped owners.";
    }
  }

  if (!NON_NEGATIVE_INTEGER.test(stats.activeTasks.trim())) {
    return "Active task metrics are not backed by the canonical count contract.";
  }

  if (!NON_NEGATIVE_INTEGER.test(stats.tasksToday.trim())) {
    return "Task execution metrics are not backed by the canonical count contract.";
  }

  if (!NON_NEGATIVE_INTEGER.test(stats.definedSequences.trim())) {
    return "Automation sequence metrics are not backed by the canonical count contract.";
  }

  return null;
}
