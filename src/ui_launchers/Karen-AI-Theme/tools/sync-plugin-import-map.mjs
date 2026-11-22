/** Build-only importer projection of already installed frontend UI packages.
 * This never installs, enables, authorizes or discovers backend plugins.
 */
import { existsSync, lstatSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const workspace = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PLUGIN_ID = /^[a-z][a-z0-9-]{0,49}$/;
const SEGMENT = /^[A-Za-z][A-Za-z0-9_.-]*$/;
const ENTRY_EXT = /\.(tsx|jsx)$/;

function regularFile(file) {
  const stat = lstatSync(file);
  return stat.isFile() && !stat.isSymbolicLink();
}

function verifiedEntry(packageDir, entry) {
  if (typeof entry !== 'string' || !entry || entry.includes('\\') || entry.startsWith('/')) {
    throw new Error('Plugin entry must be a relative POSIX file path');
  }
  const segments = entry.split('/');
  if (segments.some((segment) => !SEGMENT.test(segment) || segment === '.' || segment === '..') ||
      !ENTRY_EXT.test(segments.at(-1))) {
    throw new Error('Plugin UI entry path is invalid');
  }
  let current = packageDir;
  for (let index = 0; index < segments.length; index += 1) {
    current = join(current, segments[index]);
    const stat = lstatSync(current);
    if (stat.isSymbolicLink() ||
        (index < segments.length - 1 && !stat.isDirectory()) ||
        (index === segments.length - 1 && !stat.isFile())) {
      throw new Error('Plugin UI entry is not a regular file');
    }
  }
  return segments.join('/').replace(ENTRY_EXT, '');
}

export function renderPluginImportMap(pluginRepo) {
  if (!existsSync(pluginRepo) || !lstatSync(pluginRepo).isDirectory() ||
      lstatSync(pluginRepo).isSymbolicLink()) {
    throw new Error('Installed plugin repository is missing or untrusted');
  }
  const imports = [];
  for (const id of readdirSync(pluginRepo).sort()) {
    const directory = join(pluginRepo, id);
    const stat = lstatSync(directory);
    if (!stat.isDirectory() || stat.isSymbolicLink()) {
      if (stat.isSymbolicLink()) throw new Error('Linked plugin package forbidden');
      continue;
    }
    if (!PLUGIN_ID.test(id)) throw new Error('Invalid installed plugin identifier');
    const manifestPath = join(directory, 'manifest.json');
    if (!existsSync(manifestPath) || !regularFile(manifestPath)) {
      throw new Error('Installed plugin manifest missing or linked');
    }
    let manifest;
    try {
      manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    } catch {
      throw new Error('Installed plugin manifest is not valid JSON');
    }
    if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest) ||
        manifest.name !== id || (manifest.id !== undefined && manifest.id !== id) ||
        (manifest.plugin_id !== undefined && manifest.plugin_id !== id) ||
        manifest.capabilities?.provides_ui !== true ||
        manifest.capabilities?.prompt_first !== true ||
        !manifest.entry || typeof manifest.entry !== 'object' ||
        typeof manifest.entry.entry_file !== 'string') {
      throw new Error('Installed plugin UI manifest contract invalid: ' + id);
    }
    const entry = verifiedEntry(directory, manifest.entry.entry_file);
    imports.push('  ' + JSON.stringify(id) + ': () => import(' +
      JSON.stringify('@/plugin_repo/' + id + '/' + entry) + '),');
  }
  return [
    '/**',
    ' * Generated plugin import map (frontend).',
    ' *',
    ' * Single loading authority: \`plugin_host/loader.ts\` must import from here and',
    ' * resolve ONLY installed UI packages under \`src/plugin_repo/<plugin-id>/\`.',
    ' */',
    "import type React from 'react';",
    '',
    'export type PluginImporter = () => Promise<{',
    '  default: React.ComponentType<Record<string, unknown>>;',
    '}>;',
    '',
    'export type PluginImportMap = Record<string, PluginImporter>;',
    '',
    'export const PLUGIN_IMPORT_MAP: PluginImportMap = {',
    ...imports,
    '};',
    '',
  ].join('\n');
}

export function syncPluginImportMap({
  pluginRepo = join(workspace, 'src/plugin_repo'),
  output = join(workspace, 'src/plugin-import-map.generated.ts'),
  check = false,
} = {}) {
  const rendered = renderPluginImportMap(pluginRepo);
  if (existsSync(output) && lstatSync(output).isSymbolicLink()) {
    throw new Error('Refusing linked import-map destination');
  }
  const current = existsSync(output) && regularFile(output)
    ? readFileSync(output, 'utf8') : null;
  if (current === rendered) return false;
  if (check) throw new Error('Plugin import map differs from installed package evidence');
  const temporary = output + '.' + process.pid + '.tmp';
  try {
    writeFileSync(temporary, rendered, { flag: 'wx', mode: 0o600 });
    renameSync(temporary, output);
  } finally {
    if (existsSync(temporary)) unlinkSync(temporary);
  }
  return true;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    syncPluginImportMap({ check: process.argv.includes('--check') });
  } catch (error) {
    process.stderr.write('Plugin import map verification failed: ' +
      (error instanceof Error ? error.message : 'unknown error') + '\n');
    process.exitCode = 1;
  }
}
