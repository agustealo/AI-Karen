// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { webcrypto } from "node:crypto";
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

type DraftRecord = { text: string; revision: number; attachment_references: { source_id: string; revision: string }[] };

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
    getDraft.mockResolvedValue({ text: "", revision: 0, attachment_references: [] } as never);
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
    let canonical: DraftRecord = { text: "", revision: 0, attachment_references: [] };
    getDraft.mockImplementation(async () => ({ ...canonical } as never));
    putDraft.mockImplementation(async (_endpoint, payload) => {
      const request = payload as { text: string; expected_revision: number };
      expect(request.expected_revision).toBe(canonical.revision);
      canonical = { text: request.text, revision: canonical.revision + 1, attachment_references: [] };
      return { ...canonical } as never;
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

describe("staged attachment-bound draft preparation", () => {
  const first = { source_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", revision: "a".repeat(64) };
  const second = { source_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", revision: "b".repeat(64) };
  const references = [first, second];
  const text = "Saved private draft";

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("crypto", webcrypto);
    getDraft.mockResolvedValue({ text, revision: 7, attachment_references: references } as never);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("builds the exact ordered immutable v2 snapshot without preclearing", async () => {
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    // Fixed Python json.dumps(sort_keys=True, separators=(",", ":"))
    // SHA-256 vector; do not recalculate using the browser's serialization.
    const digest = "e1e0621b3a710eb63db47864a9d9b89ec137ad424320a2f939681831e3e1c23b";
    await act(async () => {
      const snapshot = await result.current.prepareAttachmentSubmission(text, references);
      expect(snapshot?.submissionId).toBe("draft-v2-7-" + digest);
      expect(snapshot?.attachmentReferences).toEqual(references);
      expect(Object.isFrozen(snapshot)).toBe(true);
      expect(Object.isFrozen(snapshot?.attachmentReferences)).toBe(true);
      expect(Object.isFrozen(snapshot?.attachmentReferences[0])).toBe(true);
      expect(snapshot?.attachmentReferences[0]).not.toBe(first);
      expect(await result.current.prepareRevisionSubmission(text)).toBeNull();
      expect(await result.current.prepareSubmission(text)).toBe(false);
    });
    expect(putDraft).not.toHaveBeenCalled();
    expect(result.current.draft).toBe(text);
    expect(result.current.attachments).toEqual(references);
  });

  it("flushes an edited attached draft and binds the acknowledged next revision", async () => {
    putDraft.mockImplementation(async (_path, payload) => {
      const request = payload as { text: string; expected_revision: number; attachment_references: typeof references };
      expect(request.expected_revision).toBe(7);
      return { text: request.text, revision: 8, attachment_references: request.attachment_references } as never;
    });
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    act(() => result.current.setText("Edited private draft"));
    await act(async () => {
      const snapshot = await result.current.prepareAttachmentSubmission("Edited private draft", references);
      expect(snapshot?.submissionId).toMatch(/^draft-v2-8-[a-f0-9]{64}$/);
      expect(snapshot?.attachmentReferences).toEqual(references);
    });
    expect(putDraft).toHaveBeenCalledTimes(1);
    expect(result.current.draft).toBe("Edited private draft");
    expect(result.current.attachments).toEqual(references);
  });

  it("rejects missing, malformed or mismatched attachment selection", async () => {
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    await act(async () => {
      for (const selection of [[], [first], [second, first], [first, first]]) {
        expect(await result.current.prepareAttachmentSubmission(text, selection)).toBeNull();
      }
    });
    expect(putDraft).not.toHaveBeenCalled();
  });

  it.each(["text", "selection", "unmount", "refresh"] as const)(
    "refuses a stale snapshot if %s changes while SHA-256 is pending", async (change) => {
      let finish!: (bytes: ArrayBuffer) => void;
      const digest = vi.fn(() => new Promise<ArrayBuffer>(resolve => { finish = resolve; }));
      vi.stubGlobal("crypto", { subtle: { digest } });
      const { result, unmount } = renderHook(() => useKarenPersistedDraft(conversationId));
      await flush();
      const pending = result.current.prepareAttachmentSubmission(text, references);
      await flush();
      expect(digest).toHaveBeenCalledTimes(1);
      if (change === "text") act(() => result.current.setText("Newer text"));
      else if (change === "selection") act(() => result.current.updateAttachments([first]));
      else if (change === "unmount") unmount();
      else {
        getDraft.mockRejectedValueOnce(new Error("Read failed"));
        await act(async () => { await result.current.refreshSubmittedDraft(); });
        expect(result.current.status).toBe("unavailable");
      }
      await act(async () => {
        finish(new ArrayBuffer(32));
        expect(await pending).toBeNull();
      });
      expect(putDraft).not.toHaveBeenCalled();
    },
  );

  it("fails closed when WebCrypto rejects", async () => {
    vi.stubGlobal("crypto", { subtle: { digest: vi.fn().mockRejectedValue(new Error("Unavailable")) } });
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    await act(async () => {
      expect(await result.current.prepareAttachmentSubmission(text, references)).toBeNull();
    });
    expect(putDraft).not.toHaveBeenCalled();
  });
});

describe("read-only retained retry draft", () => {
  const text = "Saved private draft";
  const references = [
    { source_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", revision: "a".repeat(64) },
    { source_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", revision: "b".repeat(64) },
  ];
  const identity = "draft-v2-7-e1e0621b3a710eb63db47864a9d9b89ec137ad424320a2f939681831e3e1c23b";
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("crypto", webcrypto);
    getDraft.mockResolvedValue({ text, revision: 7, attachment_references: references } as never);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("requires a fresh exact revision and digest without writing", async () => {
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    await act(async () => {
      expect(await result.current.readRetainedRetryDraft(identity)).toEqual({
        submissionId: identity, text, attachmentReferences: references,
      });
      expect(await result.current.readRetainedRetryDraft()).toEqual({
        submissionId: identity, text, attachmentReferences: references,
      });
      expect(await result.current.readRetainedRetryDraft("draft-v1-7")).toBeNull();
      expect(await result.current.readRetainedRetryDraft(identity.replace("-7-", "-8-"))).toBeNull();
      getDraft.mockRejectedValueOnce(new Error("Read unavailable"));
      expect(await result.current.readRetainedRetryDraft(identity)).toBeNull();
    });
    expect(putDraft).not.toHaveBeenCalled();
  });

  it("never flushes a newer unsaved edit to manufacture retry eligibility", async () => {
    const { result } = renderHook(() => useKarenPersistedDraft(conversationId));
    await flush();
    act(() => result.current.setText("New unsaved edit"));
    await act(async () => {
      expect(await result.current.readRetainedRetryDraft(identity)).toBeNull();
    });
    expect(result.current.draft).toBe("New unsaved edit");
    expect(putDraft).not.toHaveBeenCalled();
  });
});
