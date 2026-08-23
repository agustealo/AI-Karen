import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useConversationEvents } from "../hooks/useConversationEvents";
import { useExecutionEvents } from "../hooks/useExecutionEvents";
import { useUserNotifications } from "../hooks/useUserNotifications";

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
