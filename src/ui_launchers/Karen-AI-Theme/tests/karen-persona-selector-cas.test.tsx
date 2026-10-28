import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({
  apiClient: api,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { ApiError } from "@/lib/api";
import { KarenPersonaSelector } from "@/components/chat/assistant-ui/KarenPersonaSelector";

const preferences = {
  revision: 7,
  active_persona_id: "persona-a",
  show_persona_selector: true,
};
const catalog = [
  { id: "persona-a", name: "Alpha", is_active: true },
  { id: "persona-b", name: "Beta", is_active: true },
  { id: "disabled", name: "Disabled", is_active: false },
];

beforeEach(() => {
  api.get.mockReset().mockImplementation((path: string) =>
    Promise.resolve(path === "/api/personas/" ? catalog : preferences));
  api.put.mockReset().mockResolvedValue({
    ...preferences, revision: 8, active_persona_id: "persona-b",
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function mount() {
  render(<KarenPersonaSelector />);
  return await screen.findByRole("combobox", { name: "Active Karen persona" }) as HTMLSelectElement;
}

describe("shared persona selector uses Persona Studio's canonical CAS owner", () => {
  it("loads the backend revision and never shows inactive personas", async () => {
    const selector = await mount();
    expect(selector.value).toBe("persona-a");
    expect(screen.queryByRole("option", { name: "Disabled" })).toBeNull();
    expect(api.put).not.toHaveBeenCalled();
  });

  it("confirms a selection only after a revision-fenced backend receipt", async () => {
    const selector = await mount();
    fireEvent.change(selector, { target: { value: "persona-b" } });
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/api/personas/preferences/me",
      { active_persona_id: "persona-b", expected_revision: 7 },
    ));
    await waitFor(() => expect(selector.value).toBe("persona-b"));
    expect(api.put).toHaveBeenCalledTimes(1);
  });

  it("never displays an unconfirmed persona when the server receipt is invalid", async () => {
    api.put.mockResolvedValueOnce({
      ...preferences, revision: 7, active_persona_id: "persona-b",
    });
    const selector = await mount();
    fireEvent.change(selector, { target: { value: "persona-b" } });
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("Previous selection retained"));
    expect(selector.value).toBe("persona-a");
  });

  it("requires explicit reload after another tab wins and retries with the new revision", async () => {
    api.put.mockRejectedValueOnce(new ApiError(409, "private tenant conflict"))
      .mockResolvedValueOnce({ ...preferences, revision: 10, active_persona_id: null });
    const selector = await mount();
    fireEvent.change(selector, { target: { value: "persona-b" } });
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("another window"));
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(selector.value).toBe("persona-a");
    expect(selector.disabled).toBe(true);
    expect(api.put).toHaveBeenCalledTimes(1);
    api.get.mockResolvedValueOnce({ ...preferences, revision: 9, active_persona_id: "persona-b" });
    fireEvent.click(screen.getByRole("button", { name: "Reload current persona" }));
    await waitFor(() => expect(selector.disabled).toBe(false));
    expect(selector.value).toBe("persona-b");
    fireEvent.change(selector, { target: { value: "" } });
    await waitFor(() => expect(api.put).toHaveBeenLastCalledWith(
      "/api/personas/preferences/me",
      { active_persona_id: null, expected_revision: 9 },
    ));
    await waitFor(() => expect(selector.value).toBe(""));
  });

  it("stays locked on failed or invalid conflict reload, without inventing a saved selection", async () => {
    api.put.mockRejectedValueOnce(new ApiError(409, "conflict"));
    const selector = await mount();
    fireEvent.change(selector, { target: { value: "persona-b" } });
    await waitFor(() => expect(selector.disabled).toBe(true));
    api.get.mockRejectedValueOnce(new Error("private backend failure"));
    fireEvent.click(screen.getByRole("button", { name: "Reload current persona" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("could not be reloaded"));
    expect(selector.disabled).toBe(true);
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(api.put).toHaveBeenCalledTimes(1);
  });

  it("does not update state from a delayed response after unmount", async () => {
    let release!: (value: unknown) => void;
    api.put.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    const mounted = render(<KarenPersonaSelector />);
    const selector = await screen.findByRole("combobox", { name: "Active Karen persona" });
    fireEvent.change(selector, { target: { value: "persona-b" } });
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    mounted.unmount();
    await act(async () => release({ ...preferences, revision: 8, active_persona_id: "persona-b" }));
    expect(api.put).toHaveBeenCalledTimes(1);
  });
});
