export const csp = "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; worker-src 'none'; manifest-src 'none'";
export const headers = {
  'Content-Security-Policy': csp,
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  'Strict-Transport-Security': 'max-age=31536000',
  'Cache-Control': 'no-cache'
};
export const sourceFiles = ['app.ts', 'dom.ts', 'rail.ts', 'state.ts'];
export const outputFiles = ['index.html', '404.html', 'styles.css', 'ghost.svg', 'THIRD_PARTY_NOTICES.txt', '_headers', 'fonts/inter.woff2', 'fonts/space-grotesk.woff2', ...sourceFiles.map(file => `assets/${file.replace('.ts', '.js')}`)];
