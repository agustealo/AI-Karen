import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(resolve(process.cwd(), "src/app/dashboard/page.tsx"), "utf8");

describe("persistent Karen workspace shell", () => {
  it("owns the session above workspace switching", () => {
    expect(source).toContain("<AuthWrapper>\n      <SessionProvider>\n      <SidebarProvider>");
    expect(source).toContain("</SidebarProvider>\n      </SessionProvider>");
    expect(source).not.toContain("chat: (\n        <SessionProvider>");
  });

  it("keeps a single conversation mounted while navigating other workspaces", () => {
    expect(source).toContain('data-testid="persistent-karen-conversation"');
    expect(source).toContain("activeMainView === \"chat\"");
    expect(source).toContain("USE_ASSISTANT_UI_CHAT ? <KarenAssistantChat /> : <ChatInterface />");
    expect(source).toContain('aria-label="Return to your Karen conversation"');
    expect(source).toContain('activeMainView === "chat" ? null : currentViewContent');
  });
});
