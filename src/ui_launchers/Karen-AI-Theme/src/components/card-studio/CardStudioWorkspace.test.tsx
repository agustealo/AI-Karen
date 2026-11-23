// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const endpoint = vi.hoisted(() => ({
  catalog: vi.fn(),
  list: vi.fn(),
  submit: vi.fn(),
}));
vi.mock("@/lib/useAuth", () => ({
  useAuth: () => ({
    user: {
      user_id: "11111111-1111-1111-1111-111111111111",
      tenant_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    },
  }),
}));
vi.mock("@/lib/card-studio-api", async (original) => {
  const actual = await original<typeof import("@/lib/card-studio-api")>();
  return {
    ...actual,
    listCardStudioCatalog: endpoint.catalog,
    listSavedCardTemplates: endpoint.list,
    submitCardMutation: endpoint.submit,
  };
});

import { CardStudioWorkspace } from "./CardStudioWorkspace";
import {
  ApiError,
  type CardDefinition,
  type CatalogEntry,
} from "@/lib/card-studio-api";

const valid: CardDefinition = {
  schema_version: 1,
  template_key: "saved-clock",
  title: "Saved clock",
  layout: "stack",
  density: "comfortable",
  interaction_mode: "read_only",
  slots: [{ slot_id: "primary", component_type: "time.observation" }],
};
const catalog: CatalogEntry[] = [{
  origin: "system", editable: false,
  definition: { ...valid, template_key: "system-time-observation" },
}];

beforeEach(() => {
  endpoint.catalog.mockReset().mockResolvedValue(catalog);
  endpoint.list.mockReset().mockResolvedValue([]);
  endpoint.submit.mockReset();
  window.sessionStorage.clear();
  vi.stubGlobal("crypto", {
    randomUUID: vi.fn(() => "99999999-9999-4999-8999-999999999999"),
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function ready() {
  render(<CardStudioWorkspace />);
  await screen.findByTestId("card-studio-workspace");
}

function fillDraft() {
  fireEvent.change(screen.getByLabelText("Title"), {
    target: { value: "Saved clock" },
  });
  fireEvent.change(screen.getByLabelText("Template key"), {
    target: { value: "saved-clock" },
  });
}

describe("authenticated Card Studio layout UI", () => {
  it("fails closed when the backend feature is off", async () => {
    endpoint.catalog.mockRejectedValueOnce(new ApiError(404, "not enabled"));
    render(<CardStudioWorkspace />);
    const notice = await screen.findByTestId("card-studio-unavailable");
    expect(notice.textContent).toContain("Card Studio unavailable");
    expect(screen.queryByRole("button", { name: "Create draft" })).toBeNull();
    expect(endpoint.submit).not.toHaveBeenCalled();
  });

  it("shows host layout geometry with no fabricated source observation", async () => {
    await ready();
    const preview = screen.getByTestId("card-studio-preview");
    expect(preview.textContent).toContain("Time Observation");
    expect(preview.textContent).toContain("Not connected to runtime evidence");
    expect(preview.textContent).not.toContain("12:00");
    expect(preview.textContent).not.toContain("verified source");

    fireEvent.click(screen.getByRole("button", { name: "Add slot" }));
    expect(screen.getAllByText("Not connected to runtime evidence")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Move primary down" }));
    const names = preview.querySelectorAll("article");
    expect(names[0].textContent).toContain("slot_1");
    expect(names[1].textContent).toContain("primary");
  });

  it("only displays a saved revision after an exact confirmed receipt", async () => {
    endpoint.submit.mockResolvedValueOnce({
      template_id: "55555555-5555-4555-8555-555555555555",
      template_key: valid.template_key,
      revision: 1,
      lifecycle: "draft",
      definition: valid,
    });
    await ready();
    fillDraft();
    fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await screen.findByText(/Saved revision 1 with a verified server receipt/);
    expect(endpoint.submit).toHaveBeenCalledTimes(1);
    expect(endpoint.submit.mock.calls[0][0]).toMatchObject({
      operation: "create",
      idempotency_key: "99999999-9999-4999-8999-999999999999",
      draft: valid,
    });
    expect(screen.getByRole("button", { name: "Save revision" })).toBeDisabled();
    expect(screen.getByText("Revision 1 · draft")).toBeTruthy();
  });

  it("retains the exact payload and idempotency key after uncertain network loss", async () => {
    endpoint.submit
      .mockRejectedValueOnce(new TypeError("network dropped after possible commit"))
      .mockResolvedValueOnce({
        template_id: "55555555-5555-4555-8555-555555555555",
        template_key: valid.template_key,
        revision: 1,
        lifecycle: "draft",
        definition: valid,
      });
    await ready();
    fillDraft();
    fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await screen.findByText("Unverified save outcome");
    expect(screen.getByLabelText("Title")).toBeDisabled();
    expect(endpoint.submit).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.length).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Retry identical request" }));
    await screen.findByText(/Saved revision 1 with a verified server receipt/);
    expect(endpoint.submit).toHaveBeenCalledTimes(2);
    expect(endpoint.submit.mock.calls[1][0]).toEqual(endpoint.submit.mock.calls[0][0]);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("does not show success for a revision CAS conflict", async () => {
    const stored = {
      template_id: "55555555-5555-4555-8555-555555555555",
      template_key: valid.template_key,
      revision: 2,
      lifecycle: "draft" as const,
      definition: valid,
    };
    endpoint.list.mockResolvedValueOnce([stored]);
    endpoint.submit.mockRejectedValueOnce(new ApiError(409, "conflict"));
    await ready();
    fireEvent.click(screen.getByRole("button", { name: /Saved clock/ }));
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Unsaved change" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("concurrent revision");
    });
    expect(screen.queryByText(/Saved revision 3/)).toBeNull();
    expect(screen.getByLabelText("Title")).not.toBeDisabled();
  });
});
