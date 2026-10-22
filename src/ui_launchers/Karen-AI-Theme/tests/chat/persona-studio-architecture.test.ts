import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");
const editor = read("src/components/settings/PersonaSettings.tsx");
const shell = read("src/app/dashboard/page.tsx");

describe("Persona Studio canonical integration", () => {
  it("mounts the existing settings editor as a workspace, not a second conversation", () => {
    expect(shell).toContain('key: "personaStudio"');
    expect(shell).toContain('data-testid="persona-studio-workspace"');
    expect(shell).toContain("<PersonaSettings />");
    expect(shell.match(/<SessionProvider>/g)).toHaveLength(1);
    expect(shell.match(/data-testid="persistent-karen-conversation"/g)).toHaveLength(1);
    expect(editor).not.toContain("<SessionProvider");
    expect(editor).not.toContain("<KarenAssistantChat");
    expect(editor).not.toContain("<ChatInterface");
  });

  it("gets persona records and active selection from backend APIs", () => {
    expect(editor).toContain("apiClient.get<PersonaRecord[]>(PERSONAS_ENDPOINT)");
    expect(editor).toContain("setAvailablePersonas(personas)");
    expect(editor).toContain("setActivePersonaId(preferences.active_persona_id ?? null)");
    expect(editor).toContain('data-testid="persona-gallery"');
    expect(editor).toContain('aria-label="Search personas"');
    expect(editor).toContain("filteredPersonas.map((persona)");
  });

  it("requires backend revision confirmation to activate and handles conflicts", () => {
    expect(editor).toContain("const selected = await apiClient.put<PersonaPreferences>(");
    expect(editor).toContain("{ active_persona_id: personaId, expected_revision: personaRevision }");
    expect(editor).toContain("setActivePersonaId(selected.active_persona_id ?? null)");
    expect(editor).toContain("error.status === 409");
    expect(editor).toContain("setPersonaRevision(null)");
    expect(editor).toContain("isSwitchingPersona || isSavingPersona");
  });

  it("does not elevate persona prose to system, provider, or tool authority", () => {
    expect(editor).toContain("Persona preferences cannot override");
    expect(editor).toContain("system policy, tool permissions, model routing");
    expect(editor).not.toContain("new HttpAgent(");
  });
});
