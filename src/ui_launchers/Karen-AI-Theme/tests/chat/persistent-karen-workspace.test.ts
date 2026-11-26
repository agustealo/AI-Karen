import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(resolve(process.cwd(), "src/app/dashboard/page.tsx"), "utf8");

describe("persistent Karen workspace shell", () => {
  it("owns the session above workspace switching", () => {
    expect(source).toContain("<AuthWrapper>\n      <PrincipalScopedSessionProvider>\n        <DashboardWorkspace />");
    expect(source).toContain("function DashboardWorkspace() {");
    expect(source).toContain("const { createNewSession } = useSession();");
    expect(source).toContain("<SidebarProvider>");
    expect(source).toContain("<SessionProvider storagePrincipal={{");
    expect(source).toContain("<RuntimeApprovalProvider>{children}</RuntimeApprovalProvider>");
    expect(source).toContain("tenant_id: user.tenant_id");
    expect(source).toContain("user_id: user.user_id");
    expect(source).toContain("</SidebarProvider>");
    expect(source).toContain("</PrincipalScopedSessionProvider>");
    expect(source).toContain("await createNewSession();");
    expect(source).not.toContain("chat: (\n        <SessionProvider>");
    expect(source).not.toContain("chat: (\n        <PrincipalScopedSessionProvider>");
  });

  it("uses the verified handoff for Mission Control conversation navigation", () => {
    expect(source).toContain("useVerifiedConversationHandoff(openChat)");
    expect(source).toContain("onOpenConversation={openConversation}");
    expect(source).not.toContain("await loadSession(conversationId);");
  });

  it("keeps a single conversation mounted while navigating other workspaces", () => {
    expect(source).toContain('data-testid="persistent-karen-conversation"');
    expect(source).toContain("activeMainView === \"chat\"");
    expect(source.match(/<KarenCopilotConsumerChat\b/g)).toHaveLength(1);
    expect(source).toContain('onOpenAgents={() => setActiveMainView("agents")}');
    expect(source).toContain("onOpenProviderSettings={() => {");
    expect(source).toContain('aria-label="Return to your Karen conversation"');
    expect(source).toContain('activeMainView === "chat" ? null : currentViewContent');
  });
});
