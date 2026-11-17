import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PocketTTSWorkspace from "@/components/plugins/PocketTTSWorkspace";

const registry = vi.hoisted(() => ({
  refresh: vi.fn(),
  loading: false,
  error: null as string | null,
  enabled: true,
  present: true,
}));

vi.mock("@/plugin_host/registry", () => ({
  usePluginRegistry: () => ({
    plugins: registry.present ? [{
      id: "pocket-tts",
      displayName: "Pocket TTS",
      version: "1.0.0",
      rawStatus: registry.enabled ? "enabled" : "disabled",
      enabled: registry.enabled,
    }] : [],
    loading: registry.loading,
    error: registry.error,
    refresh: registry.refresh,
  }),
}));

vi.mock("@/components/plugins/PluginRecommendedModels", () => ({
  PluginRecommendedModels: ({ pluginId }: { pluginId: string }) => (
    <div data-testid="governed-model-download-owner">{pluginId}</div>
  ),
}));
vi.mock("@/components/settings/LocalVoiceEngineSettings", () => ({
  default: ({ engineFilter }: { engineFilter?: string }) => (
    <div data-testid="voice-runtime-owner">{engineFilter}</div>
  ),
}));

beforeEach(() => {
  registry.loading = false;
  registry.error = null;
  registry.enabled = true;
  registry.present = true;
  registry.refresh.mockReset().mockResolvedValue(undefined);
});

afterEach(cleanup);

describe("first-class Pocket TTS user workspace", () => {
  it("exposes model setup and scoped voice playback without fabricating runtime health", () => {
    render(<PocketTTSWorkspace />);
    expect(screen.getByRole("main", { name: "Pocket TTS plugin workspace" })).toBeTruthy();
    expect(screen.getByTestId("pocket-tts-plugin-status").textContent).toContain("Plugin enabled");
    expect(screen.getByTestId("governed-model-download-owner").textContent).toBe("pocket-tts");
    expect(screen.getByTestId("voice-runtime-owner").textContent).toBe("pocket-tts");
    expect(screen.getByText(/model and voice readiness verified separately/i)).toBeTruthy();
    expect(screen.queryByText("Voice ready")).toBeNull();
    expect(registry.refresh).not.toHaveBeenCalled();
  });

  it("does not confuse installed and enabled, and links to the plugin owner", () => {
    registry.enabled = false;
    const openPlugins = vi.fn();
    render(<PocketTTSWorkspace onOpenPlugins={openPlugins} />);
    expect(screen.getByTestId("pocket-tts-plugin-status").textContent).toContain("Plugin disabled");
    expect(screen.getByTestId("pocket-tts-plugin-not-enabled")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open plugin management" }));
    expect(openPlugins).toHaveBeenCalledOnce();
  });

  it("reports missing catalog rather than presenting an invented plugin", () => {
    registry.present = false;
    render(<PocketTTSWorkspace />);
    expect(screen.getByTestId("pocket-tts-plugin-status").textContent)
      .toContain("Plugin not found");
    expect(screen.getByTestId("pocket-tts-plugin-not-enabled")).toBeTruthy();
  });

  it("refreshes both backend-owned model and voice projections", async () => {
    const openVoice = vi.fn();
    render(<PocketTTSWorkspace onOpenVoiceStudio={openVoice} />);
    fireEvent.click(screen.getByRole("button", { name: "Open Voice Studio" }));
    expect(openVoice).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Refresh Pocket TTS status" }));
    await waitFor(() => expect(registry.refresh).toHaveBeenCalledOnce());
    expect(screen.getByTestId("voice-runtime-owner").textContent).toBe("pocket-tts");
    expect(screen.getByTestId("governed-model-download-owner").textContent).toBe("pocket-tts");
  });

  it("displays catalog failures, with no unverified enabled claim", async () => {
    registry.error = "unavailable";
    render(<PocketTTSWorkspace />);
    expect(screen.getByTestId("pocket-tts-plugin-status").textContent).toContain("unavailable");
    expect(screen.getByRole("alert").textContent).toContain("Plugin inventory unavailable");

    registry.refresh.mockRejectedValue(new Error("transport lost"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Refresh Pocket TTS status" }));
    });
    expect(screen.getByTestId("pocket-tts-plugin-status").textContent).toContain("unavailable");
  });
});
