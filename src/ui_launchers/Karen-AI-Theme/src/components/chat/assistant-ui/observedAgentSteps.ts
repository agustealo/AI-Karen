import type { AgentStepEvent } from "@/lib/types";

export function projectObservedAgentSteps(messages: readonly unknown[]): AgentStepEvent[] {
  const steps = new Map<string, AgentStepEvent>();
  const names = new Set([
    "agui-activity/KAREN_AGENT_STEP",
    "agui-activity/KAREN_DEEPAGENTS_PLAN",
    "agui-activity/KAREN_DEEPAGENTS_SUBAGENT",
  ]);
  // Only the active assistant response may contribute live activity. Scanning
  // previous turns leaks stale mission results into the current request.
  const latest = messages[messages.length - 1];
  const activeMessages = latest && typeof latest === "object" &&
    (latest as Record<string, unknown>).role === "assistant" ? [latest] : [];
  for (const rawMessage of activeMessages) {
    if (!rawMessage || typeof rawMessage !== "object") continue;
    const message = rawMessage as Record<string, unknown>;
    if (message.role !== "assistant" || !Array.isArray(message.content)) continue;
    for (const rawPart of message.content) {
      if (!rawPart || typeof rawPart !== "object") continue;
      const part = rawPart as Record<string, unknown>;
      if (part.type !== "data" || typeof part.name !== "string" || !names.has(part.name)) continue;
      if (!part.data || typeof part.data !== "object" || Array.isArray(part.data)) continue;
      const wrapper = part.data as Record<string, unknown>;
      const data = wrapper.content && typeof wrapper.content === "object" &&
        !Array.isArray(wrapper.content) ? wrapper.content as Record<string, unknown> : wrapper;
      const stepId = typeof data.step_id === "string" ? data.step_id :
        typeof data.stepId === "string" ? data.stepId : "";
      if (!stepId || stepId.length > 200) continue;
      const rawStatus = typeof data.status === "string" ? data.status.toLowerCase() : "";
      const eventType: AgentStepEvent["type"] =
        ["failed", "failure", "error", "errored"].includes(rawStatus) ? "agent_step_failed" :
        ["complete", "completed", "finished", "success", "succeeded"].includes(rawStatus) ? "agent_step_completed" :
        ["skipped"].includes(rawStatus) ? "agent_step_skipped" : "agent_step_started";
      const key = `${part.name}:${stepId}`;
      const metadata: Record<string, unknown> = {
        activity_category: part.name,
        observed_status: rawStatus || "unknown",
      };
      for (const field of ["tool", "plugin_id", "extension_id", "actual_provider", "provider", "run_id", "agent_id"]) {
        if (typeof data[field] === "string" && (data[field] as string).length <= 200) {
          metadata[field] = data[field];
        }
      }
      steps.set(key, {
        type: eventType,
        step_id: stepId,
        timestamp: typeof data.timestamp === "string" ? data.timestamp : undefined,
        metadata,
      });
      if (steps.size > 100) {
        const first = steps.keys().next().value;
        if (first) steps.delete(first);
      }
    }
  }
  return Array.from(steps.values());
}

