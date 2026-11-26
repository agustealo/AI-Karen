import { describe, it, expect, vi } from "vitest";
import { RealtimeClient } from "../client";
import { PresenceClient } from "../presence";

const tenant = "00000000-0000-0000-0000-000000000001";
const foreign = "00000000-0000-0000-0000-000000000002";
const resource = "00000000-0000-0000-0000-000000000012";

describe("RealtimeClient", () => {
  it("never fabricates connectivity, including after disconnect", () => {
    vi.useFakeTimers();
    try {
      const client = new RealtimeClient(tenant);
      const states: string[] = [];
      client.onStateChange((_prev, next) => states.push(next));
      client.connect();
      expect(client.connectionState).toBe("degraded");
      vi.advanceTimersByTime(100);
      expect(client.connectionState).toBe("degraded");
      client.disconnect();
      vi.advanceTimersByTime(100);
      expect(client.connectionState).toBe("disconnected");
      expect(states).toEqual(["degraded", "disconnected"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not deliver injected events or claim a live subscription", () => {
    const client = new RealtimeClient(tenant);
    const handler = vi.fn();
    const error = vi.fn();
    client.onError(error);
    client.connect();
    const sub = client.subscribe((registry) => registry.conversation(resource), handler);
    expect(sub.state).toBe("degraded");
    expect(client.activeSubscriptions).toEqual([]);
    client.simulateIncoming({
      event_id: resource, event_type: "conversation.message.created.v1",
      version: 1, tenant_id: tenant, resource_id: resource,
      correlation_id: resource, occurred_at: new Date().toISOString(), payload: {},
    });
    expect(handler).not.toHaveBeenCalled();
    expect(error).toHaveBeenCalledOnce();
    client.unsubscribe(sub.subscriptionId);
    expect(client.activeSubscriptions).toEqual([]);
  });

  it("rejects foreign and malformed topics", () => {
    const client = new RealtimeClient(tenant);
    expect(() => client.subscribe(`tenant:${foreign}:conversation:${resource}`, vi.fn())).toThrow();
    expect(() => client.subscribe(`tenant:${tenant}:admin:${resource}`, vi.fn())).toThrow();
    expect(() => client.subscribe(`tenant:${tenant}:notifications:${resource}`, vi.fn())).toThrow();
  });
});

describe("PresenceClient", () => {
  it("never treats local data as authenticated presence", () => {
    const client = new PresenceClient();
    const handler = vi.fn();
    const unsubscribe = client.subscribe(handler);
    expect(() => client.update({ user_id: resource, session_id: tenant, status: "online" })).toThrow(
      "Authenticated presence transport unavailable"
    );
    expect(handler).not.toHaveBeenCalled();
    unsubscribe();
    client.disconnect();
  });
});
