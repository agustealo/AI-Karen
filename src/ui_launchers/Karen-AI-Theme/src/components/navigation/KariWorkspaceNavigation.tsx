"use client";

import { useEffect, useState, type ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { ChevronDown, Loader2, Plus, Settings2, ShieldCheck, UserRound } from "lucide-react";
import {
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import type { PluginMenuEntry } from "@/plugin_host/route-injector";
import {
  WORKSPACE_ADVANCED_NAV,
  WORKSPACE_PERSONAL_NAV,
  WORKSPACE_PLUGIN_NAV,
  WORKSPACE_PRIMARY_NAV,
  isNestedWorkspaceView,
  type WorkspaceDestination,
} from "./workspace-navigation-registry";

type Props = {
  activeView: string;
  onNavigate: (view: string) => void;
  onNewConversation: () => Promise<void>;
  isAdmin: boolean;
  pluginEntries: readonly PluginMenuEntry[];
  pluginsLoading: boolean;
  renderPluginIcon: (pluginId: string, iconPath?: string) => ReactNode;
};

export function KariWorkspaceNavigation({
  activeView,
  onNavigate,
  onNewConversation,
  isAdmin,
  pluginEntries,
  pluginsLoading,
  renderPluginIcon,
}: Props) {
  const { isMobile, state, setOpen, setOpenMobile } = useSidebar();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [personalOpen, setPersonalOpen] = useState(false);
  const [creatingConversation, setCreatingConversation] = useState(false);
  const [navigationError, setNavigationError] = useState("");

  const inAdvanced = isNestedWorkspaceView(activeView, pluginEntries);
  const inPersonal = WORKSPACE_PERSONAL_NAV.some((item) => item.key === activeView);

  useEffect(() => {
    if (inAdvanced) setAdvancedOpen(true);
  }, [inAdvanced]);

  useEffect(() => {
    if (inPersonal) setPersonalOpen(true);
  }, [inPersonal]);

  const navigate = (view: string) => {
    onNavigate(view);
    if (isMobile) setOpenMobile(false);
  };

  const toggleDisclosure = (name: "advanced" | "personal") => {
    if (!isMobile && state === "collapsed") setOpen(true);
    if (name === "advanced") setAdvancedOpen((open) => !open);
    else setPersonalOpen((open) => !open);
  };

  const createConversation = async () => {
    if (creatingConversation) return;
    setCreatingConversation(true);
    setNavigationError("");
    try {
      await onNewConversation();
      if (isMobile) setOpenMobile(false);
    } catch {
      setNavigationError("New conversation could not be created. Your current conversation is unchanged.");
    } finally {
      setCreatingConversation(false);
    }
  };

  const renderDestination = (item: WorkspaceDestination, nested = false) => {
    const Icon = item.icon;
    return (
      <SidebarMenuItem key={item.key}>
        <SidebarMenuButton
          type="button"
          tooltip={item.label}
          title={item.label}
          aria-current={activeView === item.key ? "page" : undefined}
          isActive={activeView === item.key}
          className={nested ? "kari-nav-item kari-nav-subitem" : "kari-nav-item"}
          onClick={() => navigate(item.key)}
        >
          <Icon aria-hidden="true" className="h-[17px] w-[17px]" />
          <span>{item.label}</span>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  };

  return (
    <>
      <SidebarHeader data-kari-root className="kari-nav-region kari-nav-header">
        <div className="kari-nav-brand group-data-[collapsible=icon]:justify-center">
          <div className="kari-nav-mark" aria-hidden="true">
            <Image src="/brand/karen-mark.svg" alt="" width={25} height={25} />
          </div>
          <div className="min-w-0 group-data-[collapsible=icon]:hidden">
            <p className="kari-nav-wordmark">KAREN</p>
            <p className="kari-nav-caption">Your intelligent workspace</p>
          </div>
        </div>
        <SidebarMenu className="mt-3">
          <SidebarMenuItem>
            <SidebarMenuButton
              type="button"
              tooltip="New conversation"
              title="New conversation"
              disabled={creatingConversation}
              className="kari-nav-new"
              onClick={() => void createConversation()}
            >
              {creatingConversation
                ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                : <Plus className="h-4 w-4" aria-hidden="true" />}
              <span>{creatingConversation ? "Creating..." : "New conversation"}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        {navigationError && (
          <p role="alert" className="kari-nav-error group-data-[collapsible=icon]:sr-only">{navigationError}</p>
        )}
      </SidebarHeader>

      <SidebarContent data-kari-root className="kari-nav-region kari-nav-scroll">
        <SidebarGroup className="kari-nav-group">
          <SidebarGroupLabel className="kari-nav-label">Workspace</SidebarGroupLabel>
          <SidebarMenu>{WORKSPACE_PRIMARY_NAV.map((item) => renderDestination(item))}</SidebarMenu>
        </SidebarGroup>

        <SidebarGroup className="kari-nav-group kari-nav-secondary">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                type="button"
                tooltip="Advanced tools"
                title="Advanced tools"
                data-testid="advanced-tools-toggle"
                aria-expanded={advancedOpen}
                aria-controls="karen-advanced-navigation"
                isActive={inAdvanced}
                className="kari-nav-item kari-nav-disclosure"
                onClick={() => toggleDisclosure("advanced")}
              >
                <Settings2 aria-hidden="true" className="h-4 w-4" />
                <span>Advanced tools</span>
                <ChevronDown
                  aria-hidden="true"
                  className={`kari-nav-chevron group-data-[collapsible=icon]:hidden ${advancedOpen ? "rotate-180" : ""}`}
                />
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
          <div
            id="karen-advanced-navigation"
            data-testid="advanced-tools-content"
            hidden={!advancedOpen}
            className="kari-nav-nested group-data-[collapsible=icon]:hidden"
          >
            <SidebarGroupLabel className="kari-nav-label">Agents & workflows</SidebarGroupLabel>
            <SidebarMenu>{WORKSPACE_ADVANCED_NAV.map((item) => renderDestination(item, true))}</SidebarMenu>
            <SidebarGroupLabel className="kari-nav-label kari-nav-nested-heading">Plugin workspaces</SidebarGroupLabel>
            <SidebarMenu>
              {WORKSPACE_PLUGIN_NAV.map((item) => renderDestination(item, true))}
              {!pluginsLoading && pluginEntries.map((entry) => (
                <SidebarMenuItem key={entry.viewKey}>
                  <SidebarMenuButton
                    type="button"
                    tooltip={entry.label}
                    title={entry.label}
                    aria-current={activeView === entry.viewKey ? "page" : undefined}
                    isActive={activeView === entry.viewKey}
                    className="kari-nav-item kari-nav-subitem"
                    onClick={() => navigate(entry.viewKey)}
                  >
                    {renderPluginIcon(entry.pluginId, entry.iconPath)}
                    <span>{entry.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
              {pluginsLoading && (
                <li role="status" className="kari-nav-loading">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading plugins...
                </li>
              )}
            </SidebarMenu>
          </div>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter data-kari-root className="kari-nav-region kari-nav-footer">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              type="button"
              tooltip="Personalize"
              title="Personalize"
              aria-expanded={personalOpen}
              aria-controls="karen-personal-navigation"
              isActive={inPersonal}
              className="kari-nav-item"
              onClick={() => toggleDisclosure("personal")}
            >
              <UserRound aria-hidden="true" className="h-4 w-4" />
              <span>Personalize</span>
              <ChevronDown
                aria-hidden="true"
                className={`kari-nav-chevron group-data-[collapsible=icon]:hidden ${personalOpen ? "rotate-180" : ""}`}
              />
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <div id="karen-personal-navigation" hidden={!personalOpen} className="kari-nav-nested group-data-[collapsible=icon]:hidden">
          <SidebarMenu>{WORKSPACE_PERSONAL_NAV.map((item) => renderDestination(item, true))}</SidebarMenu>
        </div>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              type="button"
              tooltip="Application Settings"
              title="Application Settings"
              aria-current={activeView === "settings" ? "page" : undefined}
              isActive={activeView === "settings"}
              className="kari-nav-item"
              onClick={() => navigate("settings")}
            >
              <Settings2 aria-hidden="true" className="h-4 w-4" />
              <span>Application Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              type="button"
              tooltip="My Account"
              title="My Account"
              aria-current={activeView === "account" ? "page" : undefined}
              isActive={activeView === "account"}
              className="kari-nav-item"
              onClick={() => navigate("account")}
            >
              <UserRound aria-hidden="true" className="h-4 w-4" />
              <span>My Account</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          {isAdmin && (
            <SidebarMenuItem>
              <SidebarMenuButton asChild tooltip="Admin settings" className="kari-nav-item">
                <Link href="/admin" onClick={() => { if (isMobile) setOpenMobile(false); }}>
                  <ShieldCheck aria-hidden="true" className="h-4 w-4" />
                  <span>Admin settings</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
        </SidebarMenu>
      </SidebarFooter>
    </>
  );
}
