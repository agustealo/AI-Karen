import { describe, expect, it } from "vitest";
import { projectObservedAgentSteps } from "@/components/chat/observedAgentSteps";

const activity = (step_id: string, status: string) => ({
  type: "data",
  name: "agui-activity/KAREN_AGENT_STEP",
  data: { step_id, status, agent_id: "research", run_id: "run-current" },
});
const assistant = (...content: unknown[]) => ({ role: "assistant", content });

describe("observed AG-UI rail projection", () => {
  it("does not reuse older assistant activity for a new user turn", () => {
    expect(projectObservedAgentSteps([
      assistant(activity("previous", "completed")),
      { role: "user", content: [{ type: "text", text: "new task" }] },
    ])).toEqual([]);
  });
  it("consolidates lifecycle updates for the same observed step", () => {
    const steps = projectObservedAgentSteps([
      assistant(activity("step-1", "running"), activity("step-1", "completed")),
    ]);
    expect(steps).toHaveLength(1);
    expect(steps[0].type).toBe("agent_step_completed");
    expect(steps[0].metadata?.run_id).toBe("run-current");
  });
  it("preserves failures without manufacturing a successful outcome", () => {
    const steps = projectObservedAgentSteps([assistant(activity("step-2", "failed"))]);
    expect(steps).toHaveLength(1);
    expect(steps[0].type).toBe("agent_step_failed");
  });
  it("rejects foreign, malformed and unrecognized activity parts", () => {
    const steps = projectObservedAgentSteps([assistant(
      { type: "data", name: "another-source", data: { step_id: "fake", status: "completed" } },
      { type: "data", name: "agui-activity/KAREN_AGENT_STEP", data: { status: "completed" } },
      { type: "text", text: "Completed" },
    )]);
    expect(steps).toEqual([]);
  });
  it("keeps cancelled and skipped steps terminal and rejects unknown statuses", () => {
    const steps = projectObservedAgentSteps([assistant(
      activity("cancel", "running"), activity("cancel", "cancelled"),
      activity("skip", "skipped"), activity("unknown", "unrecognized"),
    )]);
    expect(steps.map(step => step.type)).toEqual(["agent_step_cancelled", "agent_step_skipped"]);
  });
  it("separates agents and runs with the same step ID using canonical camel-case identities", () => {
    const snapshot = (runId: string, agentId: string, status: string) => ({
      type: "data", name: "agui-activity/KAREN_AGENT_STEP",
      data: { content: { runId, agentId, stepId: "shared", status } },
    });
    const steps = projectObservedAgentSteps([assistant(
      snapshot("r1", "a", "running"), snapshot("r1", "b", "running"),
      snapshot("r2", "a", "running"), snapshot("r1", "a", "completed"),
    )]);
    expect(steps.map(step => step.type)).toEqual([
      "agent_step_completed", "agent_step_started", "agent_step_started",
    ]);
    expect(steps.map(step => step.metadata?.agent_id)).toEqual(["a", "b", "a"]);
    expect(steps.map(step => step.metadata?.run_id)).toEqual(["r1", "r1", "r2"]);
  });
  it("bounds projected event cardinality", () => {
    const steps = projectObservedAgentSteps([assistant(
      ...Array.from({ length: 150 }, (_, i) => activity(`step-${i}`, "running")),
    )]);
    expect(steps).toHaveLength(100);
    expect(steps[0].step_id).toBe("step-50");
  });
});
