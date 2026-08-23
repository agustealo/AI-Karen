import { describe, it, expect } from "vitest";
import { validateEvent, isSafePayload, matchesTopic } from "../events";
import { RealtimeEvent } from "../types";

describe("events", () => {
  it("validates a correct event", () => {
    const event = validateEvent({
      event_id: "00000000-0000-0000-0000-000000000001",
      event_type: "conversation.message.created.v1",
      version: 1,
      tenant_id: "00000000-0000-0000-0000-000000000002",
      resource_id: "00000000-0000-0000-0000-000000000003",
      correlation_id: "00000000-0000-0000-0000-000000000004",
      occurred_at: new Date().toISOString(),
      payload: {},
    });
    expect(event).not.toBeNull();
    expect(event?.event_type).toBe("conversation.message.created.v1");
  });

  it("rejects missing event_type", () => {
    const event = validateEvent({ event_id: "00000000-0000-0000-0000-000000000001" });
    expect(event).toBeNull();
  });

  it("rejects unsafe payloads", () => {
    expect(isSafePayload({ system_prompt: "..." })).toBe(false);
    expect(isSafePayload({ status: "ok" })).toBe(true);
  });

  it("matches topic with same tenant and resource", () => {
    const evt = {
      event_id: "00000000-0000-0000-0000-000000000001",
      event_type: "execution.started.v1",
      tenant_id: "00000000-0000-0000-0000-000000000002",
      resource_id: "00000000-0000-0000-0000-000000000003",
      correlation_id: "00000000-0000-0000-0000-000000000004",
      occurred_at: new Date().toISOString(),
      payload: {},
    } as RealtimeEvent;
    expect(matchesTopic("tenant:00000000-0000-0000-0000-000000000002:execution:00000000-0000-0000-0000-000000000003", evt)).toBe(true);
    expect(matchesTopic("tenant:00000000-0000-0000-0000-000000000002:execution:other", evt)).toBe(false);
  });
});
