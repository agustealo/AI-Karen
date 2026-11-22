import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { renderPluginImportMap, syncPluginImportMap } from './sync-plugin-import-map.mjs';

function fixture(fn) {
  const root = mkdtempSync(join(tmpdir(), 'karen-import-map-'));
  const repo = join(root, 'plugin_repo');
  mkdirSync(repo);
  try {
    return fn({ root, repo });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function install(repo, name, { entry = 'PluginPage.tsx', providesUi = true } = {}) {
  const directory = join(repo, name);
  mkdirSync(directory);
  writeFileSync(join(directory, 'manifest.json'), JSON.stringify({
    name,
    id: name,
    plugin_id: name,
    version: '1.0.0',
    capabilities: { provides_ui: providesUi, prompt_first: true },
    entry: { entry_file: entry },
  }));
  if (!entry.includes('..')) {
    writeFileSync(join(directory, entry), 'export default function Page() { return null; }');
  }
  return directory;
}

test('installed packages generate deterministic ordered imports, without runtime enable claims', () => fixture(({ root, repo }) => {
  install(repo, 'time-query');
  install(repo, 'file-explorer');
  const output = join(root, 'map.ts');
  assert.equal(syncPluginImportMap({ pluginRepo: repo, output }), true);
  const content = readFileSync(output, 'utf8');
  assert.ok(content.includes('"file-explorer": () => import("@/plugin_repo/file-explorer/PluginPage")'));
  assert.ok(content.indexOf('"file-explorer"') < content.indexOf('"time-query"'));
  assert.equal(syncPluginImportMap({ pluginRepo: repo, output }), false);
  assert.equal(syncPluginImportMap({ pluginRepo: repo, output, check: true }), false);
}));

test('new approved installed package causes check-mode drift without altering output', () => fixture(({ root, repo }) => {
  install(repo, 'time-query');
  const output = join(root, 'map.ts');
  syncPluginImportMap({ pluginRepo: repo, output });
  const original = readFileSync(output, 'utf8');
  install(repo, 'file-explorer');
  assert.throws(() => syncPluginImportMap({ pluginRepo: repo, output, check: true }), /differs/);
  assert.equal(readFileSync(output, 'utf8'), original);
}));

test('missing entry and malformed metadata fail closed instead of publishing an importer', () => fixture(({ root, repo }) => {
  const directory = install(repo, 'file-explorer');
  const manifestPath = join(directory, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  manifest.entry.entry_file = 'NotInstalled.tsx';
  writeFileSync(manifestPath, JSON.stringify(manifest));
  assert.throws(() => renderPluginImportMap(repo), /ENOENT/);
  manifest.entry.entry_file = '../secret.tsx';
  writeFileSync(manifestPath, JSON.stringify(manifest));
  assert.throws(() => renderPluginImportMap(repo), /invalid/);
  manifest.entry.entry_file = 'PluginPage.tsx';
  manifest.capabilities.provides_ui = false;
  writeFileSync(manifestPath, JSON.stringify(manifest));
  assert.throws(() => renderPluginImportMap(repo), /contract invalid/);
}));

test('linked packages and source files are never trusted as installed UI', () => fixture(({ root, repo }) => {
  const outside = join(root, 'outside');
  mkdirSync(outside);
  symlinkSync(outside, join(repo, 'linked-plugin'));
  assert.throws(() => renderPluginImportMap(repo), /Linked plugin/);
}));

test('the repository checked-in baseline equals current installed package evidence', () => {
  const workspace = join(import.meta.dirname ?? new URL('..', import.meta.url).pathname, '..');
  const repo = join(workspace, 'src/plugin_repo');
  const output = join(workspace, 'src/plugin-import-map.generated.ts');
  assert.equal(readFileSync(output, 'utf8'), renderPluginImportMap(repo));
});
