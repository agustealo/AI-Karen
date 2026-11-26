// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PersonalCommunicationsInbox, PersonalCommunicationsInboxProvider } from "./PersonalCommunicationsInbox";
import { INBOX_PATH, INBOX_REFRESH_INTERVAL_MS, type InboxEntry } from "./communications-inbox-contract";

const stubs = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn(), revision: 1, user: "owner" }));
vi.mock("@/lib/api", () => ({
  apiClient: { get: stubs.get, patch: stubs.patch, post: stubs.post },
  captureApiPrincipalScope: (tenant_id: string, user_id: string) => user_id === stubs.user ? { tenant_id, user_id, revision: stubs.revision } : null,
  isCurrentApiPrincipalScope: (scope: { user_id: string; revision: number }) => scope.user_id === stubs.user && scope.revision === stubs.revision,
}));
const timestamp = "2026-11-26T15:00:00Z";
const entry: InboxEntry = {
  entry_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", conversation_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  execution_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", source_kind: "terminal_chat_attention", source_status: "orphaned",
  created_at: timestamp, read_at: null, acknowledged_at: null, archived_at: null, revision: "9007199254740993",
};
const page = (entries: InboxEntry[] = [entry], count = 42) => ({ entries, next_cursor: null, active_unread_count: count, capabilities: { can_mutate: true, producer_enabled: true, can_reconcile: true } });
const workspace = (userId: string, visible = true, open?: (id: string) => Promise<void>) =>
  <PersonalCommunicationsInboxProvider tenantId="tenant" userId={userId}>
    {visible ? <PersonalCommunicationsInbox onOpenConversation={open} /> : <p>Other workspace</p>}
  </PersonalCommunicationsInboxProvider>;
const mount = (open?: (id: string) => Promise<void>) => render(workspace("owner", true, open));
beforeEach(() => { stubs.get.mockReset().mockResolvedValue(page()); stubs.patch.mockReset(); stubs.post.mockReset(); stubs.user = "owner"; stubs.revision = 1; });
afterEach(cleanup);

