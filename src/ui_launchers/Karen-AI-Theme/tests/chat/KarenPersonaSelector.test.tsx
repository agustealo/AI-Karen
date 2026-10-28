import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { KarenPersonaSelector } from "@/components/chat/assistant-ui/KarenPersonaSelector";
import { apiClient } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiClient: { get: vi.fn(), put: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

const personas = [{ id: "persona-1", name: "Research", is_active: true }];
const preferences = {
  revision: 5,
  active_persona_id: null,
  show_persona_selector: true,
};

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("authenticated persona selector", () => {
  it("lists only runtime-returned personas and confirms persisted selection", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    vi.mocked(apiClient.put).mockResolvedValue({
      ...preferences, revision: 6, active_persona_id: "persona-1",
    });
    render(<KarenPersonaSelector />);
    const select = await screen.findByRole("combobox", { name: "Active Karen persona" });
    fireEvent.change(select, { target: { value: "persona-1" } });
    await waitFor(() => expect(apiClient.put).toHaveBeenCalledWith(
      "/api/personas/preferences/me",
      { active_persona_id: "persona-1", expected_revision: 5 },
    ));
    await waitFor(() => expect((select as HTMLSelectElement).value).toBe("persona-1"));
  });

  it("keeps the previous choice when the authenticated revision-fenced switch fails", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    vi.mocked(apiClient.put).mockRejectedValue(new Error("Denied"));
    render(<KarenPersonaSelector />);
    const select = await screen.findByRole("combobox", { name: "Active Karen persona" });
    fireEvent.change(select, { target: { value: "persona-1" } });
    await screen.findByRole("alert");
    expect((select as HTMLSelectElement).value).toBe("");
    expect(apiClient.put).toHaveBeenCalledWith(
      "/api/personas/preferences/me",
      { active_persona_id: "persona-1", expected_revision: 5 },
    );
  });

  it("rejects an unconfirmed persona switch receipt even if the selected ID matches", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    // A forged/stale response that claims the new persona but not a new
    // persisted revision must not be shown as confirmed.
    vi.mocked(apiClient.put).mockResolvedValue({
      ...preferences, revision: 5, active_persona_id: "persona-1",
    });
    render(<KarenPersonaSelector />);
    const select = await screen.findByRole("combobox", { name: "Active Karen persona" });
    fireEvent.change(select, { target: { value: "persona-1" } });
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Previous selection retained");
    expect((select as HTMLSelectElement).value).toBe("");
  });
});
