import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const settings = readFileSync(resolve(process.cwd(), 'src/components/settings/SettingsDialog.tsx'), 'utf8');
const models = readFileSync(resolve(process.cwd(), 'src/components/settings/ModelSettings.tsx'), 'utf8');
const expression = readFileSync(resolve(process.cwd(), 'src/components/settings/ExpressionSettings.tsx'), 'utf8');
const downloads = readFileSync(resolve(process.cwd(), 'src/components/settings/ModelDownloads.tsx'), 'utf8');
const facts = readFileSync(resolve(process.cwd(), 'src/components/settings/PersonalFactsSettings.tsx'), 'utf8');
const privacy = readFileSync(resolve(process.cwd(), 'src/components/settings/PrivacySettings.tsx'), 'utf8');

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

  it('does not fabricate an enabled expression engine after an unavailable inventory', () => {
    expect(expression).toContain("setLoadError('Karen could not load expression settings");
    expect(expression).toContain("if (loadError || !exprSettings || !modelSettings)");
    expect(expression).toContain('Expression settings unavailable');
    expect(expression).toContain('Retry loading expression settings');
    expect(expression).toContain('const currentEngineConfig = exprSettings.engines?.[activeEngine]');
    expect(expression).not.toContain('fallback_eligible: true,\\n    metadata: {}');
    expect(expression).toContain('Saved primary');
    expect(expression).toContain('"Enabled" : "Disabled"');
  });

  it('never presents stale download reads as healthy empty inventory', () => {
    expect(downloads).toContain('setInstalled(null)');
    expect(downloads).toContain('setDiscovery(null)');
    expect(downloads).toContain('setRuntimeTelemetry(null)');
    expect(downloads).toContain("delete next.jobs");
    expect(downloads).toContain("endpointErrors.jobs ? 'Unavailable' : 'Idle'");
    expect(downloads).toContain("installed ?");
    expect(downloads).toContain('Discovery status unavailable');
  });

  it('blocks download actions when queue or policy truth is unavailable', () => {
    expect(downloads).toContain('Download job status is unavailable.');
    expect(downloads).toContain('Existing jobs may still be running.');
    expect(downloads).toContain('endpointErrors.jobs ? "Jobs unavailable"');
    expect(downloads).toContain('!endpointErrors.jobs &&');
    expect(downloads).toContain('!endpointErrors.policy &&');
    expect(downloads).toContain('!endpointErrors.channels;');
    expect(downloads).toContain('disabled={Boolean(endpointErrors.jobs) || !canPauseJob');
    expect(downloads).toContain('disabled={Boolean(endpointErrors.jobs) || retryingJobs');
  });

  it('does not invent personal memory creation times or reuse stale privacy request status', () => {
    expect(facts).toContain('created_at:');
    expect(facts).not.toContain('new Date().toISOString()');
    expect(privacy).toContain('setRequestStatus(null)');
    expect(privacy).toContain('setRequestStatus(response)');
    expect(privacy).toContain('setLastRequest(response)');
  });

  it('uses the canonical backend and runtime inventory instead of fabricated options', () => {
    expect(models).toContain("apiClient.get<ModelSettingsResponse>('/api/settings/model')");
    expect(models).toContain("normalizeModelSettingsResponse");
    expect(models).toContain("canSaveProviderModelSelection");
    expect(models).not.toContain("localStorage.setItem");
  });
});