describe("personal inbox authority", () => {
  it("shows backend count, delegates conversation handoff, and preserves 64-bit revision on explicit acknowledgment", async () => {
    const open = vi.fn().mockResolvedValue(undefined);
    const updated = { ...entry, read_at: timestamp, acknowledged_at: timestamp, revision: "9007199254740994" };
    stubs.get.mockResolvedValueOnce(page()).mockResolvedValue(page([updated], 41));
    stubs.patch.mockResolvedValue({ entry: updated, changed: true });
    mount(open);
    await screen.findByText("Chat execution interrupted");
    expect(screen.getByTestId("personal-inbox-unread").textContent).toBe("42 unread active");
    fireEvent.click(screen.getByRole("button", { name: "Open original conversation" }));
    expect(open).toHaveBeenCalledWith(entry.conversation_id);
    expect(stubs.patch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    await screen.findByText("Acknowledged");
    expect(stubs.patch).toHaveBeenCalledExactlyOnceWith(INBOX_PATH + "/" + entry.entry_id, { operation: "acknowledge", expected_revision: "9007199254740993" }, {}, { tenant_id: "tenant", user_id: "owner", revision: 1 });
    expect(screen.getByTestId("personal-inbox-unread").textContent).toBe("41 unread active");
  });

  it("does not replay uncertain mutations and hides unverified counts until refresh", async () => {
    stubs.patch.mockRejectedValue(new Error("private transport error"));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
    await screen.findByText("Notification change could not be verified. Refresh before trying again.");
    expect(screen.getByTestId("personal-inbox-unread").textContent).toBe("Unread unavailable");
    expect(screen.queryByText("private transport error")).toBeNull();
    expect(stubs.patch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh inbox" }));
    await screen.findByText("Chat execution interrupted");
    expect(stubs.patch).toHaveBeenCalledTimes(1);
  });

  it("rejects a mutation receipt for another source", async () => {
    stubs.patch.mockResolvedValue({ changed: true, entry: { ...entry, execution_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", read_at: timestamp, revision: "9007199254740994" } });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Mark read" }));
    await screen.findByText("Notification change could not be verified. Refresh before trying again.");
    expect(screen.queryByText("Notification state recorded.")).toBeNull();
  });

  it("rejects rounded revisions rather than presenting fabricated records", async () => {
    stubs.get.mockResolvedValue({ ...page(), entries: [{ ...entry, revision: 9007199254740992 }] });
    mount();
    await screen.findByText("Personal inbox unavailable. Refresh to retrieve verified records.");
    expect(screen.getByTestId("personal-inbox-unread").textContent).toBe("Unread unavailable");
  });

  it("ignores a previous account's delayed response", async () => {
    let resolve!: (value: unknown) => void;
    stubs.get.mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValue(page([], 0));
    const view = mount();
    await waitFor(() => expect(stubs.get).toHaveBeenCalledTimes(1));
    stubs.user = "other";
    stubs.revision++;
    view.rerender(workspace("other"));
    await screen.findByText("0 unread active");
    await act(async () => resolve(page()));
    expect(screen.queryByText("Chat execution interrupted")).toBeNull();
    expect(screen.getByTestId("personal-inbox-unread").textContent).toBe("0 unread active");
  });

  it("uses explicit recovery only and requests archive view from server", async () => {
    stubs.get.mockResolvedValueOnce(page()).mockResolvedValue(page([], 0));
    stubs.post.mockResolvedValue({ admitted_count: 0 });
    mount();
    await screen.findByText("Chat execution interrupted");
    expect(stubs.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Recover missed notifications" }));
    await screen.findByText("No additional entries were admitted in this recovery batch.");
    expect(stubs.post).toHaveBeenCalledExactlyOnceWith(INBOX_PATH + "/reconcile", undefined, {}, { tenant_id: "tenant", user_id: "owner", revision: 1 });
    await waitFor(() => expect((screen.getByRole("button", { name: "Archived" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    await waitFor(() => expect(stubs.get).toHaveBeenLastCalledWith(INBOX_PATH + "?limit=25&inbox_filter=archived", { tenant_id: "tenant", user_id: "owner", revision: 1 }));
  });
});

it("keeps a single pending mutation and uncertainty across complete workspace unmount", async () => {
  let reject!: (error: Error) => void;
  stubs.patch.mockReturnValue(new Promise((_resolve, fail) => { reject = fail; }));
  const view = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
  view.rerender(workspace("owner", false));
  expect(screen.queryByText("Chat execution interrupted")).toBeNull();
  view.rerender(workspace("owner"));
  expect((screen.getByRole("button", { name: "Archive" }) as HTMLButtonElement).disabled).toBe(true);
  expect(stubs.get).toHaveBeenCalledTimes(1);
  await act(async () => reject(new Error("Lost response")));
  await screen.findByText("Notification change could not be verified. Refresh before trying again.");
  view.rerender(workspace("owner", false));
  view.rerender(workspace("owner"));
  expect(screen.getByText("Notification change could not be verified. Refresh before trying again.")).toBeTruthy();
  expect(stubs.patch).toHaveBeenCalledTimes(1);
  expect(stubs.get).toHaveBeenCalledTimes(1);
});


describe("bounded authenticated inbox refresh", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
  it("coalesces focus and online events into one read, never a recovery POST", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    mount();
    await screen.findByText("Chat execution interrupted");
    let release!: (value: unknown) => void;
    stubs.get.mockReturnValueOnce(new Promise(done => { release = done; }));
    act(() => { window.dispatchEvent(new Event("focus")); window.dispatchEvent(new Event("online")); });
    expect(stubs.get).toHaveBeenCalledTimes(2);
    expect((screen.getByRole("button", { name: "Archive" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => release(page([], 0)));
    expect(screen.getByTestId("personal-inbox-unread").textContent).toBe("0 unread active");
    expect(stubs.post).not.toHaveBeenCalled();
    expect(stubs.patch).not.toHaveBeenCalled();
  });
  it("does not auto-refresh hidden or offline views", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    mount();
    await screen.findByText("Chat execution interrupted");
    act(() => window.dispatchEvent(new Event("focus")));
    visibility.mockReturnValue("visible");
    online.mockReturnValue(false);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(stubs.get).toHaveBeenCalledTimes(1);
  });
  it("keeps ambiguous mutations locked through reconnect until explicit refresh", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    stubs.patch.mockRejectedValue(new Error("Lost receipt"));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
    await screen.findByText("Notification change could not be verified. Refresh before trying again.");
    act(() => { window.dispatchEvent(new Event("online")); window.dispatchEvent(new Event("focus")); });
    expect(stubs.get).toHaveBeenCalledTimes(1);
    expect(stubs.patch).toHaveBeenCalledTimes(1);
    expect(stubs.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh inbox" }));
    await screen.findByText("Chat execution interrupted");
    expect(stubs.get).toHaveBeenCalledTimes(2);
  });
  it("polls only while mounted and visible at the bounded interval", async () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    vi.useFakeTimers();
    const view = mount();
    await act(async () => { await Promise.resolve(); });
    expect(stubs.get).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(INBOX_REFRESH_INTERVAL_MS - 1); });
    expect(stubs.get).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(stubs.get).toHaveBeenCalledTimes(2);
    view.rerender(workspace("owner", false));
    await act(async () => { await vi.advanceTimersByTimeAsync(INBOX_REFRESH_INTERVAL_MS * 2); });
    expect(stubs.get).toHaveBeenCalledTimes(2);
  });
});

it("honors server-reported producer configuration and read-only entitlements", async () => {
  stubs.get.mockResolvedValueOnce({ ...page(), capabilities: { can_mutate: false, producer_enabled: false, can_reconcile: false } });
  mount();
  await screen.findByText("Read-only inbox access. Your account cannot change notification state.");
  expect(screen.getByText(/New runtime notification production is disabled/)).toBeTruthy();
  for (const label of ["Mark read", "Acknowledge", "Archive", "Recover missed notifications"]) {
    const button = screen.getByRole("button", { name: label });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
  }
  expect(stubs.patch).not.toHaveBeenCalled();
  expect(stubs.post).not.toHaveBeenCalled();
});
