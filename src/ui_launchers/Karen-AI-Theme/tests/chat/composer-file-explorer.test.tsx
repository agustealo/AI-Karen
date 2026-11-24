import React from "react";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KarenComposerFileExplorer } from "@/components/chat/KarenComposerFileExplorer";

const calls = vi.hoisted(() => ({ inventory: vi.fn(), plugin: vi.fn() }));
vi.mock("@/components/plugins/FileExplorerInventoryHost", () => ({
  FileExplorerInventoryHost: ({ mode, children }: { mode: string; children: (props: Record<string, unknown>) => React.ReactNode }) => {
    calls.inventory(mode);
    return <>{children({ authorized: false, items: [] })}</>;
  },
}));
vi.mock("@/components/plugins/PluginHost", () => ({
  PluginHost: ({ pluginId, componentProps }: { pluginId: string; componentProps: Record<string, unknown> }) => {
    calls.plugin(pluginId, componentProps);
    return <div>Shared file browser</div>;
  },
}));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Composer file browser", () => {
  it("mounts canonical selection-only host on explicit open and releases it on close", () => {
    render(<KarenComposerFileExplorer pluginId="file-explorer" />);
    expect(calls.inventory).not.toHaveBeenCalled();
    const button = screen.getByRole("button", { name: "Browse files" });
    fireEvent.click(button);
    expect(calls.inventory).toHaveBeenCalledWith("selection");
    expect(calls.plugin).toHaveBeenCalledWith("file-explorer", { authorized: false, items: [] });
    expect(screen.getByText(/Selection is not attached/)).toBeTruthy();
    fireEvent.click(button);
    expect(screen.queryByText("Shared file browser")).toBeNull();
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });
});
