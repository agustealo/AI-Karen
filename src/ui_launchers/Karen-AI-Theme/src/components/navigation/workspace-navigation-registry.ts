import {
  Bell,
  Bot,
  Clock3,
  Drama,
  LayoutGrid,
  PanelsTopLeft,
  MessageSquare,
  PlugZap,
  ScrollText,
  Trophy,
  AudioLines,
  type LucideIcon,
} from "lucide-react";

export type WorkspaceDestination = {
  key: string;
  label: string;
  icon: LucideIcon;
};

export const WORKSPACE_PRIMARY_NAV: readonly WorkspaceDestination[] = [
  { key: "chat", label: "Chat", icon: MessageSquare },
  { key: "commsCenter", label: "Activity", icon: Bell },
  { key: "agentsOverview", label: "Automations", icon: Bot },
  { key: "tasks", label: "My Tasks", icon: ScrollText },
  { key: "pluginOverview", label: "Tools & plugins", icon: PlugZap },
];

export const WORKSPACE_ADVANCED_NAV: readonly WorkspaceDestination[] = [
  { key: "cardStudio", label: "Card Studio", icon: PanelsTopLeft },
  { key: "agents", label: "Agents", icon: Bot },
  { key: "jobs", label: "Jobs", icon: LayoutGrid },
  { key: "cronJobs", label: "Cron Jobs", icon: Clock3 },
];

export const WORKSPACE_PLUGIN_NAV: readonly WorkspaceDestination[] = [
  { key: "pocketTts", label: "Pocket TTS", icon: AudioLines },
];

export const WORKSPACE_PERSONAL_NAV: readonly WorkspaceDestination[] = [
  { key: "personaStudio", label: "Persona Studio", icon: Drama },
  { key: "growth", label: "Growth", icon: Trophy },
];

/** A visible active route must keep its containing disclosure discoverable. */
export function isNestedWorkspaceView(view: string, routes: ReadonlyArray<{ viewKey: string }>): boolean {
  return WORKSPACE_ADVANCED_NAV.some((item) => item.key === view)
    || WORKSPACE_PLUGIN_NAV.some((item) => item.key === view)
    || routes.some((item) => item.viewKey === view);
}
