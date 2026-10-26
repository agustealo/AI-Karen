import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({
  apiClient: backend,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { ApiError } from "@/lib/api";
import { useKarenPersistedDraft } from "@/components/chat/copilotkit/useKarenPersistedDraft";

const CONV = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TARGET = "/api/conversations/" + CONV + "/draft";

function Surface() {
  const draft = useKarenPersistedDraft(CONV);
  return <div>
    <span data-testid="draft-status">{draft.status}</span>
    <span data-testid="draft-synced">{String(draft.synced)}</span>
    <textarea aria-label="Saved draft" value={draft.draft}
      onChange={e => draft.setText(e.target.value)} />
    <button onClick={draft.retry}>Retry</button>
    <button onClick={draft.discardAndReload}>Reload saved</button>
  </div>;
}

beforeEach(() => {
  backend.get.mockReset().mockResolvedValue({ text: "Persisted earlier", revision: 4 });
  backend.put.mockReset().mockImplementation(
    async (_path: string, payload: { text: string; expected_revision: number }) =>
      ({ text: payload.text, revision: payload.expected_revision + 1 }),
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CK-07E6 authenticated composer draft hook", () => {
  it("hydrates only from backend and autosaves a verified CAS receipt", async () => {
    render(<Surface />);
    await waitFor(() => expect(screen.getByTestId("draft-status").textContent)
      .toBe("ready"));
    const input = screen.getByRole("textbox", { name: "Saved draft" }) as HTMLTextAreaElement;
    expect(input.value).toBe("Persisted earlier");
    fireEvent.change(input, { target: { value: "New in this window" } });
    expect(screen.getByTestId("draft-synced").textContent).toBe("false");
    await waitFor(() => expect(backend.put).toHaveBeenCalledWith(
      TARGET, { text: "New in this window", expected_revision: 4 },
      expect.objectContaining({ signal: expect.any(Object) }),
    ), { timeout: 4000 });
    await waitFor(() => expect(screen.getByTestId("draft-synced").textContent)
      .toBe("true"));
    expect(input.value).toBe("New in this window");
    expect(backend.get).toHaveBeenCalledWith(TARGET);
  });

  it("preserves local text on a stale-tab conflict, never overwrites another window", async () => {
    backend.put.mockRejectedValueOnce(new ApiError(409, "changed elsewhere"));
    render(<Surface />);
    await waitFor(() => expect(screen.getByTestId("draft-status").textContent)
      .toBe("ready"));
    const input = screen.getByRole("textbox", { name: "Saved draft" }) as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "My unsent private changes" } });
    await waitFor(() => expect(screen.getByTestId("draft-status").textContent)
      .toBe("conflict"), { timeout: 4000 });
    expect(input.value).toBe("My unsent private changes");
    expect(screen.getByTestId("draft-synced").textContent).toBe("false");
    expect(backend.put).toHaveBeenCalledTimes(1);
  });

  it("refreshes saved contents on focus when no local unsent edits exist", async () => {
    backend.get.mockResolvedValueOnce({ text: "Old tab", revision: 1 })
      .mockResolvedValueOnce({ text: "Edited from second tab", revision: 2 });
    render(<Surface />);
    await waitFor(() => expect(screen.getByTestId("draft-status").textContent)
      .toBe("ready"));
    expect((screen.getByRole("textbox", { name: "Saved draft" }) as HTMLTextAreaElement).value)
      .toBe("Old tab");
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(backend.get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(
      (screen.getByRole("textbox", { name: "Saved draft" }) as HTMLTextAreaElement).value,
    ).toBe("Edited from second tab"));
    expect(backend.put).not.toHaveBeenCalled();
  });

  it("fails closed when draft storage cannot be read; never fakes a save", async () => {
    backend.get.mockRejectedValueOnce(new ApiError(503, "storage outage"));
    render(<Surface />);
    await waitFor(() => expect(screen.getByTestId("draft-status").textContent)
      .toBe("unavailable"));
    expect(screen.getByTestId("draft-synced").textContent).toBe("false");
    expect(backend.put).not.toHaveBeenCalled();
  });

  it("refuses invalid backend receipt before trusting any saved text", async () => {
    backend.get.mockResolvedValueOnce({
      text: "Untrusted long content", revision: -3,
    });
    render(<Surface />);
    await waitFor(() => expect(screen.getByTestId("draft-status").textContent)
      .toBe("unavailable"));
    expect(backend.put).not.toHaveBeenCalled();
  });
});
