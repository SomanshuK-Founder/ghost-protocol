import ts from 'typescript';
import { sourceFiles } from './policy.mjs';
const forbidden = new Set(['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'Worker', 'SharedWorker', 'ServiceWorker', 'sendBeacon', 'localStorage', 'sessionStorage', 'indexedDB', 'cookie', 'innerHTML', 'outerHTML', 'insertAdjacentHTML', 'eval', 'Function', 'require', 'process']);
const privateMarkers = /NEBIUS_API_KEY|SMTP_PASSWORD|MYSQL_PASSWORD|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|\/api\/app\/v1|127\.0\.0\.1|localhost|member_a_backend|backend\/app|frontend\/src|import\.meta\.env/i;
export function validateSource(text, filename) {
  if (privateMarkers.test(text)) throw new Error(`Private configuration or service marker in ${filename}`);
  const file = ts.createSourceFile(filename, text, ts.ScriptTarget.ES2022, true);
  function visit(node) {
    if (ts.isIdentifier(node) && forbidden.has(node.text)) throw new Error(`Forbidden browser capability ${node.text} in ${filename}`);
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node) && node.moduleSpecifier) {
      const target = node.moduleSpecifier?.text;
      if (!sourceFiles.some(file => target === `./${file.replace('.ts', '.js')}`)) throw new Error(`Import outside isolated runtime: ${target}`);
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) throw new Error('Dynamic imports are not allowed');
    ts.forEachChild(node, visit);
  }
  visit(file);
}
export function validateStatic(html, css) {
  if (/<script\b(?![^>]*\bsrc="\.\/assets\/app\.js")[^>]*>/i.test(html) || /\son\w+\s*=|\sstyle\s*=/i.test(html)) throw new Error('Inline script, handler or style is forbidden');
  if (!html.includes("connect-src 'none'") || !html.includes('SYNTHETIC') && !html.includes('synthetic')) throw new Error('Missing CSP or synthetic context');
  for (const match of css.matchAll(/url\(['"]?([^)'"\s]+)/g)) if (!['./fonts/inter.woff2', './fonts/space-grotesk.woff2'].includes(match[1])) throw new Error('Unapproved CSS asset URL');
  if (/@import|https?:|data:/i.test(css)) throw new Error('External CSS is forbidden');
}
