export interface AutomationStats {
  activeAgents: string;
  tasksToday: string;
  activeSequences: string;
  nextJob: string;
  nextJobTime: string;
}

const hasNonEmptyString = (
  value: Record<string, unknown>,
  key: keyof AutomationStats,
): boolean => typeof value[key] === "string" && value[key].trim().length > 0;

/**
 * Validate the tenant-scoped automation dashboard contract before the UI
 * presents it as live runtime truth. Missing or malformed fields fail closed.
 */
export function parseAutomationStats(value: unknown): AutomationStats | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }

  const candidate = value as Record<string, unknown>;
  const requiredFields: Array<keyof AutomationStats> = [
    "activeAgents",
    "tasksToday",
    "activeSequences",
    "nextJob",
    "nextJobTime",
  ];

  if (!requiredFields.every((key) => hasNonEmptyString(candidate, key))) {
    return null;
  }

  return {
    activeAgents: candidate.activeAgents as string,
    tasksToday: candidate.tasksToday as string,
    activeSequences: candidate.activeSequences as string,
    nextJob: candidate.nextJob as string,
    nextJobTime: candidate.nextJobTime as string,
  };
}
