import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { headers, outputFiles } from './policy.mjs';
import { verify } from './verify.mjs';
await verify();
const dist = fileURLToPath(new URL('../dist/', import.meta.url));
const allowed = new Set([...outputFiles, 'artifact-manifest.json']);
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8', '.json': 'application/json' };
const server = createServer(async (request, response) => {
  const file = (request.url ?? '/').split('?')[0].slice(1) || 'index.html';
  const found = ['GET', 'HEAD'].includes(request.method ?? '') && allowed.has(file);
  response.writeHead(found ? 200 : 404, { ...headers, 'Content-Type': types[path.extname(found ? file : '404.html')] ?? 'text/plain' });
  response.end(request.method === 'HEAD' ? undefined : await readFile(path.join(dist, found ? file : '404.html')));
});
server.listen(4310, '127.0.0.1', () => console.log('Static synthetic demo: http://127.0.0.1:4310 — no backend attached'));
