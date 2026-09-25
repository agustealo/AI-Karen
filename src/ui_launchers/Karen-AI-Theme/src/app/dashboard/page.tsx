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
import {
  Bell,
  Binary,
  Bot as BotIcon,
  Brain,
  LayoutGrid,
  Loader2,
  MessageSquare,
  PlugZap,
  RefreshCw,
  ScrollText,
  SettingsIcon as SettingsIconLucide,
  SlidersHorizontal,
  UserCircle,
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
import ChatInterface, {
  SessionProvider,
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
} from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";

import { usePluginRegistry } from "@/plugin_host/registry";
import { usePluginRoutes } from "@/plugin_host/route-injector";

type ActiveView =
  | "chat"
  | "commsCenter"
  | "account"
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

const MAX_BACKEND_RETRIES = 10;
const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 30000;

const PRIMARY_NAV: Array<{
  section: string;
  items: NavItem[];
}> = [
  {
    section: "Assistant",
    items: [
      { key: "chat", label: "Chat", icon: MessageSquare },
      { key: "commsCenter", label: "Comms Center", icon: Bell },
    ],
  },
  {
    section: "Personal",
    items: [
      { key: "account", label: "My Account", icon: UserCircle },
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
      { key: "agentsOverview", label: "Agents Overview", icon: LayoutGrid },
      { key: "agents", label: "Agents", icon: BotIcon },
      { key: "tasks", label: "Tasks", icon: ScrollText },
      { key: "jobs", label: "Jobs", icon: LayoutGrid },
      { key: "cronJobs", label: "Cron Jobs", icon: Binary },
    ],
  },
];

export default function DashboardPage() {
  const [activeMainView, setActiveMainView] = useState<ActiveView>("chat");
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
      "Karen AI could not connect to backend services after multiple attempts.",
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
      chat: (
        <SessionProvider>
          <ChatInterface isActive={activeMainView === 'chat'} />
        </SessionProvider>
      ),
      settings: <SettingsDialogComponent />,
      pluginOverview: <PluginOverviewPage />,
      agentsOverview: <AgentsOverviewPage />,
      agents: <AgentsPage />,
      tasks: <TasksPage />,
      jobs: <JobsPage />,
      cronJobs: <CronJobsPage />,
      commsCenter: <CommsCenterPage />,
      account: <AccountPage />,
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

  if (backendStatus !== "ready") {
    return (
      <AuthWrapper>
        <div className="flex h-screen w-full items-center justify-center bg-background px-6">
          <div className="flex max-w-md flex-col items-center space-y-4 text-center">
            <Loader2
              className={`h-8 w-8 text-primary ${
                backendStatus === "checking" ? "animate-spin" : ""
              }`}
            />

            <div>
              <h2 className="text-lg font-semibold text-foreground">
                {backendStatus === "failed"
                  ? "Backend Connection Failed"
                  : "Initializing Karen AI"}
              </h2>

              <p className="mt-1 text-sm text-muted-foreground">
                {backendStatus === "failed"
                  ? backendErrorMessage
                  : "Connecting to backend services..."}
              </p>

              {backendStatus === "checking" && backendCheckRetries > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Retrying connection ({backendCheckRetries}/{MAX_BACKEND_RETRIES}
                  )...
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
      </AuthWrapper>
    );
  }

  return (
    <AuthWrapper>
      <SidebarProvider>
        <div className="flex h-screen w-full flex-col bg-background text-foreground">
          <header className="sticky top-0 z-30 flex items-center justify-between border-b border-border bg-background/90 p-3 shadow-sm backdrop-blur-md md:p-4">
            <div className="flex items-center space-x-3">
              <AppSidebarTrigger className="mr-1 md:mr-2" />
              <Brain className="h-7 w-7 shrink-0 text-primary md:h-8 md:w-8" />
              <h1 className="text-xl font-semibold tracking-tight md:text-2xl">
                Karen AI
              </h1>
            </div>

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
          </header>

          <div className="flex flex-1">
            <Sidebar
              variant="sidebar"
              collapsible="icon"
              className="z-20 border-r"
            >
              <AppSidebarHeader>
                <h2 className="px-2 py-1 text-lg font-semibold tracking-tight">
                  Navigation
                </h2>
              </AppSidebarHeader>

              <Separator className="my-1" />

              <AppSidebarContent className="space-y-4 p-2">
                {PRIMARY_NAV.map((group, groupIndex) => (
                  <div key={group.section}>
                    <SidebarGroup>
                      <SidebarGroupLabel className="mb-2 px-2 text-xs font-bold uppercase tracking-widest text-primary/70">
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
                  <SidebarGroupLabel className="mb-2 px-2 text-xs font-bold uppercase tracking-widest text-primary/70">
                    Agents & Plugins
                  </SidebarGroupLabel>

                  <div className="mt-4 space-y-4 px-2">
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
                        Plugins
                      </p>

                      <SidebarMenu>
                        <SidebarMenuItem>
                          <SidebarMenuButton
                            onClick={() => setActiveMainView("pluginOverview")}
                            isActive={activeMainView === "pluginOverview"}
                            className="h-8 w-full text-xs"
                          >
                            <LayoutGrid className="h-3.5 w-3.5" />
                            Plugin Overview
                          </SidebarMenuButton>
                        </SidebarMenuItem>

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
              </AppSidebarContent>

              <AppSidebarFooter className="relative overflow-visible border-t bg-muted/20 p-4">
                <div className="flex flex-col items-center gap-1">
                  <Brain className="h-4 w-4 text-primary/50" />
                  <p className="text-[10px] font-medium uppercase tracking-tighter text-muted-foreground/60">
                    Karen AI Unified Platform
                  </p>
                </div>
              </AppSidebarFooter>
            </Sidebar>

            <SidebarInset className="flex min-h-0 flex-1 flex-col">
              <div className="container flex flex-1 flex-col overflow-y-auto p-4 md:p-6">
                {currentViewContent}
              </div>
            </SidebarInset>
          </div>
        </div>
      </SidebarProvider>
    </AuthWrapper>
  );
}
