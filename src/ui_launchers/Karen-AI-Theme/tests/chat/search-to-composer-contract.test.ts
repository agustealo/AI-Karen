import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

describe("search evidence handoff contract", () => {
  it("stages evidence in the canonical session rather than forging a chat event", () => {
    const panel = source("src/plugin_repo/intelligent-search/components/Panels.tsx");
    expect(panel).toContain("setSearchDraft(createSearchDraft(item))");
    expect(panel).not.toContain("new CustomEvent('karen:inject-message'");
  });
  it("requires an explicit user action to fill assistant-ui's composer", () => {
    const chat = source("src/components/chat/assistant-ui/KarenAssistantChat.tsx");
    expect(chat).toContain("useAssistantRuntime()");
    expect(chat).toContain("assistantRuntime.composer.setText(searchDraft)");
    expect(chat).toContain("Use in composer");
    expect(chat).not.toContain("assistantRuntime.composer.send(");
  });
});
