import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
const screenshots = path.join(tmpdir(), 'ghost-phase5b', 'screenshots');
async function capture(page, name) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (await page.getByRole('dialog').count()) expect(await page.getByRole('dialog').evaluate(element => { const rect = element.getBoundingClientRect(); return rect.left >= 0 && rect.right <= innerWidth && rect.height <= innerHeight; })).toBe(true);
  await mkdir(screenshots, { recursive: true }); await page.screenshot({ path: path.join(screenshots, `${name}.png`), fullPage: true });
}
async function create(page, scenario = 'document', title) {
  await page.getByRole('button', { name: 'Create sample task', exact: true }).click();
  await page.getByLabel('Synthetic scenario').selectOption(scenario);
  if (title) await page.getByLabel('Sample task title').fill(title);
  await page.getByRole('dialog').getByRole('button', { name: 'Create sample task', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText(title ?? '');
  await page.getByRole('button', { name: 'Generate simulated plan' }).click();
}
async function review(page) { await page.getByRole('button', { name: 'Review pending approval' }).click(); }
async function decide(page, label) { await page.getByRole('button', { name: label, exact: true }).click(); await page.getByRole('dialog').getByRole('button', { name: label, exact: true }).click(); }
async function navigateSurface(page, label, width) {
  if (width < 901) { await page.getByRole('button', { name: 'Menu', exact: true }).click(); await page.getByRole('dialog').getByRole('link', { name: label, exact: true }).click(); }
  else await page.getByRole('link', { name: label, exact: true }).click();
}
for (const width of [390, 768, 1440, 1920]) test(`${width}px complete synthetic workflow, layout, focus and no external traffic`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const errors = []; const forbiddenRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' || message.type() === 'warning') errors.push(message.text()); });
  page.on('request', request => { const url = new URL(request.url()); if (url.origin !== 'http://127.0.0.1:4310' || /\/api\/|pair|session|gateway/.test(url.pathname) || !['GET', 'HEAD'].includes(request.method())) forbiddenRequests.push(request.url()); });
  await page.goto('/'); await expect(page).toHaveTitle(/Ghost Protocol public synthetic demo/);
  await page.keyboard.press('Tab'); await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
  await page.keyboard.press('Enter'); await expect(page.locator('#main')).toBeFocused();
  await expect(page.getByText('PUBLIC INTERACTIVE DEMO — SYNTHETIC DATA', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Your agent. Your call.');
  await capture(page, `overview-${width}`);
  await page.getByRole('button', { name: 'Create sample task', exact: true }).click();
  await capture(page, `task-creation-${width}`);
  await page.keyboard.press('Escape'); await expect(page.getByRole('button', { name: 'Create sample task', exact: true })).toBeFocused();
  await create(page); await capture(page, `planning-${width}`);
  await review(page); await capture(page, `pending-approval-${width}`);
  await page.getByRole('button', { name: 'Approve request', exact: true }).click();
  const dialog = page.getByRole('dialog'); await expect(dialog.getByRole('heading')).toHaveText('Approve request?');
  await expect(dialog.getByRole('button', { name: 'Go back' })).toBeFocused();
  await page.keyboard.press('Tab'); await expect(dialog.getByRole('button', { name: 'Approve request' })).toBeFocused();
  await page.keyboard.press('Tab'); await expect(dialog.locator('summary')).toBeFocused();
  await page.keyboard.press('Shift+Tab'); await expect(dialog.getByRole('button', { name: 'Approve request' })).toBeFocused();
  await capture(page, `approval-dialog-${width}`); await page.keyboard.press('Escape'); await expect(page.getByRole('button', { name: 'Approve request', exact: true })).toBeFocused();
  await decide(page, 'Approve request'); await expect(page.getByText('Approved, still paused.', { exact: false })).toBeVisible();
  await expect(page.getByText('SAFE_STOPPED', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open continuation controls →' }).click();
  await decide(page, 'Continue synthetic workflow');
  await expect(page.getByRole('heading', { name: 'Continued safely. Nothing executed.' })).toBeVisible();
  await capture(page, `safe-stopped-${width}`);
  await page.getByRole('button', { name: 'Inspect audit evidence →' }).click(); await capture(page, `audit-${width}`);
  await page.getByLabel('Filter event category').selectOption('Workflow'); await expect(page.locator('.timeline > li')).toHaveCount(1);
  await page.getByRole('button', { name: 'Inspect event' }).click(); await expect(page.locator('dialog pre')).toContainText('SYNTHETIC_BROWSER_DEMO'); await page.keyboard.press('Escape');
  await navigateSurface(page, 'Operation records', width);
  await expect(page.getByText('NOT_EXECUTED', { exact: true })).toBeVisible(); await capture(page, `operations-${width}`);
  for (const [label, name] of [['Document catalog', 'documents'], ['About this demo', 'about']]) { await navigateSurface(page, label, width); await capture(page, `${name}-${width}`); }
  await navigateSurface(page, 'Operation records', width);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length, cookies: document.cookie }))).toEqual({ local: 0, session: 0, cookies: '' });
  expect(forbiddenRequests).toEqual([]); expect(errors).toEqual([]);
  await decide(page, 'Reset demo'); await expect(page.getByRole('heading', { name: 'No operation proposed.' })).toBeVisible();
  await page.reload(); await expect(page.getByText('No operation proposed.', { exact: true })).toBeVisible();
});
for (const [name, phase] of [['Reject request', 'REJECTED'], ['Revoke permission', 'REVOKED']]) test(`${name} prevents continuation`, async ({ page }) => {
  await page.goto('/'); await create(page); await review(page); await decide(page, name);
  await expect(page.locator('.approval-card > .section-heading')).toContainText(phase);
  await expect(page.getByRole('button', { name: 'Approve request', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Open continuation controls →' })).toHaveCount(0);
});
for (const [label, expected] of [['Simulate expiry', 'EXPIRED'], ['Simulate UNKNOWN', 'UNKNOWN']]) test(`${label} is labelled and blocks retries`, async ({ page }) => {
  await page.goto('/'); await create(page); await review(page); await decide(page, 'Approve request'); await page.getByRole('button', { name: 'Open continuation controls →' }).click();
  await page.getByText('Explore stopping and uncertainty examples', { exact: true }).click(); await decide(page, label);
  await expect(page.locator('.workspace-status')).toContainText(expected);
  await expect(page.getByRole('button', { name: 'Continue synthetic workflow', exact: true })).toHaveCount(0);
});
test('denial, cancellation, sample email and untrusted text stay synthetic', async ({ page }) => {
  await page.goto('/'); await create(page, 'denied'); await expect(page.locator('.workspace-status')).toContainText('DENIED');
  await decide(page, 'Reset demo');
  await create(page, 'email', '<img src=x onerror=alert(1)>'); await expect(page.getByRole('heading', { level: 1 })).toHaveText('<img src=x onerror=alert(1)>');
  expect(await page.locator('main img').count()).toBe(0);
  await review(page); await expect(page.getByText('teammate@example.test', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Task workspace', exact: true }).click(); await decide(page, 'Cancel task'); await expect(page.locator('.workspace-status')).toContainText('CANCELLED');
});
test('CSP, asset-only server, reduced motion, navigation and refresh reset', async ({ page, request }) => {
  const response = await page.goto('/'); expect(response.headers()['content-security-policy']).toContain("connect-src 'none'");
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect(await page.locator('button').first().evaluate(element => getComputedStyle(element).transitionDuration)).toBe('0s');
  for (const route of ['documents', 'about']) { await page.getByRole('link', { name: route === 'about' ? 'About this demo' : 'Document catalog', exact: true }).click(); await capture(page, route); }
  await expect(page.getByText('Native OpenShell enforcement remains unverified.', { exact: false })).toBeVisible();
  for (const route of ['/api/app/v1/session', '/.env', '/../README.md', '/src/app.ts', '/assets/app.js.map']) expect((await request.get(route)).status()).toBe(404);
  expect((await request.post('/')).status()).toBe(404);
  await page.getByRole('link', { name: 'Overview', exact: true }).click(); await create(page); await page.reload(); await expect(page.getByRole('heading', { name: 'Your workspace is ready.' })).toBeVisible();
});
test('CSP actually blocks a connection before network dispatch', async ({ page }) => {
  let attempted = 0;
  await page.route('**/synthetic-network-probe', route => { attempted++; return route.abort(); });
  await page.goto('/');
  const blocked = await page.evaluate(async () => { try { await fetch('/synthetic-network-probe'); return false; } catch { return true; } });
  expect(blocked).toBe(true); expect(attempted).toBe(0);
});
test('invalid form input and cancelled confirmation do not change state', async ({ page }) => {
  await page.goto('/'); await page.getByRole('button', { name: 'Create sample task', exact: true }).click();
  await page.getByLabel('Sample task title').fill('   ');
  await page.getByRole('dialog').getByRole('button', { name: 'Create sample task', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('between 3 and 100');
  await page.keyboard.press('Escape');
  await create(page); await review(page); await page.getByRole('button', { name: 'Approve request', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Go back' }).click();
  await expect(page.locator('.approval-card > .section-heading')).toContainText('PENDING');
  await expect(page.getByRole('button', { name: 'Open continuation controls →' })).toHaveCount(0);
});
