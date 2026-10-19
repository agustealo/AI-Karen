import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const settings = readFileSync(resolve(process.cwd(), 'src/components/settings/SettingsDialog.tsx'), 'utf8');
const models = readFileSync(resolve(process.cwd(), 'src/components/settings/ModelSettings.tsx'), 'utf8');

describe('settings UX ownership contract', () => {
  it('keeps settings navigation in the shell and persistence in existing panels', () => {
    expect(settings).toContain("render: () => <ModelSettings />");
    expect(settings).toContain("render: () => <ExpressionSettings />");
    expect(settings).toContain("render: () => <ModelDownloads adminMode={adminMode} />");
    expect(settings).not.toContain('localStorage.setItem');
    expect(settings).not.toContain("apiClient.put");
  });

  it('reports model load failures without silently presenting a configuration', () => {
    expect(models).toContain("setSettingsLoadError(message)");
    expect(models).toContain("if (!settings || settingsLoadError)");
    expect(models).toContain('role="alert"');
    expect(models).toContain('Retry loading settings');
    expect(models).toContain('onClick={() => void loadSettings()}');
    expect(models).toContain('Your saved provider and model selection have not been changed');
  });

  it('distinguishes saved provider selection from runtime health and draft changes', () => {
    expect(models).toContain('const hasUnsavedSelection');
    expect(models).toContain("Saved model:");
    expect(models).toContain("not proof of a currently executing model");
    expect(models).toContain("Provider or model selection changed locally");
    expect(models).toContain("Registered provider details");
    expect(models).not.toContain("Active Node Status");
    expect(models).not.toContain("Active Model</span>");
  });

  it('distinguishes detected runtimes from verified model inventory and handles clipboard denial', () => {
    expect(models).toContain('Detected');
    expect(models).toContain('No models were reported by this provider.');
    expect(models).toContain('saved model availability has not been verified');
    expect(models).toContain('Unable to copy setup command');
    expect(models).toContain('aria-label="Refresh model discovery"');
  });

  it('uses the canonical backend and runtime inventory instead of fabricated options', () => {
    expect(models).toContain("apiClient.get<ModelSettingsResponse>('/api/settings/model')");
    expect(models).toContain("normalizeModelSettingsResponse");
    expect(models).toContain("canSaveProviderModelSelection");
    expect(models).not.toContain("localStorage.setItem");
  });
});
