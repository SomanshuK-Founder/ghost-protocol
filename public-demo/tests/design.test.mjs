import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const css = await readFile(new URL('../static/styles.css', import.meta.url), 'utf8');
const tokens = Object.fromEntries([...css.matchAll(/--([\w-]+):(#\w{6})/g)].map(match => [match[1], match[2]]));
function luminance(hex) {
  return hex.slice(1).match(/../g).map(part => parseInt(part, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
}
test('Control Room text and status colors retain AA contrast on all surfaces', () => {
  for (const surface of ['canvas', 'panel', 'raised']) for (const text of ['text', 'muted', 'iris', 'cyan', 'amber', 'danger', 'success']) {
    const a = luminance(tokens[text]), b = luminance(tokens[surface]);
    assert.ok((Math.max(a, b) + .05) / (Math.min(a, b) + .05) >= 4.5, `${text} on ${surface}`);
  }
});
test('labels never drop below 12px and reduced-motion / focus / touch styles exist', () => {
  for (const match of css.matchAll(/font-size:(\d+)px/g)) assert.ok(Number(match[1]) >= 12);
  for (const marker of [':focus-visible', 'prefers-reduced-motion:reduce', 'min-height:44px', '.skip-link:not(:focus)']) assert.ok(css.includes(marker));
});
