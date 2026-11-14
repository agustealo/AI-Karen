import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KarenComposerRuntimeCatalog } from "@/components/chat/KarenComposerRuntimeCatalog";

const api = vi.hoisted(() => ({
  getRuntimeProviderCatalog: vi.fn(),
  get: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ apiClient: api }));

const inventory = {
  catalog_version: "live",
  providers: [
    {
      id: "local-provider", label: "Local provider", enabled: true,
      configured: true, healthy: true, health: { status: "healthy" },
      allowed_for_current_user: true,
      models: [
        { id: "model-one", label: "Model one", available: true },
        { id: "retired", label: "Retired", available: false },
      ],
    },
    {
      id: "unconfigured", label: "Unconfigured provider", enabled: true,
      configured: false, healthy: false, health: { status: "unknown" },
      allowed_for_current_user: true,
      models: [{ id: "unverified", label: "Unverified", available: true }],
    },
    {
      id: "restricted", label: "Restricted provider", enabled: true,
      configured: true, healthy: true, health: { status: "healthy" },
      allowed_for_current_user: false,
      models: [{ id: "restricted-model", label: "Restricted", available: true }],
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getRuntimeProviderCatalog.mockResolvedValue(inventory);
});
afterEach(cleanup);

describe("consumer provider and model controls", () => {
  it("shows the actual provider/model picker and only forwards an eligible pair", async () => {
    const change = vi.fn();
    render(<KarenComposerRuntimeCatalog selection={null} onSelectionChange={change} />);
    const provider = await screen.findByRole("combobox", { name: "Requested model provider" });
    const model = screen.getByRole("combobox", { name: "Requested model" });
    await waitFor(() => expect((provider as HTMLSelectElement).disabled).toBe(false));
    expect((model as HTMLSelectElement).disabled).toBe(true);
    expect(screen.getByText("Automatic routing (Karen default)")).not.toBeNull();
    expect(screen.queryByRole("option", { name: /Restricted provider/ })).toBeNull();
    fireEvent.change(provider, { target: { value: "local-provider" } });
    expect(change).toHaveBeenCalledWith(null);
    expect((model as HTMLSelectElement).disabled).toBe(false);
    expect(screen.queryByRole("option", { name: "Retired" })).toBeNull();
    fireEvent.change(model, { target: { value: "model-one" } });
    expect(change).toHaveBeenLastCalledWith({ provider: "local-provider", model: "model-one" });
    expect(api.get).not.toHaveBeenCalled();
  });

  it("shows unconfigured providers only in diagnostics, never the chat picker", async () => {
    const change = vi.fn();
    const setup = vi.fn();
    render(<KarenComposerRuntimeCatalog selection={null} onSelectionChange={change} onOpenProviders={setup} />);
    const provider = await screen.findByRole("combobox", { name: "Requested model provider" });
    await waitFor(() => expect((provider as HTMLSelectElement).disabled).toBe(false));
    expect(screen.queryByRole("option", { name: /Unconfigured provider/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Restricted provider/ })).toBeNull();
    expect(screen.getByText(/provider hidden from chat selection/)).not.toBeNull();
    fireEvent.click(screen.getByText("Advanced provider and agent details"));
    expect(screen.getByText(/Unconfigured provider/)).not.toBeNull();
    expect(screen.getByText("Not configured")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Configure providers" }));
    expect(setup).toHaveBeenCalledTimes(1);
    expect(change).not.toHaveBeenCalled();
  });

  it("hides unverified and degraded providers even if their catalog marks a model available", async () => {
    api.getRuntimeProviderCatalog.mockResolvedValueOnce({
      catalog_version: "live",
      providers: [{
        id: "degraded-remote", label: "Degraded remote",
        enabled: true, configured: true, healthy: false,
        health: { status: "degraded" },
        allowed_for_current_user: true,
        models: [{ id: "model-claimed-ready", available: true }],
      }],
    });
    const change = vi.fn();
    render(<KarenComposerRuntimeCatalog selection={null} onSelectionChange={change} />);
    await screen.findByText(/No selectable models are verified/);
    expect(screen.queryByRole("option", { name: /Degraded remote/ })).toBeNull();
    expect((screen.getByRole("combobox", { name: "Requested model" }) as HTMLSelectElement).disabled).toBe(true);
    expect(change).not.toHaveBeenCalled();
  });

  it("revalidates a previously selected model on refresh instead of forwarding a stale pair", async () => {
    const change = vi.fn();
    api.getRuntimeProviderCatalog.mockResolvedValueOnce(inventory).mockResolvedValueOnce({
      ...inventory, providers: inventory.providers.filter((item) => item.id !== "local-provider"),
    });
    render(<KarenComposerRuntimeCatalog
      selection={{ provider: "local-provider", model: "model-one" }}
      onSelectionChange={change}
    />);
    await waitFor(() => expect(api.getRuntimeProviderCatalog).toHaveBeenCalledTimes(1));
    await screen.findByRole("button", { name: "Refresh models" });
    fireEvent.click(screen.getByRole("button", { name: "Refresh models" }));
    await waitFor(() => expect(api.getRuntimeProviderCatalog).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(change).toHaveBeenCalledWith(null));
  });

  it("allows setup and retry without claiming availability when the backend catalog fails", async () => {
    api.getRuntimeProviderCatalog.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(inventory);
    const change = vi.fn();
    const setup = vi.fn();
    render(<KarenComposerRuntimeCatalog selection={null} onSelectionChange={change} onOpenProviders={setup} />);
    await screen.findByText(/Runtime provider catalog unavailable/);
    expect((screen.getByRole("combobox", { name: "Requested model provider" }) as HTMLSelectElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Refresh models" }));
    await waitFor(() => expect((screen.getByRole("combobox", { name: "Requested model provider" }) as HTMLSelectElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Configure providers" }));
    expect(setup).toHaveBeenCalledTimes(1);
    expect(change).not.toHaveBeenCalled();
  });

  it("does not invent a model when no healthy configured provider exists", async () => {
    api.getRuntimeProviderCatalog.mockResolvedValueOnce({
      catalog_version: "live",
      providers: inventory.providers.filter((entry) => entry.id === "unconfigured"),
    });
    const change = vi.fn();
    render(<KarenComposerRuntimeCatalog selection={null} onSelectionChange={change} />);
    await screen.findByText(/No selectable models are verified/);
    expect((screen.getByRole("combobox", { name: "Requested model" }) as HTMLSelectElement).disabled).toBe(true);
    expect(change).not.toHaveBeenCalled();
  });
});
