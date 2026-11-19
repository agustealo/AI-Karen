import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KariWorkspaceNavigation } from "@/components/navigation/KariWorkspaceNavigation";
import {
  WORKSPACE_ADVANCED_NAV,
  WORKSPACE_PLUGIN_NAV,
  WORKSPACE_PRIMARY_NAV,
  isNestedWorkspaceView,
} from "@/components/navigation/workspace-navigation-registry";
import type { PluginMenuEntry } from "@/plugin_host/route-injector";

const sidebarState = vi.hoisted(() => ({
  isMobile: false,
  state: "expanded" as "expanded" | "collapsed",
  setOpen: vi.fn(),
  setOpenMobile: vi.fn(),
}));

vi.mock("next/image", () => ({
  default: ({ alt, ...props }: { alt: string; src: string; width: number; height: number }) =>
    React.createElement("img", { ...props, alt }),
}));

vi.mock("@/components/ui/sidebar", () => {
  const div = ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) =>
    React.createElement("div", props, children);
  const ul = ({ children, ...props }: React.HTMLAttributes<HTMLUListElement>) =>
    React.createElement("ul", props, children);
  const li = ({ children, ...props }: React.HTMLAttributes<HTMLLIElement>) =>
    React.createElement("li", props, children);
  return {
    useSidebar: () => sidebarState,
    SidebarContent: div,
    SidebarFooter: div,
    SidebarGroup: div,
    SidebarGroupLabel: div,
    SidebarHeader: div,
    SidebarMenu: ul,
    SidebarMenuItem: li,
    SidebarMenuButton: ({
      children, tooltip: _tooltip, isActive, asChild, ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
      tooltip?: string; isActive?: boolean; asChild?: boolean;
    }) => asChild
      ? React.createElement("div", { "data-active": isActive }, children)
      : React.createElement("button", { ...props, "data-active": isActive }, children),
  };
});

const pluginEntry: PluginMenuEntry = {
  viewKey: "weather::home",
  pluginId: "weather",
  entryId: "home",
  label: "Weather Workspace",
  order: null,
  isDefault: false,
};

function mount(overrides: Partial<React.ComponentProps<typeof KariWorkspaceNavigation>> = {}) {
  const onNavigate = vi.fn();
  const onNewConversation = vi.fn().mockResolvedValue(undefined);
  render(
    <KariWorkspaceNavigation
      activeView="chat"
      onNavigate={onNavigate}
      onNewConversation={onNewConversation}
      isAdmin={false}
      pluginEntries={[pluginEntry]}
      pluginsLoading={false}
      renderPluginIcon={() => <span aria-hidden="true">◈</span>}
      {...overrides}
    />,
  );
  return { onNavigate, onNewConversation };
}

beforeEach(() => {
  sidebarState.isMobile = false;
  sidebarState.state = "expanded";
  sidebarState.setOpen.mockReset();
  sidebarState.setOpenMobile.mockReset();
});

afterEach(() => cleanup());

describe("task-first Kari workspace navigation", () => {
  it("keeps five canonical destinations and no duplicated plugin keys", () => {
    expect(WORKSPACE_PRIMARY_NAV.map((item) => item.key)).toEqual([
      "chat", "commsCenter", "agentsOverview", "tasks", "pluginOverview",
    ]);
    expect(WORKSPACE_PLUGIN_NAV.map((item) => item.key)).toEqual(["pocketTts"]);
    expect(WORKSPACE_ADVANCED_NAV.map((item) => item.key)).toEqual(["agents", "jobs", "cronJobs"]);
    expect(isNestedWorkspaceView(pluginEntry.viewKey, [pluginEntry])).toBe(true);
    expect(isNestedWorkspaceView("account", [pluginEntry])).toBe(false);
  });

  it("routes the five primary destinations through the parent without fake execution", () => {
    const { onNavigate } = mount();
    for (const key of ["Activity", "Automations", "My Tasks", "Tools & plugins"]) {
      fireEvent.click(screen.getByRole("button", { name: key, exact: true }));
    }
    expect(onNavigate.mock.calls.map(([view]) => view)).toEqual([
      "commsCenter", "agentsOverview", "tasks", "pluginOverview",
    ]);
    expect(screen.getByRole("button", { name: "Chat", exact: true }).getAttribute("aria-current")).toBe("page");
    expect(screen.queryByRole("button", { name: "Weather Workspace" })).toBeNull();
  });

  it("reveals backend-derived plugin routes without generating a second plugin registry", () => {
    const { onNavigate } = mount({ activeView: pluginEntry.viewKey });
    const toggle = screen.getByTestId("advanced-tools-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Weather Workspace" }));
    expect(onNavigate).toHaveBeenCalledWith(pluginEntry.viewKey);
    expect(screen.getByRole("button", { name: "Weather Workspace" }).getAttribute("aria-current")).toBe("page");
  });

  it("keeps admin entry server-auth derived and closes the mobile drawer on navigation", () => {
    sidebarState.isMobile = true;
    const { onNavigate } = mount({ isAdmin: false });
    expect(screen.queryByText("Admin settings")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    expect(onNavigate).toHaveBeenCalledWith("commsCenter");
    expect(sidebarState.setOpenMobile).toHaveBeenCalledWith(false);
  });

  it("uses the canonical new-session callback and never claims a failed save", async () => {
    const onNewConversation = vi.fn().mockRejectedValue(new Error("backend unavailable"));
    mount({ onNewConversation });
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("could not be created"));
    expect(onNewConversation).toHaveBeenCalledOnce();
  });

  it("makes collapsed advanced workflows discoverable without a parallel menu", () => {
    sidebarState.state = "collapsed";
    mount();
    fireEvent.click(screen.getByTestId("advanced-tools-toggle"));
    expect(sidebarState.setOpen).toHaveBeenCalledWith(true);
    expect(screen.getByTestId("advanced-tools-toggle").getAttribute("aria-expanded")).toBe("true");
  });
});
