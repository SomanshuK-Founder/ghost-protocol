import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(
  new URL("../src/app/globals.css", import.meta.url),
  "utf8",
);
const tokens = Object.fromEntries(
  [...css.matchAll(/--([\w-]+):\s*(#[\da-f]{6})/gi)].map((match) => [
    match[1],
    match[2],
  ]),
);
function luminance(color: string) {
  const components = color
    .slice(1)
    .match(/../g)!
    .map((v) => parseInt(v, 16) / 255)
    .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return (
    components[0] * 0.2126 + components[1] * 0.7152 + components[2] * 0.0722
  );
}
test("text and status tokens meet WCAG AA contrast on all three surfaces", () => {
  for (const foreground of [
    "text",
    "muted",
    "iris",
    "cyan",
    "amber",
    "danger",
    "success",
  ]) {
    for (const background of ["canvas", "panel", "raised"]) {
      const a = luminance(tokens[foreground]);
      const b = luminance(tokens[background]);
      assert.ok(
        (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= 4.5,
        `${foreground} on ${background}`,
      );
    }
  }
});
test("explicit metadata and UI font sizes never drop below 12px", () => {
  for (const [, size] of css.matchAll(/font-size:\s*(\d+)px/g))
    assert.ok(Number(size) >= 12);
});
