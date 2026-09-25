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

const ACTIVE_AGENT_COUNT = /^(\d+)\s*\/\s*(\d+)$/;
const NON_NEGATIVE_INTEGER = /^\d+$/;
const UNAVAILABLE_VALUES = new Set(["unavailable", "unknown", "n/a"]);

const normalized = (value: string): string => value.trim().toLowerCase();

/**
 * Validate the automation dashboard response shape without inventing missing
 * runtime truth. Semantic readiness is evaluated separately below.
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

/**
 * Return a reason when a structurally valid response is not complete enough to
 * be presented as verified tenant-scoped runtime truth.
 *
 * The legacy agent catalog is installation-wide. Until a tenant-aware agent
 * inventory becomes canonical, the backend honestly returns "Unavailable".
 * That sentinel must never be promoted to the UI/showcase "ready" state.
 */
export function automationStatsReadinessIssue(
  stats: AutomationStats,
): string | null {
  for (const value of Object.values(stats)) {
    if (UNAVAILABLE_VALUES.has(normalized(value))) {
      return "One or more automation metrics are unavailable from canonical tenant-scoped owners.";
    }
  }

  const agentMatch = stats.activeAgents.trim().match(ACTIVE_AGENT_COUNT);
  if (!agentMatch) {
    return "Active agent metrics are not backed by the canonical count contract.";
  }

  const activeAgents = Number.parseInt(agentMatch[1], 10);
  const totalAgents = Number.parseInt(agentMatch[2], 10);
  if (activeAgents > totalAgents) {
    return "Active agent metrics are internally inconsistent.";
  }

  if (!NON_NEGATIVE_INTEGER.test(stats.tasksToday.trim())) {
    return "Task execution metrics are not backed by the canonical count contract.";
  }

  if (!NON_NEGATIVE_INTEGER.test(stats.activeSequences.trim())) {
    return "Automation sequence metrics are not backed by the canonical count contract.";
  }

  return null;
}
