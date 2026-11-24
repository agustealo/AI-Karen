import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string): string =>
  readFileSync(resolve(process.cwd(), path), "utf8");

const consumer = read("src/components/chat/copilotkit/KarenCopilotConsumerChat.tsx");
const shell = read("src/components/chat/copilotkit/KarenCopilotChat.tsx");
const catalog = read("src/components/chat/KarenComposerRuntimeCatalog.tsx");
const rail = read("src/components/chat/copilotkit/KarenCopilotVerifiedRail.tsx");
const styles = read("src/app/kari-os.css");

describe("provider/model and selected response context alignment", () => {
  it("mounts model controls at the top of the conversation column beside the existing context rail", () => {
    const chatMount = consumer.indexOf("<KarenCopilotChat\n");
    expect(chatMount).toBeGreaterThan(0);
    expect(consumer.slice(0, chatMount)).not.toContain('data-testid="karen-copilot-model-discovery"');
    expect(consumer.slice(chatMount)).toContain("modelControls={");
    expect(consumer.slice(chatMount)).toContain('data-testid="karen-copilot-model-discovery"');

    expect(shell).toContain('className="flex min-h-0 min-w-0 flex-1 flex-col xl:flex-row"');
    expect(shell).toContain('data-testid="karen-copilot-conversation-column"');
    expect(shell).toMatch(/\{modelControls\}\s*<KarenCopilotControlledChat/);
    expect(shell).toMatch(/<\/div>\s*<KarenCopilotVerifiedRail \/>/);
    expect(shell).toContain("<KarenCopilotPinnedDock />");
  });

  it("preserves the shared vertical start, scroll region and accessible responsive context", () => {
    expect(consumer).toContain('className="shrink-0 border-b border-border/60 bg-background/80 px-3 py-3 sm:px-4"');
    expect(rail).toContain('className="hidden h-full min-h-0 w-[21rem]');
    expect(rail).toContain('xl:block');
    expect(rail).toContain('data-testid="karen-copilot-mobile-intelligence"');
    expect(rail).toContain('xl:hidden');
    expect(rail).toContain('className="order-first w-full shrink-0');
    expect(rail).toContain("Evidence linked to the selected saved response");
    expect(styles).toContain('[data-kari-root][data-testid="karen-copilot-consumer-chat"] [data-testid="karen-copilot-model-discovery"]');
  });

  it("keeps visible backend-authorized provider/model choices with diagnostics secondary", () => {
    expect(catalog).toContain("Provider / Model");
    expect(catalog).toContain('aria-label="Requested model provider"');
    expect(catalog).toContain('aria-label="Requested model"');
    expect(catalog).toContain("isRuntimeProviderOperational(provider)");
    expect(catalog).toContain("model.available === true");
    expect(catalog).toContain("Advanced provider and agent details");
    expect(catalog).toContain("Refresh models");
    expect(catalog).toContain("Configure providers");
    expect(catalog).not.toContain("providerRegistryFallback");
    expect(consumer).toContain("disabled={runBusy}");
    expect(consumer).toContain("preferredProvider={modelRequest?.provider ?? null}");
    expect(consumer).toContain("preferredModel={modelRequest?.model ?? null}");
  });
});
