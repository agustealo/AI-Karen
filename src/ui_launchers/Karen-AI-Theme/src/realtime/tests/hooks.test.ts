import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useConversationEvents } from "../hooks/useConversationEvents";
import { useExecutionEvents } from "../hooks/useExecutionEvents";
import { useUserNotifications } from "../hooks/useUserNotifications";
import { useRealtimeConnection, getRealtimeClient } from "../hooks/useRealtimeConnection";
import { usePresence, getPresenceClient } from "../hooks/usePresence";

describe("realtime hooks", () => {
  it("useConversationEvents collects events", async () => {
    const { result } = renderHook(() =>
      useConversationEvents(
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000012"
      )
    );
    expect(result.current.events).toEqual([]);
  });

  it("useExecutionEvents collects events", async () => {
    const { result } = renderHook(() =>
      useExecutionEvents(
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000013"
      )
    );
    expect(result.current.events).toEqual([]);
  });

  it("useUserNotifications collects events", async () => {
    const { result } = renderHook(() =>
      useUserNotifications("00000000-0000-0000-0000-000000000001")
    );
    expect(result.current.notifications).toEqual([]);
  });
});


it("keeps tenant changes and simultaneous hook instances isolated", () => {
  const tenantA = "00000000-0000-0000-0000-000000000001";
  const tenantB = "00000000-0000-0000-0000-000000000002";
  const first = renderHook(({ tenant }) => useRealtimeConnection(tenant), { initialProps: { tenant: tenantA } });
  const second = renderHook(() => useRealtimeConnection(tenantA));
  const old = first.result.current.client;
  expect(first.result.current.state).toBe("degraded");
  expect(second.result.current.client).not.toBe(old);
  first.rerender({ tenant: tenantB });
  expect(first.result.current.client).not.toBe(old);
  expect(old.connectionState).toBe("disconnected");
  expect(second.result.current.state).toBe("degraded");
  expect(first.result.current.state).toBe("degraded");
  expect(getRealtimeClient(tenantA)).not.toBe(getRealtimeClient(tenantA));
  first.unmount();
  second.unmount();
});

it("does not share an unscoped presence cache", () => {
  const a = renderHook(() => usePresence());
  const b = renderHook(() => usePresence());
  expect(a.result.current.client).not.toBe(b.result.current.client);
  expect(getPresenceClient()).not.toBe(getPresenceClient());
  expect(a.result.current.state).toBeNull();
  expect(b.result.current.state).toBeNull();
  a.unmount();
  b.unmount();
});
