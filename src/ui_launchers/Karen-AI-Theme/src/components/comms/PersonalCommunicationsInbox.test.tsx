// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PersonalCommunicationsInbox } from "./PersonalCommunicationsInbox";
import { INBOX_PATH, type InboxEntry } from "./communications-inbox-contract";

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
const page = (entries: InboxEntry[] = [entry], count = 42) => ({ entries, next_cursor: null, active_unread_count: count });
const mount = (open?: (id: string) => Promise<void>) => render(<PersonalCommunicationsInbox tenantId="tenant" userId="owner" onOpenConversation={open} />);
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
    view.rerender(<PersonalCommunicationsInbox tenantId="tenant" userId="other" />);
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
