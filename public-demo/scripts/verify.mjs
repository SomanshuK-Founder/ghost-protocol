import { readFile, readdir, lstat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { sourceFiles, outputFiles, csp } from './policy.mjs';
import { validateSource, validateStatic } from './guard.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
export async function verify() {
  const dist = path.join(root, 'dist');
  async function walk(directory) {
    const result = [];
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if ((await lstat(file)).isSymbolicLink()) throw new Error('Symlinks cannot enter static output');
      if (entry.isDirectory()) result.push(...await walk(file)); else result.push(path.relative(dist, file).replaceAll('\\', '/'));
    }
    return result.sort();
  }
  const files = await walk(dist);
  const expected = [...outputFiles, 'artifact-manifest.json'].sort();
  if (JSON.stringify(files) !== JSON.stringify(expected)) throw new Error('Unexpected or missing static artifact; inspect rather than publishing unknown files');
  for (const file of sourceFiles) validateSource(await readFile(path.join(dist, 'assets', file.replace('.ts', '.js')), 'utf8'), file);
  validateStatic(await readFile(path.join(dist, 'index.html'), 'utf8'), await readFile(path.join(dist, 'styles.css'), 'utf8'));
  const manifest = JSON.parse(await readFile(path.join(dist, 'artifact-manifest.json'), 'utf8'));
  for (const file of outputFiles) if (createHash('sha256').update(await readFile(path.join(dist, file))).digest('hex') !== manifest.files[file]) throw new Error(`Artifact hash mismatch: ${file}`);
  if (!(await readFile(path.join(dist, '_headers'), 'utf8')).includes(csp)) throw new Error('Missing hosting CSP');
  console.log(`Verified ${files.length} static files; isolated imports, no forbidden runtime capabilities, CSP and SHA-256 manifest valid.`);
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await verify();
