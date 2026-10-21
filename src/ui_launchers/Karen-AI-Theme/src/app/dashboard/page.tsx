"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Image from "next/image";
import dynamic from "next/dynamic";
import {
  Bell,
  Binary,
  ChevronDown,
  Bot as BotIcon,
  LayoutGrid,
  Loader2,
  MessageSquare,
  PlugZap,
  RefreshCw,
  ScrollText,
  SettingsIcon as SettingsIconLucide,
  SlidersHorizontal,
  UserCircle,
  Trophy,
} from "lucide-react";

import { AuthWrapper } from "@/components/AuthWrapper";
import SettingsDialogComponent from "@/components/settings/SettingsDialog";
import { PluginHost } from "@/components/plugins/PluginHost";
import { PluginErrorBoundary } from "@/plugin_host/PluginErrorBoundary";
import PluginOverviewPage from "@/components/plugins/PluginOverviewPage";
import AgentsOverviewPage from "@/components/automation/AgentsOverviewPage";
import AgentsPage from "@/components/automation/AgentsPage";
import TasksPage from "@/components/automation/TasksPage";
import JobsPage from "@/components/automation/JobsPage";
import CronJobsPage from "@/components/automation/CronJobsPage";
import AccountPage from "@/components/account/AccountPage";
import GrowthPage from "@/components/growth/GrowthPage";
import ChatInterface, {
  SessionProvider,
  useSession,
} from "@/components/chat/ChatInterface";
import CommsCenterPage from "@/components/comms/CommsCenterPage";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Sidebar,
  SidebarContent as AppSidebarContent,
  SidebarFooter as AppSidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader as AppSidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger as AppSidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";

import { usePluginRegistry } from "@/plugin_host/registry";
import { usePluginRoutes } from "@/plugin_host/route-injector";

// Keep legacy chat as the default until full assistant-ui/AG-UI proof passes.
const USE_ASSISTANT_UI_CHAT = process.env.NEXT_PUBLIC_KAREN_ASSISTANT_UI_ENABLED === "true";
const KarenAssistantChat = dynamic(
  () => import("@/components/chat/assistant-ui/KarenAssistantChat"),
  { ssr: false },
);

type ActiveView =
  | "chat"
  | "commsCenter"
  | "account"
  | "growth"
  | "settings"
  | "agentsOverview"
  | "agents"
  | "tasks"
  | "jobs"
  | "cronJobs"
  | "pluginOverview"
  | string;

type BackendStatus = "checking" | "ready" | "failed";

type NavItem = {
  key: ActiveView;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  className?: string;
};

type NavSubgroup = {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  items: NavItem[];
};

function AgentWorkspaceView({ openChat }: { openChat: () => void }) {
  const { loadSession, setWorkspaceRunId } = useSession();
  const [handoffError, setHandoffError] = useState("");
  const { workspaceRunId } = useSession();

  const openConversation = useCallback(async (conversationId: string) => {
    setHandoffError("");
    try {
      // Canonical session provider fetches and authorizes the conversation.
      // Navigate only after a successful backend-owned load.
      await loadSession(conversationId);
      openChat();
    } catch {
      setHandoffError("Unable to open that conversation. It may be unavailable or you may not have access.");
    }
  }, [loadSession, openChat]);

  return (
    <>
      {handoffError && <p role="alert" className="mb-3 text-sm text-destructive">{handoffError}</p>}
      {workspaceRunId && <div className="mb-3 flex items-center gap-2 rounded-lg border p-2 text-xs"><span>Context: execution {workspaceRunId.slice(0, 8)}</span><Button type="button" size="sm" variant="outline" onClick={() => setWorkspaceRunId(null)}>Clear context</Button></div>}
      <AgentsPage onAskKaren={openChat} onOpenConversation={openConversation}
        onDiscussRun={(runId) => { setWorkspaceRunId(runId); openChat(); }} />
    </>
  );
}

function DashboardNavigationContent({ children }: { children: React.ReactNode }) {
  const { isMobile, setOpenMobile } = useSidebar();

  const handleNavigationClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!isMobile) return;
    const target = event.target;
    if (target instanceof Element && target.closest('[data-sidebar="menu-button"]')) {
      setOpenMobile(false);
    }
  };

  return (
    <AppSidebarContent onClick={handleNavigationClick} className="space-y-4 p-2">
      {children}
    </AppSidebarContent>
  );
}

const MAX_BACKEND_RETRIES = 10;
const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 30000;

