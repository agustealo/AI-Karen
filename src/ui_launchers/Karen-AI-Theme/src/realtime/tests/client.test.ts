import { describe, it, expect } from "vitest";
import { RealtimeClient } from "../client";

describe("RealtimeClient", () => {
  it("connects and transitions state", async () => {
    const client = new RealtimeClient("00000000-0000-0000-0000-000000000001");
    const states: string[] = [];
    client.onStateChange((prev, next) => {
      states.push(next);
    });
    client.connect();
    expect(client.connectionState).toBe("connecting");
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(client.connectionState).toBe("connected");
    expect(states).toContain("connected");
  });

  it("subscribes and receives events", async () => {
    const client = new RealtimeClient("00000000-0000-0000-0000-000000000001");
    const events: unknown[] = [];
    client.subscribe(
      (registry) => registry.conversation("00000000-0000-0000-0000-000000000012"),
      (event) => events.push(event),
    );
    client.simulateIncoming({
      event_id: "00000000-0000-0000-0000-000000000001",
      event_type: "conversation.message.created.v1",
      version: 1,
      tenant_id: "00000000-0000-0000-0000-000000000001",
      resource_id: "00000000-0000-0000-0000-000000000012",
      correlation_id: "00000000-0000-0000-0000-000000000004",
      occurred_at: new Date().toISOString(),
      payload: {},
    });
    expect(events.length).toBe(1);
  });

  it("unsubscribes", () => {
    const client = new RealtimeClient("00000000-0000-0000-0000-000000000001");
    const topic = client.subscribe(
      (registry) => registry.conversation("00000000-0000-0000-0000-000000000012"),
      () => {},
    );
    client.unsubscribe(topic.subscriptionId);
    expect(client.activeSubscriptions).toHaveLength(0);
  });
});
