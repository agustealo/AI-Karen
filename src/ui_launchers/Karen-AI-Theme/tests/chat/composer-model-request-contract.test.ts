import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(process.cwd(), "src/components/chat");
const read = (file: string): string => readFileSync(resolve(root, file), "utf8");

describe("CopilotKit model request transport", () => {
  it("routes optional model requests through canonical owned CopilotKit properties", () => {
    const provider = read("copilotkit/KarenCopilotChat.tsx");
    const consumer = read("copilotkit/KarenCopilotConsumerChat.tsx");
    expect(provider).toContain("preferred_llm_provider: preferredProvider.trim()");
    expect(provider).toContain("preferred_model: preferredModel.trim()");
    expect(provider).toContain("workspace_run_id: workspaceRunId");
    expect(provider).toContain('runtimeUrl="/api/copilotkit"');
    expect(provider).toContain('agentId="default"');
    expect(consumer).toContain("preferredProvider={modelRequest?.provider ?? null}");
    expect(consumer).toContain("preferredModel={modelRequest?.model ?? null}");
    expect(consumer).toContain("workspaceRunId={workspaceRunId}");
    expect(consumer).toContain("onSelectionChange={handleModelRequest}");
  });

  it("discovers only backend-reported eligible providers without owning runtime selection", () => {
    const catalog = read("KarenComposerRuntimeCatalog.tsx");
    expect(catalog).toContain("Automatic routing (Karen default)");
    expect(catalog).toContain("model.available === true");
    expect(catalog).toContain("provider.healthy === true");
    expect(catalog).toContain("provider.configured === true");
    expect(catalog).toContain("provider.allowed_for_current_user !== false");
    expect(catalog).toContain("onSelectionChange(null)");
    expect(catalog).toContain("Automatic lets Karen choose an available model.");
    expect(catalog).toContain("Advanced provider and agent details");
  });

  it("does not retain a dependency on retired assistant-ui transport", () => {
    const provider = read("copilotkit/KarenCopilotChat.tsx");
    const consumer = read("copilotkit/KarenCopilotConsumerChat.tsx");
    expect(provider).not.toContain("assistant-ui/");
    expect(consumer).not.toContain("assistant-ui/");
  });
});
