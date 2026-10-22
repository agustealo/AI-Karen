import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { KarenPersonaSelector } from "@/components/chat/assistant-ui/KarenPersonaSelector";
import { apiClient } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

const personas = [{ id: "persona-1", name: "Research", is_active: true }];
const preferences = { active_persona_id: null, show_persona_selector: true };

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("authenticated persona selector", () => {
  it("lists only runtime-returned personas and confirms persisted selection", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    vi.mocked(apiClient.post).mockResolvedValue({ ...preferences, active_persona_id: "persona-1" });
    render(<KarenPersonaSelector />);
    const select = await screen.findByRole("combobox", { name: "Active Karen persona" });
    fireEvent.change(select, { target: { value: "persona-1" } });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith(
      "/api/personas/preferences/switch", { persona_id: "persona-1" },
    ));
    await waitFor(() => expect((select as HTMLSelectElement).value).toBe("persona-1");
  });

  it("keeps the previous choice when the authenticated switch fails", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Denied"));
    render(<KarenPersonaSelector />);
    const select = await screen.findByRole("combobox", { name: "Active Karen persona" });
    fireEvent.change(select, { target: { value: "persona-1" } });
    await screen.findByRole("alert");
    expect((select as HTMLSelectElement).value).toBe("");
  });
  it("rejects an unconfirmed persona switch receipt", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) =>
      path === "/api/personas/" ? personas : preferences);
    vi.mocked(apiClient.post).mockResolvedValue({ ...preferences, active_persona_id: null });
    render(<KarenPersonaSelector />);
    const select = await screen.findByRole("combobox", { name: "Active Karen persona" });
    fireEvent.change(select, { target: { value: "persona-1" } });
    expect((await screen.findByRole("alert")).textContent).toContain("Previous selection retained");
    expect((select as HTMLSelectElement).value).toBe("");
  });

});
