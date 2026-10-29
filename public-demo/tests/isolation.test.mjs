import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { validateSource, validateStatic } from '../scripts/guard.mjs';
import { sourceFiles, csp } from '../scripts/policy.mjs';
for (const snippet of [
  'import x from "../../frontend/src/lib/api/client.js";',
  'import x from "https://example.test/x.js";',
  'import x from "./private.js";', 'import("./state.js");',
  'fetch("/x");', 'window.fetch("/x");', 'new WebSocket("wss://example.test");',
  'new XMLHttpRequest();', 'navigator.sendBeacon("/x");', 'localStorage.setItem("a","b");',
  'sessionStorage.getItem("a");', 'indexedDB.open("db");', 'document.cookie;',
  'element.innerHTML = value;', 'element.insertAdjacentHTML("beforeend", value);',
  'eval(value);', 'new Function(value);', 'process.env.KEY;', 'const x = "NEBIUS_API_KEY";'
]) test(`build rejects ${snippet.split(';')[0]}`, () => assert.throws(() => validateSource(snippet, 'probe.ts')));
test('all runtime imports are isolated and runtime has no forbidden capabilities', async () => {
  for (const file of sourceFiles) validateSource(await readFile(new URL(`../src/${file}`, import.meta.url), 'utf8'), file);
});
test('static policy disallows connections, inline scripts, external CSS and image URLs', () => {
  assert.match(csp, /connect-src 'none'/); assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval/);
  const html = '<title>synthetic</title><meta content="connect-src \'none\'"><script src="./assets/app.js" type="module"></script>';
  assert.doesNotThrow(() => validateStatic(html, 'p{color:red}'));
  assert.throws(() => validateStatic(html + '<script>alert(1)</script>', ''));
  assert.throws(() => validateStatic(html, 'p{background:url(https://example.test/a)}'));
});