const PRIMARY_NAV: Array<{
  section: string;
  items: NavItem[];
}> = [
  {
    section: "Start here",
    items: [
      { key: "chat", label: "Chat", icon: MessageSquare },
      { key: "commsCenter", label: "Messages & channels", icon: Bell },
    ],
  },
  {
    section: "Explore",
    items: [
      { key: "agentsOverview", label: "Automations", icon: BotIcon },
      { key: "pluginOverview", label: "Tools & plugins", icon: PlugZap },
    ],
  },
  {
    section: "Personal",
    items: [
      { key: "account", label: "My Account", icon: UserCircle },
      { key: "growth", label: "Growth", icon: Trophy },
      {
        key: "settings",
        label: "Application Settings",
        icon: SettingsIconLucide,
      },
    ],
  },
];

const RUNTIME_SUBGROUPS: NavSubgroup[] = [
  {
    label: "Agents & Workflows",
    icon: Binary,
    items: [
      { key: "agents", label: "Agents", icon: BotIcon },
      { key: "tasks", label: "Tasks", icon: ScrollText },
      { key: "jobs", label: "Jobs", icon: LayoutGrid },
      { key: "cronJobs", label: "Cron Jobs", icon: Binary },
    ],
  },
];

export default function DashboardPage() {
  const [activeMainView, setActiveMainView] = useState<ActiveView>("chat");
  const [karenPanelOpen, setKarenPanelOpen] = useState(false);
  const karenLauncherRef = useRef<HTMLButtonElement | null>(null);
  const karenPanelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!karenPanelOpen || activeMainView === "chat") return;
    karenPanelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setKarenPanelOpen(false);
        karenLauncherRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [karenPanelOpen, activeMainView]);
  const [advancedToolsOpen, setAdvancedToolsOpen] = useState(false);
  const [imgErrors, setImgErrors] = useState<Record<string, boolean>>({});
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");
  const [backendCheckRetries, setBackendCheckRetries] = useState(0);
  const [backendErrorMessage, setBackendErrorMessage] = useState<string>("");

  const mountedRef = useRef(true);
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { loading: pluginsLoading } = usePluginRegistry();
  const { sidebarEntries, viewMap } = usePluginRoutes();

  const clearRetryTimeout = useCallback(() => {
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current);
      retryTimeoutRef.current = null;
    }
  }, []);

  const runBackendHealthCheck = useCallback(async () => {
    clearRetryTimeout();
    setBackendStatus("checking");
    setBackendErrorMessage("");

    let attempt = 0;

    while (mountedRef.current && attempt <= MAX_BACKEND_RETRIES) {
      try {
        const response = await fetch("/api/health", {
          method: "GET",
          cache: "no-cache",
          headers: {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            Pragma: "no-cache",
            Expires: "0",
          },
        });

        if (!mountedRef.current) {
          return;
        }

        if (response.ok) {
          setBackendStatus("ready");
          setBackendCheckRetries(attempt);
          setBackendErrorMessage("");
          return;
        }
      } catch (error) {
        if (!mountedRef.current) {
          return;
        }

        console.warn("[Dashboard] Backend health check failed:", error);
      }

      if (attempt >= MAX_BACKEND_RETRIES) {
        break;
      }

      const nextAttempt = attempt + 1;
      const delay = Math.min(
        BACKOFF_BASE_MS * Math.pow(2, attempt),
        BACKOFF_MAX_MS,
      );

      setBackendCheckRetries(nextAttempt);

      await new Promise<void>((resolve) => {
        retryTimeoutRef.current = setTimeout(resolve, delay);
      });

      attempt = nextAttempt;
    }

    if (!mountedRef.current) {
      return;
    }

    setBackendStatus("failed");
    setBackendErrorMessage(
      "KAREN could not connect to backend services after multiple attempts.",
    );
  }, [clearRetryTimeout]);

  useEffect(() => {
    mountedRef.current = true;
    void runBackendHealthCheck();

    return () => {
      mountedRef.current = false;
      clearRetryTimeout();
    };
  }, [clearRetryTimeout, runBackendHealthCheck]);

  const handleRetryBackend = useCallback(() => {
    setBackendCheckRetries(0);
    void runBackendHealthCheck();
  }, [runBackendHealthCheck]);

  const renderPluginMenuIcon = useCallback(
    (pluginId: string, iconPath?: string) => {
      const imgKey = `${pluginId}-${iconPath ?? "default"}`;

      if (iconPath && !imgErrors[imgKey]) {
        const cleanIconPath = iconPath.startsWith("assets/")
          ? iconPath.slice("assets/".length)
          : iconPath;

        const frontendPath = `/plugin_repo/${pluginId}/assets/${cleanIconPath}`;

        return (
          <Image
            src={frontendPath}
            alt=""
            width={16}
            height={16}
            className="h-4 w-4 shrink-0 rounded-sm object-contain"
            onError={() =>
              setImgErrors((prev) => ({
                ...prev,
                [imgKey]: true,
              }))
            }
            unoptimized
          />
        );
      }

      return <PlugZap className="h-4 w-4" />;
    },
    [imgErrors],
  );

  const staticViewMap = useMemo<Record<string, React.ReactNode>>(
    () => ({

      settings: <SettingsDialogComponent />,
      pluginOverview: <PluginOverviewPage />,
      agentsOverview: <AgentsOverviewPage />,
      agents: <AgentWorkspaceView openChat={() => setActiveMainView("chat")} />,
      tasks: <TasksPage />,
      jobs: <JobsPage />,
      cronJobs: <CronJobsPage />,
      commsCenter: <CommsCenterPage />,
      account: <AccountPage />,
      growth: <GrowthPage />,
    }),
    [],
  );

  const currentViewContent = useMemo(() => {
    if (staticViewMap[activeMainView]) {
      return staticViewMap[activeMainView];
    }

    if (viewMap[activeMainView]) {
      return (
        <Suspense
          fallback={
            <div className="flex items-center justify-center p-12">
              <Loader2 className="h-8 w-8 animate-spin text-primary opacity-50" />
            </div>
          }
        >
          <PluginErrorBoundary pluginId={viewMap[activeMainView]}>
            <PluginHost pluginId={viewMap[activeMainView]} />
          </PluginErrorBoundary>
        </Suspense>
      );
    }

    return (
      <div className="flex h-full min-h-[240px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20">
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">
            This view is not available.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Select another area from the sidebar.
          </p>
        </div>
      </div>
    );
  }, [activeMainView, staticViewMap, viewMap]);

  const backendGate =
    backendStatus === "ready" ? null : (
      <div
        className="flex min-h-0 flex-1 items-center justify-center px-6"
        data-testid="backend-health-gate"
      >
        <div className="karen-surface flex max-w-md flex-col items-center space-y-4 rounded-2xl p-6 text-center">
          <Loader2
            className={`h-7 w-7 text-primary ${
              backendStatus === "checking" ? "animate-spin" : ""
            }`}
          />

          <div>
            <h2 className="text-base font-semibold text-foreground">
              {backendStatus === "failed"
                ? "Backend Connection Failed"
                : "Initializing KAREN"}
            </h2>

            <p className="mt-1 text-sm text-muted-foreground">
              {backendStatus === "failed"
                ? backendErrorMessage
                : "The workspace will stay mounted while backend services become ready."}
            </p>

            {backendStatus === "checking" && backendCheckRetries > 0 && (
              <p className="mt-2 text-xs text-muted-foreground">
                Retrying connection ({backendCheckRetries}/{MAX_BACKEND_RETRIES})...
              </p>
            )}
          </div>

          {backendStatus === "failed" && (
            <Button
              type="button"
              variant="outline"
              onClick={handleRetryBackend}
              className="gap-2"
            >
              <RefreshCw className="h-4 w-4" />
              Retry Connection
            </Button>
          )}
        </div>
      </div>
    );

  return (
    <AuthWrapper>
      <SessionProvider>
      <SidebarProvider>
        <div className="karen-app-shell flex h-dvh min-h-0 w-full flex-col overflow-hidden bg-background text-foreground">
          <header className="z-30 flex h-14 shrink-0 items-center justify-between border-b border-border/70 bg-background/80 px-3 backdrop-blur-xl md:px-4">
            <div className="flex items-center space-x-3">
              <AppSidebarTrigger className="mr-1 md:mr-2" />
              <Image
                src="/brand/karen-mark.svg"
                alt=""
                width={32}
                height={32}
                className="h-7 w-7 shrink-0 md:h-8 md:w-8"
                priority
              />
              <div className="flex items-baseline gap-2.5">
                <h1 className="font-mono text-sm font-bold uppercase tracking-[0.18em] text-foreground md:text-[15px]">
                  KAREN
                </h1>
                <span className="hidden font-mono text-[9px] font-semibold uppercase tracking-[0.16em] text-primary/80 sm:inline">
                  Local-first runtime
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {activeMainView !== "chat" && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setActiveMainView("chat")}
                  aria-label="Return to your Karen conversation"
                  className="gap-2"
                >
                  <MessageSquare className="h-4 w-4" />
                  <span className="hidden sm:inline">Ask Karen</span>
                </Button>
              )}
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Settings">
                  <SlidersHorizontal className="h-5 w-5 text-muted-foreground transition-colors hover:text-foreground" />
                </Button>
              </SheetTrigger>
              <SheetContent
                side="right"
                className="flex w-[90vw] max-w-sm flex-col p-0 sm:w-[480px]"
              >
                <SheetHeader className="border-b p-4">
                  <SheetTitle>Settings</SheetTitle>
                </SheetHeader>
                <div className="flex-1 overflow-y-auto">
                  <SettingsDialogComponent inSheet />
                </div>
              </SheetContent>
            </Sheet>
            </div>
          </header>

          <div className="flex min-h-0 flex-1 overflow-hidden">
            <Sidebar
              variant="sidebar"
              collapsible="icon"
              className="z-20 border-r border-sidebar-border/80 bg-sidebar/90 backdrop-blur-xl"
            >
              <AppSidebarHeader className="px-3 py-3">
                <div className="px-1">
                  <p className="karen-panel-label">Workspace</p>
                  <p className="mt-1 text-[11px] text-muted-foreground group-data-[collapsible=icon]:hidden">
                    KAREN operating surfaces
                  </p>
                </div>
              </AppSidebarHeader>

              <Separator className="my-1" />

              <DashboardNavigationContent>
                {PRIMARY_NAV.map((group, groupIndex) => (
                  <div key={group.section}>
                    <SidebarGroup>
                      <SidebarGroupLabel className="mb-2 px-2 font-mono text-[9px] font-bold uppercase tracking-[0.16em] text-muted-foreground/75">
                        {group.section}
                      </SidebarGroupLabel>
                      <SidebarMenu>
                        {group.items.map((item) => {
                          const Icon = item.icon;

                          return (
                            <SidebarMenuItem key={item.key}>
                              <SidebarMenuButton
                                onClick={() => setActiveMainView(item.key)}
                                isActive={activeMainView === item.key}
                                className={`w-full ${item.className ?? ""}`}
                              >
                                <Icon className="h-4 w-4" />
                                <span>{item.label}</span>
                              </SidebarMenuButton>
                            </SidebarMenuItem>
                          );
                        })}
                      </SidebarMenu>
                    </SidebarGroup>

                    {groupIndex < PRIMARY_NAV.length - 1 && (
                      <Separator className="mx-2 bg-border/50" />
                    )}
                  </div>
                ))}

                <Separator className="mx-2 bg-border/50" />

                <SidebarGroup>
                  <button
                    type="button"
                    aria-expanded={advancedToolsOpen}
                    aria-controls="karen-advanced-navigation"
                    onClick={() => setAdvancedToolsOpen((open) => !open)}
                    className="flex w-full items-center justify-between rounded-md px-2 py-2 text-left text-xs font-semibold text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    data-testid="advanced-tools-toggle"
                  >
                    <span>Advanced tools</span>
                    <ChevronDown
                      aria-hidden="true"
                      className={`h-4 w-4 transition-transform ${advancedToolsOpen ? "rotate-180" : ""}`}
                    />
                  </button>

                  <div
                    id="karen-advanced-navigation"
                    data-testid="advanced-tools-content"
                    hidden={!advancedToolsOpen}
                    className={advancedToolsOpen ? "mt-3 space-y-4 px-2" : "hidden"}
                  >
                    {RUNTIME_SUBGROUPS.map((subgroup) => {
                      const SubgroupIcon = subgroup.icon;

                      return (
                        <div key={subgroup.label}>
                          <p className="mb-2 flex items-center text-[10px] font-semibold uppercase text-muted-foreground/60">
                            <SubgroupIcon className="mr-1.5 h-3 w-3" />
                            {subgroup.label}
                          </p>

                          <SidebarMenu>
                            {subgroup.items.map((item) => {
                              const Icon = item.icon;

                              return (
                                <SidebarMenuItem key={item.key}>
                                  <SidebarMenuButton
                                    onClick={() => setActiveMainView(item.key)}
                                    isActive={activeMainView === item.key}
                                    className="h-8 w-full text-xs"
                                  >
                                    <Icon className="h-3.5 w-3.5" />
                                    {item.label}
                                  </SidebarMenuButton>
                                </SidebarMenuItem>
                              );
                            })}
                          </SidebarMenu>
                        </div>
                      );
                    })}

                    <div>
                      <p className="mb-2 flex items-center text-[10px] font-semibold uppercase text-muted-foreground/60">
                        <PlugZap className="mr-1.5 h-3 w-3" />
                        Plugin pages
                      </p>

                      <SidebarMenu>
                        {!pluginsLoading &&
                          sidebarEntries.map((entry) => (
                            <SidebarMenuItem key={entry.viewKey}>
                              <SidebarMenuButton
                                onClick={() => setActiveMainView(entry.viewKey)}
                                isActive={activeMainView === entry.viewKey}
                                className="h-8 w-full text-xs"
                              >
                                {renderPluginMenuIcon(
                                  entry.pluginId,
                                  entry.iconPath,
                                )}
                                {entry.label}
                              </SidebarMenuButton>
                            </SidebarMenuItem>
                          ))}

                        {pluginsLoading && (
                          <SidebarMenuItem>
                            <div className="flex h-8 items-center gap-2 px-2 text-xs text-muted-foreground">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              Loading plugins...
                            </div>
                          </SidebarMenuItem>
                        )}
                      </SidebarMenu>
                    </div>
                  </div>
                </SidebarGroup>
              </DashboardNavigationContent>

              <AppSidebarFooter className="relative overflow-visible border-t border-sidebar-border/70 bg-sidebar/70 p-3">
                <div className="flex flex-col items-center gap-1.5 text-center">
                  <Image
                    src="/brand/karen-mark.svg"
                    alt=""
                    width={18}
                    height={18}
                    className="h-[18px] w-[18px] opacity-70"
                  />
                  <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/60">
                    KAREN · Local-first runtime
                  </p>
                </div>
              </AppSidebarFooter>
            </Sidebar>

            <SidebarInset className="karen-workspace-grid flex min-h-0 flex-1 flex-col bg-transparent">
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-2 md:p-3">
                <div className="karen-surface flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
                  <div
                    id="persistent-karen-panel"
                    ref={karenPanelRef}
                    tabIndex={-1}
                    role={activeMainView !== "chat" && karenPanelOpen ? "dialog" : undefined}
                    aria-label={activeMainView !== "chat" && karenPanelOpen ? "Karen conversation" : undefined}
                    data-testid="persistent-karen-conversation"
                    className={backendStatus === "ready" && (activeMainView === "chat" || karenPanelOpen)
                      ? activeMainView === "chat" ? "flex min-h-0 flex-1 flex-col" : "fixed inset-x-2 top-16 bottom-20 z-50 flex flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl sm:inset-x-auto sm:right-3 sm:bottom-20 sm:w-[min(440px,calc(100vw-24px))]"
                      : "hidden"}
                    aria-hidden={backendStatus !== "ready" || (activeMainView !== "chat" && !karenPanelOpen)}
                  >
                    {USE_ASSISTANT_UI_CHAT ? <KarenAssistantChat /> : <ChatInterface />}
                  </div>
                  <div
                    key={activeMainView}
                    data-testid="workspace-scroll-region"
                    className={
                      activeMainView === "chat" && backendStatus === "ready"
                        ? "hidden"
                        : "min-h-0 flex-1 overflow-y-auto overscroll-contain"
                    }
                  >
                    {backendGate ?? (activeMainView === "chat" ? null : currentViewContent)}
                  </div>
                </div>
              </div>
            </SidebarInset>
            {activeMainView !== "chat" && backendStatus === "ready" && (
              <div className="fixed bottom-4 right-4 z-[60] flex gap-2">
                {karenPanelOpen && <Button type="button" variant="outline" onClick={() => setKarenPanelOpen(false)} aria-label="Collapse Karen conversation">Close panel</Button>}
                <Button ref={karenLauncherRef} type="button" onClick={() => setKarenPanelOpen((open) => !open)} aria-expanded={karenPanelOpen} aria-controls="persistent-karen-panel">
                  <MessageSquare className="mr-2 h-4 w-4" /> {karenPanelOpen ? "Hide Karen" : "Ask Karen"}
                </Button>
              </div>
            )}
          </div>
        </div>
      </SidebarProvider>
      </SessionProvider>
    </AuthWrapper>
  );
}
