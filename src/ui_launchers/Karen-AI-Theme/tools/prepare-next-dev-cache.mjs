/**
 * Verify Karen's Next.js development artifact cache against the inputs that
 * determine webpack/Turbopack chunk manifests. This executes before next dev,
 * not from a running compiler and never in the production build command.
 *
 * Docker keeps .next in a named volume while npm ci can replace node_modules.
 * Reusing that volume after dependency or compiler-config changes can leave
 * stale dynamic-import chunk paths (including CopilotKit web-inspector).
 */
import { createHash } from 'node:crypto';
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const INPUTS = Object.freeze([
  'package.json',
  'package-lock.json',
  'next.config.ts',
  'tailwind.config.ts',
  'tools/prepare-copilotkit-styles.mjs',
]);
const MARKER = '.karen-dev-cache-fingerprint';
const SELF = fileURLToPath(import.meta.url);

function sourceFingerprint(root) {
  const hash = createHash('sha256');
  hash.update('karen-next-dev-cache-v1\0');
  hash.update(`node-major:${process.versions.node.split('.')[0]}\0`);
  hash.update(readFileSync(SELF));
  for (const name of INPUTS) {
    hash.update(`\0${name}\0`);
    hash.update(readFileSync(path.join(root, name)));
  }
  return hash.digest('hex');
}

function prepareNextDevCache(root) {
  const cachePath = path.join(root, '.next');
  const markerPath = path.join(cachePath, MARKER);
  const expected = sourceFingerprint(root);

  // A symlinked cache root is never safe to recursively clean: do not follow
  // it or overwrite a marker in an unrelated directory.
  if (existsSync(cachePath)) {
    const stat = lstatSync(cachePath);
    if (!stat.isDirectory() || stat.isSymbolicLink()) {
      throw new Error('Refusing to use a non-directory or linked Next.js cache');
    }
  } else {
    mkdirSync(cachePath, { recursive: true });
  }

  let current = null;
  try {
    const markerStat = lstatSync(markerPath);
    if (!markerStat.isFile() || markerStat.isSymbolicLink()) {
      throw new Error('Refusing to read a non-regular Next.js cache marker');
    }
    current = readFileSync(markerPath, 'utf8').trim();
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }

  // A production `next build` writes BUILD_ID into this same directory. A
  // matching dev marker does not authorize reuse of production compilation.
  if (current === expected && !existsSync(path.join(cachePath, 'BUILD_ID'))) return;

  // Remove *contents*, not the cache root: Docker's named-volume mount at
  // /app/.next must remain intact. rmSync unlinks child symlinks, not targets.
  for (const entry of readdirSync(cachePath)) {
    rmSync(path.join(cachePath, entry), { recursive: true, force: true });
  }
  writeFileSync(markerPath, `${expected}\n`, { flag: 'wx', mode: 0o600 });
}

prepareNextDevCache(process.cwd());
