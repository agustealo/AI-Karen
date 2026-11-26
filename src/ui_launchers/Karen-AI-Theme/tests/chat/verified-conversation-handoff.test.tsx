import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ loadSession: vi.fn() }));
vi.mock("@/components/chat/SessionProvider", () => ({
  useSession: () => ({ loadSession: mocks.loadSession }),
}));

import { useVerifiedConversationHandoff } from "@/components/chat/useVerifiedConversationHandoff";

const ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

beforeEach(() => {
  mocks.loadSession.mockReset();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("verified workspace conversation handoff", () => {
  it("navigates only after canonical loading confirms success", async () => {
    const openChat = vi.fn();
    const { result } = renderHook(() => useVerifiedConversationHandoff(openChat));
    mocks.loadSession.mockResolvedValue(true);
    await act(async () => { await result.current.openConversation(ID); });
    expect(mocks.loadSession).toHaveBeenCalledExactlyOnceWith(ID);
    expect(openChat).toHaveBeenCalledTimes(1);
    expect(result.current.handoffError).toBe("");
  });

  it.each([false, undefined, null])("does not navigate on unverified resolution %s", async (value) => {
    const openChat = vi.fn();
    const { result } = renderHook(() => useVerifiedConversationHandoff(openChat));
    mocks.loadSession.mockResolvedValue(value);
    await act(async () => { await result.current.openConversation(ID); });
    expect(openChat).not.toHaveBeenCalled();
    expect(result.current.handoffError).toContain("Unable to open that conversation");
    mocks.loadSession.mockResolvedValue(true);
    await act(async () => { await result.current.openConversation(ID); });
    expect(openChat).toHaveBeenCalledTimes(1);
    expect(result.current.handoffError).toBe("");
  });

  it("does not expose raw errors or navigate on rejected authorization", async () => {
    const openChat = vi.fn();
    const { result } = renderHook(() => useVerifiedConversationHandoff(openChat));
    mocks.loadSession.mockRejectedValue(new Error("private transport detail"));
    await act(async () => { await result.current.openConversation(ID); });
    expect(openChat).not.toHaveBeenCalled();
    expect(result.current.handoffError).toContain("Unable to open that conversation");
    expect(result.current.handoffError).not.toContain("private transport detail");
  });

  it("does not start competing loads while one is outstanding", async () => {
    const openChat = vi.fn();
    const load = deferred<boolean>();
    mocks.loadSession.mockReturnValue(load.promise);
    const { result } = renderHook(() => useVerifiedConversationHandoff(openChat));
    let first!: Promise<void>;
    act(() => { first = result.current.openConversation(ID); });
    await act(async () => { await result.current.openConversation("other"); });
    expect(mocks.loadSession).toHaveBeenCalledExactlyOnceWith(ID);
    expect(openChat).not.toHaveBeenCalled();
    await act(async () => { load.resolve(true); await first; });
    expect(openChat).toHaveBeenCalledTimes(1);
  });

  it("does not navigate from a delayed response after leaving the originating view", async () => {
    const openChat = vi.fn();
    const load = deferred<boolean>();
    mocks.loadSession.mockReturnValue(load.promise);
    const { result, unmount } = renderHook(() => useVerifiedConversationHandoff(openChat));
    let first!: Promise<void>;
    act(() => { first = result.current.openConversation(ID); });
    unmount();
    await act(async () => { load.resolve(true); await first; });
    expect(openChat).not.toHaveBeenCalled();
  });
});
