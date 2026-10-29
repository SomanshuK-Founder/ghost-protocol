import { mkdir, readFile, writeFile, copyFile, readdir, lstat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import ts from 'typescript';
import { sourceFiles, outputFiles, headers } from './policy.mjs';
import { validateSource, validateStatic } from './guard.mjs';
import { verify } from './verify.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
const dist = path.join(root, 'dist');
if ((await readdir(root)).some(name => name.startsWith('.env'))) throw new Error('Environment files are forbidden in the public demo');
if (JSON.stringify((await readdir(path.join(root, 'src'))).sort()) !== JSON.stringify([...sourceFiles].sort())) throw new Error('Unreviewed runtime source file');
execFileSync(process.execPath, [path.join(root, 'node_modules/typescript/bin/tsc'), '--noEmit'], { cwd: root, stdio: 'inherit' });
await mkdir(path.join(dist, 'assets'), { recursive: true }); await mkdir(path.join(dist, 'fonts'), { recursive: true });
for (const file of sourceFiles) {
  const source = path.join(root, 'src', file);
  if ((await lstat(source)).isSymbolicLink()) throw new Error('Source symlinks are forbidden');
  const text = await readFile(source, 'utf8'); validateSource(text, file);
  const output = ts.transpileModule(text, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, sourceMap: false, removeComments: true, verbatimModuleSyntax: true } });
  await writeFile(path.join(dist, 'assets', file.replace('.ts', '.js')), output.outputText);
}
const html = await readFile(path.join(root, 'static/index.html'), 'utf8');
const css = await readFile(path.join(root, 'static/styles.css'), 'utf8'); validateStatic(html, css);
for (const file of ['index.html', 'styles.css', 'ghost.svg']) await copyFile(path.join(root, 'static', file), path.join(dist, file));
await writeFile(path.join(dist, '404.html'), '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Ghost Protocol · Page not found</title><link rel="stylesheet" href="/styles.css"><main><h1>Page not found.</h1><p>This is a static synthetic demo. <a href="/">Open the Control Room</a>.</p></main></html>');
let notices = 'Ghost Protocol public interactive synthetic demonstration\n\nOriginal team-owned demo code and visual assets are MIT licensed. Third-party fonts retain their OFL terms below.\n\n=== Original Ghost Protocol contributions (MIT) ===\n' + await readFile(path.join(root, 'LICENSE'), 'utf8');
for (const [name, output] of [['inter', 'inter'], ['space-grotesk', 'space-grotesk']]) {
  const pkg = path.join(root, 'node_modules/@fontsource-variable', name);
  await copyFile(path.join(pkg, `files/${name}-latin-wght-normal.woff2`), path.join(dist, `fonts/${output}.woff2`));
  notices += `\n\n=== ${name} variable font (Fontsource 5.3.0) ===\n${await readFile(path.join(pkg, 'LICENSE'), 'utf8')}`;
}
await writeFile(path.join(dist, 'THIRD_PARTY_NOTICES.txt'), notices);
await writeFile(path.join(dist, '_headers'), '/*\n' + Object.entries(headers).map(([key, value]) => `  ${key}: ${value}`).join('\n') + '\n');
await writeFile(path.join(root, 'vercel.json'), JSON.stringify({ framework: null, installCommand: 'npm ci', buildCommand: 'npm run build', outputDirectory: 'dist', headers: [{ source: '/(.*)', headers: Object.entries(headers).map(([key, value]) => ({ key, value })) }] }, null, 2) + '\n');
const manifest = { mode: 'PUBLIC_INTERACTIVE_SYNTHETIC_DEMO', files: {} };
for (const file of outputFiles) manifest.files[file] = createHash('sha256').update(await readFile(path.join(dist, file))).digest('hex');
await writeFile(path.join(dist, 'artifact-manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
await verify();
