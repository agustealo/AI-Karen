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
  it("offers an explicit new conversation only after persisted persona selection", async () => {
    const createNewSession = vi.fn().mockResolvedValue(undefined);
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    vi.mocked(apiClient.put).mockResolvedValue({
      ...preferences, revision: 6, active_persona_id: "persona-1",
    });

    render(<KarenPersonaSelector onStartNewConversation={createNewSession} />);
    expect(screen.queryByRole("button", { name: "Start new conversation for selected persona" })).toBeNull();
    const select = await screen.findByRole("combobox", { name: "Active Karen persona" });
    fireEvent.change(select, { target: { value: "persona-1" } });
    const start = await screen.findByRole("button", { name: "Start new conversation for selected persona" });
    expect(screen.getByRole("status").textContent).toContain("Persona selection saved");
    expect(createNewSession).not.toHaveBeenCalled();
    fireEvent.click(start);
    await waitFor(() => expect(createNewSession).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole(
      "button", { name: "Start new conversation for selected persona",
    )).toBeNull());
  });

  it("retains handoff notice and surfaces canonical creation failures", async () => {
    const createNewSession = vi.fn().mockRejectedValue(new Error("write failed"));
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    vi.mocked(apiClient.put).mockResolvedValue({
      ...preferences, revision: 6, active_persona_id: "persona-1",
    });
    render(<KarenPersonaSelector onStartNewConversation={createNewSession} />);
    fireEvent.change(await screen.findByRole("combobox", { name: "Active Karen persona" }), {
      target: { value: "persona-1" },
    });
    fireEvent.click(await screen.findByRole("button", {
      name: "Start new conversation for selected persona",
    }));
    expect((await screen.findByRole("alert")).textContent)
      .toContain("Unable to create a new conversation");
    expect(screen.getByRole("button", {
      name: "Start new conversation for selected persona",
    })).toBeTruthy();
  });

  it("does not display a verified handoff after an unconfirmed switch", async () => {
    const createNewSession = vi.fn();
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    vi.mocked(apiClient.put).mockRejectedValue(new Error("no confirmation"));
    render(<KarenPersonaSelector onStartNewConversation={createNewSession} />);
    fireEvent.change(await screen.findByRole("combobox", { name: "Active Karen persona" }), {
      target: { value: "persona-1" },
    });
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", {
      name: "Start new conversation for selected persona",
    })).toBeNull();
    expect(createNewSession).not.toHaveBeenCalled();
  });

});
