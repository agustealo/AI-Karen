import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const settingsDir = resolve(process.cwd(), 'src/components/settings');
const source = (file: string) => readFileSync(resolve(settingsDir, file), 'utf8');

describe('Settings reconciliation safety contract', () => {
  it('guards credential and provider mutations with administrator eligibility', () => {
    const model = source('ModelSettings.tsx');
    expect(model).toContain('const canManageRuntime =');
    expect(model).toContain('if (!canManageRuntime) return;');
    expect(model).toContain('settingsLoadError');
    expect(model).toContain('disabled={!canManageRuntime || isSaving');
  });

  it('guards shared model-download policy and storage mutations', () => {
    const downloads = source('ModelDownloads.tsx');
    expect(downloads).toContain('if (!adminMode || !policy)');
    expect(downloads).toContain('if (!adminMode) return;');
    expect(downloads).toContain('endpointErrors');
    expect(downloads).toContain('disabled={!adminMode');
  });

  it('retains fail-closed expression editing and admin-only navigation', () => {
    const expression = source('ExpressionSettings.tsx');
    const dialog = source('SettingsDialog.tsx');
    expect(expression).toContain('if (!canManageRuntime) return;');
    expect(expression).toContain('loadError');
    expect(dialog).toContain("...(adminMode ? [{");
    expect(dialog).toContain('settings sections');
  });
});
