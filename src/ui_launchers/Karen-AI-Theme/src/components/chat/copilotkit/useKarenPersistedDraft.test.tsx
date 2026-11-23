// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api";
import { useKarenPersistedDraft } from "./useKarenPersistedDraft";

vi.mock("@/lib/api", () => ({
  apiClient: {
    get: vi.fn(),
    put: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    constructor(public status: number) {
      super("draft request failed");
    }
  },
}));

type DraftRecord = { text: string; revision: number };

class DraftBroadcastChannel {
  static channels: DraftBroadcastChannel[] = [];

  readonly name: string;
  readonly messages: unknown[] = [];
  onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
  closed = false;

  constructor(name: string) {
    this.name = name;
    DraftBroadcastChannel.channels.push(this);
  }

  postMessage(data: unknown): void {
    this.messages.push(data);
    for (const channel of DraftBroadcastChannel.channels) {
      if (channel !== this && !channel.closed && channel.name === this.name) {
        channel.onmessage?.({ data } as MessageEvent<unknown>);
      }
    }
  }

  close(): void {
    this.closed = true;
  }
}

const getDraft = vi.mocked(apiClient.get);
const putDraft = vi.mocked(apiClient.put);
const conversationId = "b7b37a75-4b14-48de-a0ac-2a14b51c7c25";

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("authenticated persisted composer draft synchronization", () => {
  let visibility: DocumentVisibilityState;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    DraftBroadcastChannel.channels = [];
    visibility = "visible";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => visibility,
    });
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => visibility !== "visible",
    });
    vi.stubGlobal("BroadcastChannel", DraftBroadcastChannel);
    getDraft.mockResolvedValue({ text: "", revision: 0 });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    delete (document as unknown as Record<string, unknown>).visibilityState;
    delete (document as unknown as Record<string, unknown>).hidden;
  });

  it("makes one initial read and no more reads over sixty healthy idle seconds", async () => {
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    expect(result.current.status).toBe("ready");
    expect(getDraft).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(getDraft).toHaveBeenCalledTimes(1);
    expect(putDraft).not.toHaveBeenCalled();
  });

  it("coalesces focus and visibility resume into one authenticated reread", async () => {
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    visibility = "hidden";

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(getDraft).toHaveBeenCalledTimes(1);

    visibility = "visible";
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    await flush();

    expect(getDraft).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("ready");
  });

  it("notifies another tab with revision only, then rereads canonical server text", async () => {
    let canonical: DraftRecord = { text: "", revision: 0 };
    getDraft.mockImplementation(async () => ({ ...canonical }));
    putDraft.mockImplementation(async (_endpoint, payload) => {
      const request = payload as { text: string; expected_revision: number };
      expect(request.expected_revision).toBe(canonical.revision);
      canonical = { text: request.text, revision: canonical.revision + 1 };
      return { ...canonical };
    });

    const first = renderHook(() => useKarenPersistedDraft(conversationId));
    const second = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    expect(getDraft).toHaveBeenCalledTimes(2);

    act(() => first.result.current.setText("A draft from the first tab"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await flush();

    expect(putDraft).toHaveBeenCalledTimes(1);
    expect(getDraft).toHaveBeenCalledTimes(3);
    expect(second.result.current.draft).toBe("A draft from the first tab");
    expect(second.result.current.synced).toBe(true);
    expect(DraftBroadcastChannel.channels[0].messages).toEqual([{ revision: 1 }]);
  });

  it("never replaces unsaved local text from a peer notification", async () => {
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    act(() => result.current.setText("Private local edits"));
    expect(result.current.synced).toBe(false);

    act(() => {
      DraftBroadcastChannel.channels[0].onmessage?.({
        data: { revision: 2, text: "untrusted peer content" },
      } as MessageEvent<unknown>);
    });
    await flush();

    expect(result.current.draft).toBe("Private local edits");
    expect(getDraft).toHaveBeenCalledTimes(1);
    expect(putDraft).not.toHaveBeenCalled();
  });

  it("ignores stale or malformed peer revisions, and cleans up listeners on unmount", async () => {
    const { unmount } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    const channel = DraftBroadcastChannel.channels[0];

    act(() => {
      channel.onmessage?.({ data: { revision: 0 } } as MessageEvent<unknown>);
      channel.onmessage?.({ data: { revision: "10", text: "never trust this" } } as MessageEvent<unknown>);
    });
    expect(getDraft).toHaveBeenCalledTimes(1);

    unmount();
    expect(channel.closed).toBe(true);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(getDraft).toHaveBeenCalledTimes(1);
  });
});
