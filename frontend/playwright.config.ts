import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import path from "node:path";
export default defineConfig({
  testDir: "tests/browser",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  outputDir: path.join(tmpdir(), "ghost-frontend-playwright-results"),
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    browserName: "chromium",
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
